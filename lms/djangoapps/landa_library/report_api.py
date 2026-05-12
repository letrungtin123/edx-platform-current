from django.contrib.auth.models import User
from django.db.models import Count, Avg, FloatField, OuterRef, Exists, Subquery, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from datetime import timedelta
import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser

from common.djangoapps.student.models import CourseEnrollment
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from lms.djangoapps.grades.models import PersistentCourseGrade

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import (
    SessionAuthenticationAllowInactiveUser,
)
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from lms.djangoapps.grades.models import PersistentCourseGrade
from lms.djangoapps.grades.models import PersistentCourseGrade
from lms.djangoapps.courseware.models import StudentModule
from openedx.core.djangoapps.content.block_structure.api import get_course_in_cache
from openedx.core.djangoapps.content.block_structure.exceptions import BlockStructureNotFound
from completion.models import BlockCompletion


log = logging.getLogger(__name__)

class IsSuperUser(permissions.BasePermission):
    """Chỉ cho phép superuser."""
    def has_permission(self, request, view):
        return request.user and request.user.is_superuser


def _calc_avg_completion_rate(enrollment_qs):
    """
    Tính trung bình cộng % tiến độ của tất cả enrollment.
    
    Tối ưu: group by course thay vì loop per-enrollment.
    - Python loop: O(courses) ~500 thay vì O(enrollments) ~1M
    - SQL queries: 3 aggregate queries, không load raw data vào RAM
    - Công thức: weighted_avg = SUM(avg_progress_per_course × n_enrolled) / total_enrolled
    """
    from django.db.models import Sum
    
    # Query 1: Đếm enrollments per course + tổng enrollments
    course_stats = list(
        enrollment_qs
        .values('course_id')
        .annotate(n=Count('id'))
        .values_list('course_id', 'n')
    )
    if not course_stats:
        return 0.0
    
    total_enrolled = sum(n for _, n in course_stats)
    course_ids = [str(cid) for cid, _ in course_stats]
    course_n_map = {str(cid): n for cid, n in course_stats}
    
    # Query 2: Tổng unique blocks completable per course
    course_total_blocks = {}
    for row in (
        BlockCompletion.objects
        .filter(context_key__in=course_ids, completion__gte=1.0)
        .values('context_key')
        .annotate(total=Count('block_key', distinct=True))
    ):
        course_total_blocks[str(row['context_key'])] = row['total']
    
    if not course_total_blocks:
        return 0.0
    
    # Query 3: Tổng completed blocks per course (chỉ cho enrolled users)
    # Dùng Subquery cho user_ids — không load list vào RAM
    course_sum_completed = {}
    for row in (
        BlockCompletion.objects
        .filter(
            context_key__in=list(course_total_blocks.keys()),
            completion__gte=1.0,
            user_id__in=Subquery(enrollment_qs.values('user_id').distinct())
        )
        .values('context_key')
        .annotate(total_completed=Count('id'))
    ):
        course_sum_completed[str(row['context_key'])] = row['total_completed']
    
    # Tính weighted average — loop O(courses), không phải O(enrollments)
    weighted_sum = 0.0
    for cid_str in course_ids:
        total_blocks = course_total_blocks.get(cid_str, 0)
        if total_blocks == 0:
            continue
        n_enrolled = course_n_map.get(cid_str, 0)
        sum_completed = course_sum_completed.get(cid_str, 0)
        # avg_progress = (sum_completed / n_enrolled) / total_blocks * 100
        avg_progress = min((sum_completed / (n_enrolled * total_blocks)) * 100.0, 100.0)
        weighted_sum += avg_progress * n_enrolled
    
    return round(weighted_sum / total_enrolled, 1)


