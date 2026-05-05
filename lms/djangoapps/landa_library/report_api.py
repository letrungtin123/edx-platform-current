from django.contrib.auth.models import User
from django.db.models import Count, Avg, FloatField, OuterRef, Exists
from django.db.models.functions import Cast
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

            # ── 1. User Metrics ──────────────────────────────────────────
            total_learners = User.objects.filter(is_active=True, date_joined__lte=month_end).count()
            total_staff    = User.objects.filter(is_active=True, is_staff=True, date_joined__lte=month_end).count()

            # Học viên hoạt động: login trong tháng được chọn
            active_learners = User.objects.filter(
                last_login__gte=month_start,
                last_login__lte=month_end,
            ).count()

            # ── 2. Course Metrics ─────────────────────────────────────────
            total_courses = CourseOverview.objects.filter(created__lte=month_end).count()

            # ── 7. Trend — 4 tuần trong tháng được chọn ─────────────────
            uncompleted_trend = []
            week_size = max(last_day // 4, 1)
            for week_idx in range(4):
                week_start_day = week_idx * week_size + 1
                week_end_day   = (week_start_day + week_size - 1) if week_idx < 3 else last_day
                w_start = timezone.make_aware(datetime(year, month, week_start_day))
                w_end   = timezone.make_aware(datetime(year, month, min(week_end_day, last_day), 23, 59, 59))

                count = CourseEnrollment.objects.filter(
                    is_active=True,
                    created__gte=w_start,
                    created__lte=w_end,
                ).exclude(
                    Exists(
                        PersistentCourseGrade.objects.filter(
                            user_id=OuterRef('user_id'),
                            course_id=OuterRef('course_id'),
                            passed_timestamp__isnull=False
                        )
                    )
                ).count()

                uncompleted_trend.append({
                    "day": f"T{week_start_day}/{month}",
                    "count": count
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
                    "total_staff": total_staff,
                    "active_learners": active_learners,
                    "total_courses": total_courses
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
            year = int(request.query_params.get('year', timezone.now().year))
            metric = request.query_params.get('metric', 'total_learners')

            import calendar
            from datetime import datetime

            result = []
            for month in range(1, 13):
                month_start = timezone.make_aware(datetime(year, month, 1))
                last_day = calendar.monthrange(year, month)[1]
                month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

                if metric == 'total_learners':
                    val = User.objects.filter(is_active=True, date_joined__lte=month_end).count()
                elif metric == 'total_staff':
                    val = User.objects.filter(is_active=True, is_staff=True, date_joined__lte=month_end).count()
                elif metric == 'active_learners':
                    val = User.objects.filter(last_login__gte=month_start, last_login__lte=month_end).count()
                elif metric == 'total_courses':
                    val = CourseOverview.objects.filter(created__lte=month_end).count()
                else:
                    val = 0

                result.append({
                    "month": f"T{month}",
                    "value": val
                })

            return Response({"year": year, "metric": metric, "data": result})
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
            ).values('course_id').annotate(
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

            now = timezone.now()
            month = int(request.query_params.get('month', now.month))
            year  = int(request.query_params.get('year',  now.year))

            import calendar
            from datetime import datetime
            month_start = timezone.make_aware(datetime(year, month, 1))
            last_day    = calendar.monthrange(year, month)[1]
            month_end   = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

            from django.db.models import Max
            qs = CourseEnrollment.objects.filter(
                is_active=True,
                created__gte=month_start,
                created__lte=month_end,
            ).exclude(
                Exists(
                    PersistentCourseGrade.objects.filter(
                        user_id=OuterRef('user_id'),
                        course_id=OuterRef('course_id'),
                        passed_timestamp__isnull=False
                    )
                )
            ).values('user__username', 'user__email').annotate(
                latest_enrollment=Max('created')
            ).order_by('-latest_enrollment')

            if search:
                qs = qs.filter(user__username__icontains=search) | qs.filter(user__email__icontains=search)

            paginator = Paginator(qs, page_size)
            try:
                page_obj = paginator.page(page)
            except (EmptyPage, PageNotAnInteger):
                return Response({"results": [], "count": paginator.count, "total_pages": paginator.num_pages})

            results = []
            for item in page_obj.object_list:
                results.append({
                    "username": item['user__username'],
                    "email": item['user__email'],
                    "enrolled_at": item['latest_enrollment'].isoformat() if item['latest_enrollment'] else None
                })

            return Response({
                "count": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": page,
                "results": results
            })
        except Exception as e:
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
        
        results_all = []
        for en in enrollments_qs:
            try:
                course = CourseOverview.objects.get(id=en.course_id)
                course_name = course.display_name
            except Exception:
                course_name = str(en.course_id)
            
            if search and search.lower() not in course_name.lower() and search.lower() not in str(en.course_id).lower():
                continue

            progress = self._get_actual_progress(user, en.course_id)
            
            results_all.append({
                "course_id": str(en.course_id),
                "course_name": course_name,
                "enrolled_at": en.created.isoformat() if en.created else None,
                "progress": round(progress, 1),
                "is_completed": PersistentCourseGrade.objects.filter(user_id=user.id, course_id=en.course_id, passed_timestamp__isnull=False).exists()
            })

        # Pagination
        paginator = Paginator(results_all, page_size)
        try:
            paged_data = paginator.page(page)
        except PageNotAnInteger:
            paged_data = paginator.page(1)
        except EmptyPage:
            paged_data = paginator.page(paginator.num_pages)

        return Response({
            "username": username,
            "results": list(paged_data),
            "total_count": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": paged_data.number
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
