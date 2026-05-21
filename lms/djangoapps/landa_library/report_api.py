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


class IsSuperUserOrLearnerPlus(permissions.BasePermission):
    """
    Cho phép superuser HOẶC user có custom role learner_plus.
    Dùng cho report views.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        # Check custom role
        try:
            from lms.djangoapps.landa_groups.models import LandaUserRole
            return LandaUserRole.objects.filter(
                user=request.user, role='learner_plus'
            ).exists()
        except Exception:
            return False


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
    permission_classes = [IsSuperUserOrLearnerPlus]
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

            # learner_plus: bắt buộc phải có group_id + validate quyền xem group đó
            # staff/superuser được phép xem tất cả
            if not request.user.is_superuser and not request.user.is_staff:
                if not group_id:
                    return Response(
                        {"error": "Bạn chỉ được phép xem báo cáo của nhóm mình."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                from lms.djangoapps.landa_groups.models import SubGroupMembership
                user_group_ids = list(
                    SubGroupMembership.objects.filter(
                        user=request.user,
                    ).values_list('subgroup__org_group_id', flat=True).distinct()
                )
                if int(group_id) not in user_group_ids:
                    return Response(
                        {"error": "Bạn không có quyền xem báo cáo của nhóm này."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

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

            # ── 7. Trend (Removed) ─────────────────
            # Tính toán uncompleted_trend đã được loại bỏ để tối ưu query DB
            # do frontend không còn sử dụng biểu đồ này nữa.
            uncompleted_trend = []

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
    permission_classes = [IsSuperUserOrLearnerPlus]
    parser_classes = [JSONParser]

    def get(self, request):
        try:
            now = timezone.now()
            year = int(request.query_params.get('year', now.year))
            metric = request.query_params.get('metric', 'total_learners')
            group_id = request.query_params.get('group_id')
            group_by_org = request.query_params.get('group_by_org') == 'true'

            import calendar
            from datetime import datetime
            from lms.djangoapps.landa_groups.models import SubGroup, OrgGroup

            # Giới hạn tháng: nếu năm hiện tại thì chỉ tới tháng hiện tại
            if year > now.year:
                max_month = 0
            elif year == now.year:
                max_month = now.month
            else:
                max_month = 12

            result = []
            
            if group_by_org:
                if group_id:
                    org_groups = OrgGroup.objects.filter(id=group_id)
                else:
                    org_groups = OrgGroup.objects.all()

                for month in range(1, 13):
                    month_data = {"month": f"T{month}"}
                    
                    if month > max_month:
                        for og in org_groups:
                            month_data[og.name] = 0
                        result.append(month_data)
                        continue

                    month_start = timezone.make_aware(datetime(year, month, 1))
                    last_day = calendar.monthrange(year, month)[1]
                    month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))
                    
                    for og in org_groups:
                        og_users = User.objects.filter(group_memberships__subgroup__org_group=og, is_active=True).distinct()
                        val = 0
                        if metric == 'total_learners':
                            val = og_users.filter(date_joined__lte=month_end).count()
                        elif metric == 'completion_rate':
                            sg_enroll = CourseEnrollment.objects.filter(is_active=True, user__in=og_users, created__lte=month_end)
                            val = _calc_avg_completion_rate(sg_enroll)
                        elif metric == 'active_learners':
                            val = og_users.filter(last_login__gte=month_start, last_login__lte=month_end).count()
                        elif metric == 'total_enrollments':
                            val = CourseEnrollment.objects.filter(user__in=og_users, created__gte=month_start, created__lte=month_end).count()
                        
                        month_data[og.name] = val
                        
                    result.append(month_data)
                    
                return Response({"year": year, "metric": metric, "data": result, "is_grouped": True})
            
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
    permission_classes = [IsSuperUserOrLearnerPlus]

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


def _get_group_course_ids(group_id):
    """
    Lấy tất cả course_id thuộc 1 OrgGroup qua:
    SubGroupCourseCategoryAssignment → CourseCategoryMembership
    (course thuộc danh mục khóa học được gán cho subgroup)
    Trả về set(str) để dùng cho filter __in.
    """
    from lms.djangoapps.landa_groups.models import SubGroupCourseCategoryAssignment
    from lms.djangoapps.landa_library.models import CourseCategoryMembership

    cat_ids = SubGroupCourseCategoryAssignment.objects.filter(
        subgroup__org_group_id=group_id,
    ).values_list('category_id', flat=True)

    return set(
        CourseCategoryMembership.objects.filter(
            category_id__in=cat_ids,
        ).values_list('course_id', flat=True)
    )


class UncompletedLearnersView(APIView):
    """
    Danh sách TẤT CẢ học viên trong hệ thống (hoặc theo group).
    Base query khớp 100% với total_learners trong ReportSummaryView.
    Mỗi user có 1 trong 3 trạng thái:
      - not_started: tiến độ tổng = 0% (chưa complete block nào)
      - learning:    0% < tiến độ tổng < 100%
      - completed:   tiến độ tổng = 100% (tất cả course đều hoàn thành)
    Tối ưu cho hàng triệu records: filter status tại DB level,
    tính progress chỉ cho page hiện tại (5-10 items).
    Khi có group_id: chỉ tính progress cho courses được gán cho group.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUserOrLearnerPlus]

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

            from django.db.models import Q, F, IntegerField as DjIntField
            from django.db.models.functions import Coalesce

            # ── Base query: KHỚP 100% với total_learners của ReportSummaryView ──
            users_qs = User.objects.filter(is_active=True, date_joined__lte=month_end)
            if group_id:
                users_qs = users_qs.filter(
                    group_memberships__subgroup__org_group_id=group_id
                ).distinct()

            # ── Lấy danh sách courses thuộc group (nếu có) ──
            group_course_ids = None
            if group_id:
                group_course_ids = _get_group_course_ids(group_id)

            # Search filter
            if search:
                users_qs = users_qs.filter(
                    Q(username__icontains=search) | Q(email__icontains=search)
                )

            # ── Status filter tại DB level ──
            status_filter = request.query_params.get('status', 'all')

            # Build enrollment base filter (chỉ courses thuộc group nếu có)
            enrollment_filter = Q(
                user_id=OuterRef('id'),
                is_active=True,
                created__lte=month_end,
            )
            if group_course_ids is not None:
                enrollment_filter &= Q(course_id__in=group_course_ids)

            # Build completion base filter (chỉ courses thuộc group nếu có)
            completion_filter = Q(
                user_id=OuterRef('id'),
                completion__gte=1.0,
            )
            if group_course_ids is not None:
                completion_filter &= Q(context_key__in=group_course_ids)

            # Subquery: user có ít nhất 1 BlockCompletion trong group courses
            has_any_completion = Exists(
                BlockCompletion.objects.filter(completion_filter)
            )

            # Subquery: user có ít nhất 1 enrollment active trong group courses
            has_enrollment = Exists(
                CourseEnrollment.objects.filter(enrollment_filter)
            )

            # Subquery cho incomplete enrollment:
            # Enrollment mà user_done < course_total HOẶC course_total = 0
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

            incomplete_enrollment_base = CourseEnrollment.objects.filter(
                user_id=OuterRef('id'),
                is_active=True,
                created__lte=month_end,
            )
            if group_course_ids is not None:
                incomplete_enrollment_base = incomplete_enrollment_base.filter(
                    course_id__in=group_course_ids,
                )
            has_incomplete_enrollment = Exists(
                incomplete_enrollment_base.annotate(
                    _user_done=Coalesce(user_done_sq, Value(0)),
                    _course_total=Coalesce(course_total_sq, Value(0)),
                ).filter(
                    Q(_course_total=0) | Q(_user_done__lt=F('_course_total'))
                )
            )

            if status_filter == 'not_started':
                # Chưa học: không có completion nào (trong group courses)
                users_qs = users_qs.annotate(
                    _has_completion=has_any_completion,
                ).filter(_has_completion=False)
            elif status_filter == 'completed':
                # Đã học: có enrollment + KHÔNG có enrollment nào incomplete
                users_qs = users_qs.annotate(
                    _has_enrollment=has_enrollment,
                    _has_incomplete=has_incomplete_enrollment,
                ).filter(_has_enrollment=True, _has_incomplete=False)
            elif status_filter == 'learning':
                # Đang học: có completion + có ít nhất 1 enrollment incomplete
                users_qs = users_qs.annotate(
                    _has_completion=has_any_completion,
                    _has_incomplete=has_incomplete_enrollment,
                ).filter(_has_completion=True, _has_incomplete=True)

            # Order by: mới nhất trước
            users_qs = users_qs.order_by('-date_joined')

            paginator = Paginator(users_qs, page_size)
            try:
                page_obj = paginator.page(page)
            except (EmptyPage, PageNotAnInteger):
                return Response({
                    "results": [], "count": paginator.count,
                    "total_pages": paginator.num_pages, "current_page": page
                })

            # ── Tính progress cho page hiện tại (5-10 items) ──
            page_user_ids = [u.id for u in page_obj.object_list]

            if not page_user_ids:
                return Response({
                    "count": paginator.count,
                    "total_pages": paginator.num_pages,
                    "current_page": page,
                    "results": []
                })

            # Batch query: lấy danh sách enrollments cho users trên page
            # CHỈ courses thuộc group (nếu có group_id)
            page_enrollments_qs = CourseEnrollment.objects.filter(
                user_id__in=page_user_ids,
                is_active=True,
                created__lte=month_end,
            )
            if group_course_ids is not None:
                page_enrollments_qs = page_enrollments_qs.filter(
                    course_id__in=group_course_ids,
                )

            page_enrollments = page_enrollments_qs.values('user_id', 'course_id')

            # Pre-fetch user objects cho calculate_actual_progress
            page_users_by_id = {u.id: u for u in page_obj.object_list}

            # Build per-user progress dùng calculate_actual_progress (chính xác 100%)
            user_progress_raw = {}  # {uid: [(prog, course_id), ...]}
            user_enrolled_count = {}  # {uid: total enrolled courses}
            for row in page_enrollments:
                uid_r = row['user_id']
                user_enrolled_count[uid_r] = user_enrolled_count.get(uid_r, 0) + 1
                user_obj_r = page_users_by_id.get(uid_r)
                if not user_obj_r:
                    continue
                try:
                    from opaque_keys.edx.keys import CourseKey as CKey
                    ckey = CKey.from_string(str(row['course_id']))
                    prog = calculate_actual_progress(user_obj_r, ckey)
                except Exception:
                    prog = 0.0
                if uid_r not in user_progress_raw:
                    user_progress_raw[uid_r] = []
                user_progress_raw[uid_r].append((prog, row['course_id']))

            # Tính trung bình + tìm course có progress thấp nhất
            user_progress_map = {}  # {uid: (avg_progress, worst_course_id, n_courses)}
            for uid_r, entries in user_progress_raw.items():
                if not entries:
                    continue
                avg_prog = round(sum(p for p, _ in entries) / len(entries), 1)
                worst_entry = min(entries, key=lambda x: x[0])
                user_progress_map[uid_r] = (avg_prog, worst_entry[1], len(entries))

            # Batch fetch course names
            all_course_ids = [v[1] for v in user_progress_map.values()]
            course_name_map = {}
            for co in CourseOverview.objects.filter(id__in=all_course_ids):
                course_name_map[co.id] = co.display_name

            # Batch lấy ngày hoàn thành block cuối cùng (trong group courses nếu có)
            from django.db.models import Max as MaxDate
            last_completion_base = BlockCompletion.objects.filter(user_id__in=page_user_ids)
            if group_course_ids is not None:
                last_completion_base = last_completion_base.filter(
                    context_key__in=group_course_ids,
                )
            last_completion_qs = (
                last_completion_base
                .values('user_id')
                .annotate(last_done=MaxDate('modified'))
            )
            last_completion_map = {row['user_id']: row['last_done'] for row in last_completion_qs}

            # Batch fetch avatar URLs (chỉ user có ảnh đã upload)
            from common.djangoapps.student.models import UserProfile
            from openedx.core.djangoapps.user_api.accounts.image_helpers import get_profile_image_urls_for_user
            profile_has_image = set(
                UserProfile.objects.filter(
                    user_id__in=page_user_ids,
                    profile_image_uploaded_at__isnull=False,
                ).values_list('user_id', flat=True)
            )
            avatar_map = {}
            for user_obj_av in page_obj.object_list:
                if user_obj_av.id in profile_has_image:
                    try:
                        urls = get_profile_image_urls_for_user(user_obj_av, request)
                        avatar_map[user_obj_av.id] = urls.get('small', '')
                    except Exception:
                        avatar_map[user_obj_av.id] = ''
                else:
                    avatar_map[user_obj_av.id] = ''

            results = []
            for user_obj in page_obj.object_list:
                uid = user_obj.id
                username = user_obj.username

                progress_info = user_progress_map.get(uid, (0.0, None, 0))
                avg_progress = progress_info[0]
                worst_cid = progress_info[1]
                n_courses = progress_info[2]
                enrolled = user_enrolled_count.get(uid, 0)

                worst_course_name = course_name_map.get(worst_cid, str(worst_cid) if worst_cid else '')
                if n_courses > 1:
                    worst_course_name = f"{worst_course_name} (+{n_courses - 1} khóa khác)"

                last_done = last_completion_map.get(uid)

                # Xác định status từ progress
                if avg_progress >= 100.0 and enrolled > 0 and n_courses > 0:
                    user_status = 'completed'
                elif avg_progress > 0:
                    user_status = 'learning'
                else:
                    user_status = 'not_started'

                results.append({
                    "username": username,
                    "email": user_obj.email,
                    "avatar": avatar_map.get(uid, ''),
                    "last_completion_at": last_done.isoformat() if last_done else None,
                    "progress": avg_progress,
                    "course_name": worst_course_name,
                    "status": user_status,
                    "enrolled_courses": enrolled,
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
    permission_classes = [IsSuperUserOrLearnerPlus]
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

        # Lấy thông tin group/subgroup
        user_groups = []
        for membership in user.group_memberships.select_related('subgroup', 'subgroup__org_group').all():
            user_groups.append({
                "group_name": membership.subgroup.org_group.name,
                "subgroup_name": membership.subgroup.name
            })

        return Response({
            "username": username,
            "groups": user_groups,
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


class AdminUserBadgesView(APIView):
    """
    GET /api/landa/admin/user-badges/?username=...

    Admin xem danh sách badges đã đạt của 1 user cụ thể.
    Dùng trong LearnerDetailModal trên frontend-shell.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUserOrLearnerPlus]

    def get(self, request):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        from lms.djangoapps.landa_library.models import UserBadge
        badges = UserBadge.objects.filter(user=user).order_by('-earned_at')
        data = [
            {
                'badge_id': b.badge_id,
                'earned_at': b.earned_at.isoformat(),
            }
            for b in badges
        ]
        return Response({'username': username, 'badges': data})


class AdminUserStudyTimeView(APIView):
    """
    GET /api/landa/admin/user-study-time/?username=...

    Admin xem study time tuần hiện tại của 1 user cụ thể.
    Dùng trong LearnerDetailModal trên frontend-shell.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [IsSuperUserOrLearnerPlus]

    def get(self, request):
        username = request.query_params.get('username')
        if not username:
            return Response({'error': 'username is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        from datetime import date, timedelta
        from lms.djangoapps.landa_library.models import StudyTimeDaily

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

        rows = StudyTimeDaily.objects.filter(
            user=user,
            date__gte=monday,
            date__lte=sunday,
        ).values('date', 'minutes')

        data_map = {r['date']: r['minutes'] for r in rows}

        entries = []
        for i in range(7):
            d = monday + timedelta(days=i)
            entries.append({
                'date': d.isoformat(),
                'minutes': data_map.get(d, 0),
            })

        return Response({'username': username, 'entries': entries})