class ReportSummaryView(APIView):
    """
    API Báo cáo tổng hợp dành cho Superuser.
    Hỗ trợ filter theo tháng/năm qua query params: ?month=5&year=2026
    Mặc định: tháng hiện tại.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUser]
    parser_classes = [JSONParser]

    def get(self, request):
        try:
            now = timezone.now()

            # ── Xác định tháng/năm cần xem ──────────────────────────────
            try:
                month = int(request.query_params.get('month', now.month))
                year  = int(request.query_params.get('year',  now.year))
                if not (1 <= month <= 12):
                    month = now.month
            except (ValueError, TypeError):
                month, year = now.month, now.year

            # Khoảng thời gian đầu/cuối tháng được chọn (aware datetime)
            import calendar
            from datetime import datetime
            month_start = timezone.make_aware(datetime(year, month, 1))
            last_day    = calendar.monthrange(year, month)[1]
            month_end   = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

            is_current_month = (month == now.month and year == now.year)

            group_id = request.query_params.get('group_id')
            users_qs = User.objects.filter(is_active=True)
            if group_id:
                users_qs = users_qs.filter(group_memberships__subgroup__org_group_id=group_id).distinct()

            # ── 1. User Metrics ──────────────────────────────────────────
            total_learners = users_qs.filter(date_joined__lte=month_end).count()

            # Tỉ lệ hoàn thành: trung bình cộng % tiến độ tất cả enrollment
            # Dùng BlockCompletion thay vì PersistentCourseGrade (vì grading không dùng)
            enrollment_base = CourseEnrollment.objects.filter(
                is_active=True, created__lte=month_end
            )
            if group_id:
                enrollment_base = enrollment_base.filter(user__in=users_qs)

            completion_rate = _calc_avg_completion_rate(enrollment_base)

            # Học viên hoạt động: login trong tháng được chọn
            active_learners = users_qs.filter(
                last_login__gte=month_start,
                last_login__lte=month_end,
            ).count()

            # ── 2. Tổng lượt đăng ký trong tháng ──────────────────────────
            month_enrollments = CourseEnrollment.objects.filter(
                created__gte=month_start, created__lte=month_end
            )
            if group_id:
                month_enrollments = month_enrollments.filter(user__in=users_qs)
            total_enrollments = month_enrollments.count()

            # ── 7. Trend — 4 tháng (2 tháng trước, tháng hiện tại, 1 tháng sau) ─────────────────
            uncompleted_trend = []
            today = timezone.now()

            from django.db.models import F, IntegerField as DjIntField
            from django.db.models.functions import Coalesce as CoalesceF
            import calendar
            from datetime import datetime

            for offset in [-2, -1, 0, 1]:
                target_month = month + offset
                target_year = year
                if target_month <= 0:
                    target_month += 12
                    target_year -= 1
                elif target_month > 12:
                    target_month -= 12
                    target_year += 1

                target_last_day = calendar.monthrange(target_year, target_month)[1]
                m_end = timezone.make_aware(datetime(target_year, target_month, target_last_day, 23, 59, 59))

                # Nếu là tháng hoàn toàn trong tương lai, gán 0
                if m_end > today and (target_year > today.year or (target_year == today.year and target_month > today.month)):
                    uncompleted_trend.append({
                        "day": f"T{target_month}/{target_year % 100}",
                        "count": 0
                    })
                    continue

                # Tất cả enrollment active tính đến cuối tháng này
                enroll_qs = CourseEnrollment.objects.filter(
                    is_active=True,
                    created__lte=m_end,
                )
                if group_id:
                    enroll_qs = enroll_qs.filter(user__in=users_qs)

                total_m = enroll_qs.count()

                # Annotate completion counts
                user_done_sq = Subquery(
                    BlockCompletion.objects.filter(
                        user_id=OuterRef('user_id'),
                        context_key=OuterRef('course_id'),
                        completion__gte=1.0,
                    ).order_by().values('user_id', 'context_key').annotate(
                        cnt=Count('block_key', distinct=True)
                    ).values('cnt')[:1],
                    output_field=DjIntField(),
                )
                course_total_sq = Subquery(
                    BlockCompletion.objects.filter(
                        context_key=OuterRef('course_id'),
                        completion__gte=1.0,
                    ).order_by().values('context_key').annotate(
                        cnt=Count('block_key', distinct=True)
                    ).values('cnt')[:1],
                    output_field=DjIntField(),
                )

                completed_m = enroll_qs.annotate(
                    _ud=CoalesceF(user_done_sq, Value(0)),
                    _ct=CoalesceF(course_total_sq, Value(0)),
                ).filter(
                    _ct__gt=0,
                    _ud__gte=F('_ct'),
                ).count()

                uncompleted = max(total_m - completed_m, 0)

                uncompleted_trend.append({
                    "day": f"T{target_month}/{target_year % 100}",
                    "count": uncompleted
                })

            return Response({
                "meta": {
                    "month": month,
                    "year": year,
                    "month_label": f"Tháng {month}/{year}",
                    "is_current_month": is_current_month,
                },
                "overview": {
                    "total_learners": total_learners,
                    "completion_rate": completion_rate,
                    "active_learners": active_learners,
                    "total_enrollments": total_enrollments
                },
                "lists": {
                    "top_courses": [],
                    "uncompleted_learners": [],
                    "uncompleted_trend": uncompleted_trend
                }
            })

        except Exception as e:
            log.exception("Error generating report summary")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class ReportChartTrendView(APIView):
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUser]
    parser_classes = [JSONParser]

    def get(self, request):
        try:
            now = timezone.now()
            year = int(request.query_params.get('year', now.year))
            metric = request.query_params.get('metric', 'total_learners')
            group_id = request.query_params.get('group_id')

            import calendar
            from datetime import datetime
            from lms.djangoapps.landa_groups.models import SubGroup

            # Giới hạn tháng: nếu năm hiện tại thì chỉ tới tháng hiện tại
            if year > now.year:
                max_month = 0
            elif year == now.year:
                max_month = now.month
            else:
                max_month = 12

            result = []
            
            if group_id:
                subgroups = SubGroup.objects.filter(org_group_id=group_id)
                for month in range(1, 13):
                    month_data = {"month": f"T{month}"}
                    
                    if month > max_month:
                        # Tháng tương lai: gán 0 cho tất cả subgroup
                        for sg in subgroups:
                            month_data[sg.name] = 0
                        result.append(month_data)
                        continue

                    month_start = timezone.make_aware(datetime(year, month, 1))
                    last_day = calendar.monthrange(year, month)[1]
                    month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))
                    
                    for sg in subgroups:
                        sg_users = User.objects.filter(group_memberships__subgroup=sg, is_active=True).distinct()
                        val = 0
                        if metric == 'total_learners':
                            val = sg_users.filter(date_joined__lte=month_end).count()
                        elif metric == 'completion_rate':
                            sg_enroll = CourseEnrollment.objects.filter(is_active=True, user__in=sg_users, created__lte=month_end)
                            val = _calc_avg_completion_rate(sg_enroll)
                        elif metric == 'active_learners':
                            val = sg_users.filter(last_login__gte=month_start, last_login__lte=month_end).count()
                        elif metric == 'total_enrollments':
                            val = CourseEnrollment.objects.filter(user__in=sg_users, created__gte=month_start, created__lte=month_end).count()
                        
                        month_data[sg.name] = val
                        
                    result.append(month_data)
            else:
                for month in range(1, 13):
                    if month > max_month:
                        result.append({"month": f"T{month}", "value": 0})
                        continue

                    month_start = timezone.make_aware(datetime(year, month, 1))
                    last_day = calendar.monthrange(year, month)[1]
                    month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

                    if metric == 'total_learners':
                        val = User.objects.filter(is_active=True, date_joined__lte=month_end).count()
                    elif metric == 'completion_rate':
                        all_enroll = CourseEnrollment.objects.filter(is_active=True, created__lte=month_end)
                        val = _calc_avg_completion_rate(all_enroll)
                    elif metric == 'active_learners':
                        val = User.objects.filter(is_active=True, last_login__gte=month_start, last_login__lte=month_end).count()
                    elif metric == 'total_enrollments':
                        val = CourseEnrollment.objects.filter(created__gte=month_start, created__lte=month_end).count()
                    else:
                        val = 0

                    result.append({
                        "month": f"T{month}",
                        "value": val
                    })

            return Response({"year": year, "metric": metric, "data": result, "is_grouped": bool(group_id)})
        except Exception as e:
            log.exception("Error generating chart trend")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TopCoursesView(APIView):
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUser]

    def get(self, request):
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 5))
            group_id = request.query_params.get('group_id')

            now = timezone.now()
            month = int(request.query_params.get('month', now.month))
            year  = int(request.query_params.get('year',  now.year))

            import calendar
            from datetime import datetime
            month_start = timezone.make_aware(datetime(year, month, 1))
            last_day    = calendar.monthrange(year, month)[1]
            month_end   = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

            qs = CourseEnrollment.objects.filter(
                created__gte=month_start,
                created__lte=month_end,
            )
            
            if group_id:
                users_qs = User.objects.filter(is_active=True, group_memberships__subgroup__org_group_id=group_id).distinct()
                qs = qs.filter(user__in=users_qs)

            qs = qs.values('course_id').annotate(
                enrollment_count=Count('id')
            ).order_by('-enrollment_count')

            paginator = Paginator(qs, page_size)
            try:
                page_obj = paginator.page(page)
            except (EmptyPage, PageNotAnInteger):
                return Response({"results": [], "count": paginator.count, "total_pages": paginator.num_pages})

            results = []
            for item in page_obj.object_list:
                cid = str(item['course_id'])
                try:
                    course = CourseOverview.objects.get(id=item['course_id'])
                    name = course.display_name
                except Exception:
                    name = cid
                results.append({
                    "course_id": cid,
                    "name": name,
                    "enrollments": item['enrollment_count']
                })

            return Response({
                "count": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": page,
                "results": results
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UncompletedLearnersView(APIView):
    """
    Học viên chưa hoàn thành: có enrollment active tính đến cuối tháng,
    nhưng progress < 100%.
    Tối ưu cho hàng triệu records bằng pre-aggregated JOINs thay vì
    correlated subqueries.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUser]

    def get(self, request):
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 5))
            search = request.query_params.get('search', '').strip()
            group_id = request.query_params.get('group_id')

            now = timezone.now()
            month = int(request.query_params.get('month', now.month))
            year  = int(request.query_params.get('year',  now.year))

            import calendar
            from datetime import datetime
            last_day = calendar.monthrange(year, month)[1]
            month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

            from django.db.models import Max, Q, F, IntegerField as DjIntField
            from django.db.models.functions import Coalesce

            # Base: tất cả enrollment active tính đến cuối tháng
            qs = CourseEnrollment.objects.filter(
                is_active=True,
                created__lte=month_end,
            )
            if group_id:
                users_qs = User.objects.filter(
                    is_active=True,
                    group_memberships__subgroup__org_group_id=group_id
                ).distinct()
                qs = qs.filter(user__in=users_qs)

            # ── Annotate completion counts bằng Subquery ──
            # Subquery 1: số blocks user đã complete cho course này
            user_done_sq = Subquery(
                BlockCompletion.objects.filter(
                    user_id=OuterRef('user_id'),
                    context_key=OuterRef('course_id'),
                    completion__gte=1.0,
                ).order_by().values('user_id', 'context_key').annotate(
                    cnt=Count('block_key', distinct=True)
                ).values('cnt')[:1],
                output_field=DjIntField(),
            )
            # Subquery 2: tổng blocks trong course (từ bất kỳ user nào)
            course_total_sq = Subquery(
                BlockCompletion.objects.filter(
                    context_key=OuterRef('course_id'),
                    completion__gte=1.0,
                ).order_by().values('context_key').annotate(
                    cnt=Count('block_key', distinct=True)
                ).values('cnt')[:1],
                output_field=DjIntField(),
            )

            qs = qs.annotate(
                _user_done=Coalesce(user_done_sq, Value(0)),
                _course_total=Coalesce(course_total_sq, Value(0)),
            )

            # Loại bỏ enrollment đã hoàn thành (user_done >= course_total VÀ course_total > 0)
            qs = qs.exclude(
                _course_total__gt=0,
                _user_done__gte=F('_course_total'),
            )

            # Group by user
            qs = qs.values(
                'user_id', 'user__username', 'user__email'
            ).annotate(
                latest_enrollment=Max('created'),
            ).order_by('-latest_enrollment')

            if search:
                qs = qs.filter(
                    Q(user__username__icontains=search) | Q(user__email__icontains=search)
                )

            status_filter = request.query_params.get('status', 'all')
            from datetime import timedelta
            stalled_threshold = now - timedelta(days=30)
            
            if status_filter in ['stalled', 'learning']:
                recent_users_sq = BlockCompletion.objects.filter(
                    modified__gte=stalled_threshold
                ).values('user_id')
                
                if status_filter == 'stalled':
                    qs = qs.exclude(user_id__in=Subquery(recent_users_sq))
                elif status_filter == 'learning':
                    qs = qs.filter(user_id__in=Subquery(recent_users_sq))

            paginator = Paginator(qs, page_size)
            try:
                page_obj = paginator.page(page)
            except (EmptyPage, PageNotAnInteger):
                return Response({
                    "results": [], "count": paginator.count,
                    "total_pages": paginator.num_pages, "current_page": page
                })

            # ── Tính progress + stalled cho page hiện tại (5-10 items) ──
            stalled_threshold = now - timedelta(days=30)
            results = []

            # Pre-fetch: tất cả enrollment chưa hoàn thành của users trên page
            page_user_ids = [item['user_id'] for item in page_obj.object_list]

            # Batch tính approximate progress bằng BlockCompletion counts (nhẹ, không cần block structure cache)
            # user_done / course_total * 100
            from django.db.models import F as Ff, IntegerField as IntF2
            from django.db.models.functions import Coalesce as Coal2

            page_enrollments = CourseEnrollment.objects.filter(
                user_id__in=page_user_ids,
                is_active=True,
                created__lte=month_end,
            ).annotate(
                _u_done=Coal2(Subquery(
                    BlockCompletion.objects.filter(
                        user_id=OuterRef('user_id'),
                        context_key=OuterRef('course_id'),
                        completion__gte=1.0,
                    ).order_by().values('user_id', 'context_key').annotate(
                        c=Count('block_key', distinct=True)
                    ).values('c')[:1],
                    output_field=IntF2(),
                ), Value(0)),
                _c_total=Coal2(Subquery(
                    BlockCompletion.objects.filter(
                        context_key=OuterRef('course_id'),
                        completion__gte=1.0,
                    ).order_by().values('context_key').annotate(
                        c=Count('block_key', distinct=True)
                    ).values('c')[:1],
                    output_field=IntF2(),
                ), Value(0)),
            ).values('user_id', 'course_id', '_u_done', '_c_total')

            # Build per-user average progress: {user_id: (avg_progress, total_courses, course_list)}
            # Bỏ qua course chưa có block data (course_total = 0)
            user_progress_raw = {}  # {uid: [(prog, course_id), ...]}
            for row in page_enrollments:
                uid_r = row['user_id']
                total = row['_c_total']
                done = row['_u_done']
                if total <= 0:
                    continue  # Bỏ qua course chưa có ai complete block nào
                prog = min(round((done / total) * 100.0, 1), 100.0)
                if uid_r not in user_progress_raw:
                    user_progress_raw[uid_r] = []
                user_progress_raw[uid_r].append((prog, row['course_id']))

            # Tính trung bình + tìm course có progress thấp nhất để hiện tên
            user_progress_map = {}  # {uid: (avg_progress, worst_course_id, n_courses)}
            for uid_r, entries in user_progress_raw.items():
                if not entries:
                    continue
                avg_prog = round(sum(p for p, _ in entries) / len(entries), 1)
                worst_entry = min(entries, key=lambda x: x[0])
                user_progress_map[uid_r] = (avg_prog, worst_entry[1], len(entries))

            # Batch fetch course names (cho course có progress thấp nhất)
            all_course_ids = [v[1] for v in user_progress_map.values()]
            course_name_map = {}
            for co in CourseOverview.objects.filter(id__in=all_course_ids):
                course_name_map[co.id] = co.display_name
            # ── Batch lấy ngày hoàn thành block cuối cùng cho tất cả users trên page ──
            # 1 query duy nhất thay vì N queries .exists() — tối ưu hơn
            from django.db.models import Max as MaxDate
            last_completion_qs = (
                BlockCompletion.objects
                .filter(user_id__in=page_user_ids)
                .values('user_id')
                .annotate(last_done=MaxDate('modified'))
            )
            last_completion_map = {row['user_id']: row['last_done'] for row in last_completion_qs}

            for item in page_obj.object_list:
                uid = item['user_id']
                username = item['user__username']

                progress_info = user_progress_map.get(uid, (0.0, None, 0))
                avg_progress = progress_info[0]
                worst_cid = progress_info[1]
                n_courses = progress_info[2]
                worst_course_name = course_name_map.get(worst_cid, str(worst_cid) if worst_cid else '')
                if n_courses > 1:
                    worst_course_name = f"{worst_course_name} (+{n_courses - 1} khóa khác)"

                # Ngày cuối học viên hoàn thành 1 block bất kỳ
                last_done = last_completion_map.get(uid)
                is_stalled = (last_done is None or last_done < stalled_threshold) and avg_progress < 100.0

                results.append({
                    "username": username,
                    "email": item['user__email'],
                    "last_completion_at": last_done.isoformat() if last_done else None,
                    "progress": avg_progress,
                    "course_name": worst_course_name,
                    "is_stalled": is_stalled,
                })

            return Response({
                "count": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": page,
                "results": results
            })
        except Exception as e:
            log.exception("Error in UncompletedLearnersView")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def calculate_actual_progress(user, course_key):
    """
    Tính toán tiến độ thực tế đồng bộ 100% với logic frontend (FE-5173).
    Tính % tổng số module (chapter) đã hoàn thành.
    Module hoàn thành khi tất cả các sequential (lesson) bên trong đều có avg leaf completion >= 1.0.
    """
    try:
        block_structure = get_course_in_cache(course_key)
        
        # Lấy toàn bộ completion records của user
        raw_completions = BlockCompletion.objects.filter(
            user=user,
            context_key=course_key,
        ).values_list('block_key', 'completion')
        
        completions_dict = {}
        for b_key, comp in raw_completions:
            try:
                mapped_key = b_key.map_into_course(course_key)
                completions_dict[mapped_key] = comp
            except Exception:
                completions_dict[b_key] = comp

        chapters = block_structure.get_children(block_structure.root_block_usage_key)
        total_modules = 0
        total_modules_progress = 0

        for chapter_key in chapters:
            if block_structure.get_xblock_field(chapter_key, 'category') != 'chapter':
                continue
            
            sequentials = block_structure.get_children(chapter_key)
            seq_list = [s for s in sequentials if block_structure.get_xblock_field(s, 'category') == 'sequential']
            
            if not seq_list:
                continue
                
            total_modules += 1
            completed_seqs = 0
            
            for seq_key in seq_list:
                leaf_blocks = []
                def collect_leaves(bk):
                    children = block_structure.get_children(bk)
                    if not children:
                        leaf_blocks.append(bk)
                    else:
                        for child in children:
                            collect_leaves(child)
                
                collect_leaves(seq_key)
                
                leaf_completions = [completions_dict.get(leaf, 0.0) for leaf in leaf_blocks]
                if leaf_completions:
                    avg_completion = sum(leaf_completions) / len(leaf_completions)
                    if avg_completion >= 1.0:
                        completed_seqs += 1
                        
            module_progress = (completed_seqs / len(seq_list)) * 100
            total_modules_progress += module_progress
            
        if total_modules > 0:
            return min(round(total_modules_progress / total_modules, 1), 100.0)

    except BlockStructureNotFound:
        log.warning("LearnerDetail BlockStructureNotFound for course=%s", course_key)
    except Exception as exc:
        log.warning("calculate_actual_progress error: user=%s course=%s error=%s", user.username, course_key, exc)

    return 0.0

class LearnerDetailView(APIView):
    """
    API chi tiết học viên dành cho Superuser drill-down.
    Trả về danh sách khóa học, ngày enroll và tiến độ học tập thực tế.
    Có hỗ trợ phân trang và tìm kiếm.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUser]
    parser_classes = [JSONParser]

    def _get_actual_progress(self, user, course_key):
        return calculate_actual_progress(user, course_key)

    def get(self, request):
        username = request.query_params.get('username')
        if not username:
            return Response({"error": "Username is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        search = request.query_params.get('search', '')
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Lấy danh sách enrollments
        enrollments_qs = CourseEnrollment.objects.filter(user=user, is_active=True).order_by('-created')
        
        # Search filter — áp dụng TRƯỚC pagination
        if search:
            # Lấy course_ids khớp search từ CourseOverview
            matching_courses = CourseOverview.objects.filter(
                display_name__icontains=search
            ).values_list('id', flat=True)
            enrollments_qs = enrollments_qs.filter(course_id__in=matching_courses)
        
        # Pagination TRƯỚC khi tính progress — chỉ tính cho page hiện tại
        paginator = Paginator(enrollments_qs, page_size)
        try:
            page_obj = paginator.page(page)
        except (EmptyPage, PageNotAnInteger):
            return Response({
                "username": username,
                "results": [],
                "total_count": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": page
            })
        
        # Batch-fetch CourseOverview cho page hiện tại
        page_course_ids = [en.course_id for en in page_obj.object_list]
        course_names = {}
        for co in CourseOverview.objects.filter(id__in=page_course_ids):
            course_names[co.id] = co.display_name
        
        # Tính progress chỉ cho enrollments trong page
        results = []
        for en in page_obj.object_list:
            course_name = course_names.get(en.course_id, str(en.course_id))
            progress = self._get_actual_progress(user, en.course_id)
            
            results.append({
                "course_id": str(en.course_id),
                "course_name": course_name,
                "enrolled_at": en.created.isoformat() if en.created else None,
                "progress": round(progress, 1),
                "is_completed": progress >= 100.0
            })

        return Response({
            "username": username,
            "results": results,
            "total_count": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page_obj.number
        })

class MyCourseProgressView(APIView):
    """
    API hiệu năng cao trả về tiến độ học tập (%) của học viên đang đăng nhập.
    Giúp FE-5173 không phải tải toàn bộ cấu trúc khoá học.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({"error": "Thiếu tham số course_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from opaque_keys.edx.keys import CourseKey
            from opaque_keys import InvalidKeyError
            course_key = CourseKey.from_string(course_id)
            
            # Đảm bảo user đã enroll khoá này
            if not CourseEnrollment.objects.filter(user=request.user, course_id=course_key, is_active=True).exists():
                return Response({"progress": 0.0, "is_completed": False}, status=status.HTTP_200_OK)

            progress = calculate_actual_progress(request.user, course_key)
            return Response({
                "course_id": course_id,
                "progress": progress,
                "is_completed": progress >= 100.0
            }, status=status.HTTP_200_OK)

        except Exception as e:
            from opaque_keys import InvalidKeyError
            if isinstance(e, InvalidKeyError):
                return Response({"error": "ID khoá học không hợp lệ"}, status=status.HTTP_400_BAD_REQUEST)
            log.error(f"MyCourseProgressView Error: {e}")
            return Response({"error": "Lỗi nội bộ hệ thống"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
