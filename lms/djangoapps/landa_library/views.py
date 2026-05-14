"""
views.py — LANDA Library API Views

GET /api/landa/v1/library/documents/
    → Danh sách tài liệu visible, phân trang + filter + search

GET /api/landa/v1/library/categories/
    → Danh sách category + số file visible

GET /api/landa/v1/library/download/<id>/
    → Download file (protected — yêu cầu đăng nhập)

POST /api/landa/v1/account/send-welcome-email/
    → Gửi email chào mừng chứa thông tin tài khoản cho user mới đăng ký qua Google

Auth: JWT hoặc Session — user phải đăng nhập (trừ send-welcome-email).
"""

import logging
import os
import secrets
import string
from datetime import datetime

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import (
    SessionAuthenticationAllowInactiveUser,
)
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument, CourseModalConfig, UserBadge
from lms.djangoapps.landa_library.serializers import (
    DocumentCategorySerializer,
    LibraryDocumentSerializer,
)

log = logging.getLogger(__name__)

# Giới hạn page_size tối đa để tránh abuse
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20


class LibraryPagination(PageNumberPagination):
    """Phân trang cho Library API"""
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = 'page_size'
    max_page_size = MAX_PAGE_SIZE


class DocumentListView(ListAPIView):
    """
    GET /api/landa/v1/library/documents/

    Query params:
        page        — Trang (default: 1)
        page_size   — Items/trang (default: 20, max: 50)
        category    — Filter theo category slug
        extension   — Filter theo đuôi file (pdf/docx/xlsx/pptx)
        search      — Tìm theo title
        ordering    — Sắp xếp (-created_at | created_at | title | -title)

    Response:
        {
          "count": 45,
          "next": "...?page=2",
          "previous": null,
          "results": [...]
        }
    """
    serializer_class = LibraryDocumentSerializer
    pagination_class = LibraryPagination
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    # Cho phép sắp xếp theo các field sau
    ALLOWED_ORDERING = frozenset([
        'created_at', '-created_at',
        'title', '-title',
        'sort_order', '-sort_order',
    ])

    def get_queryset(self):
        """
        Base queryset: chỉ file visible + select_related category.
        Apply filter + search từ query params.
        """
        user = self.request.user
        qs = (
            LibraryDocument.objects
            .filter(is_visible=True)
            .select_related('category', 'uploaded_by')
        )

        if not user.is_staff and not user.is_superuser:
            from lms.djangoapps.landa_groups.models import SubGroupCategoryAssignment
            allowed_category_ids = SubGroupCategoryAssignment.objects.filter(
                subgroup__memberships__user=user
            ).values_list('category_id', flat=True)
            qs = qs.filter(category_id__in=allowed_category_ids)

        # ── Filter theo category slug ──
        category_slug = self.request.query_params.get('category')
        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        # ── Filter theo extension ──
        extension = self.request.query_params.get('extension')
        if extension:
            qs = qs.filter(extension=extension.lower())

        # ── Search theo title ──
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(title__icontains=search)

        # ── Ordering ──
        ordering = self.request.query_params.get('ordering', '-created_at')
        if ordering not in self.ALLOWED_ORDERING:
            ordering = '-created_at'
        qs = qs.order_by(ordering)

        return qs


class CategorySummaryView(APIView):
    """
    GET /api/landa/v1/library/categories/

    Trả danh sách category + số file visible trong mỗi category.

    Response:
        {
          "categories": [
            {"id": 1, "name": "Nhân sự", "slug": "nhan-su", "count": 12},
            ...
          ],
          "total": 28
        }
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        # Annotate count file visible cho mỗi category
        categories = (
            DocumentCategory.objects
            .annotate(
                count=Count(
                    'documents',
                    filter=Q(documents__is_visible=True)
                )
            )
            .filter(count__gt=0)  # Ẩn category rỗng
            .order_by('sort_order', 'name')
        )

        if not user.is_staff and not user.is_superuser:
            from lms.djangoapps.landa_groups.models import SubGroupCategoryAssignment
            allowed_category_ids = SubGroupCategoryAssignment.objects.filter(
                subgroup__memberships__user=user
            ).values_list('category_id', flat=True)
            categories = categories.filter(id__in=allowed_category_ids)

        serializer = DocumentCategorySerializer(categories, many=True)

        # Tổng số file visible (tất cả category)
        if not user.is_staff and not user.is_superuser:
            total = LibraryDocument.objects.filter(is_visible=True, category_id__in=allowed_category_ids).count()
        else:
            total = LibraryDocument.objects.filter(is_visible=True).count()

        return Response({
            'categories': serializer.data,
            'total': total,
        })


@api_view(['GET'])
@authentication_classes([
    JwtAuthentication,
    BearerAuthenticationAllowInactiveUser,
    SessionAuthenticationAllowInactiveUser,
])
@permission_classes([permissions.IsAuthenticated])
def document_download(request, doc_id):
    """
    GET /api/landa/v1/library/download/<id>/

    Protected download — kiểm tra auth + is_visible trước khi trả file.
    Trả FileResponse (streaming) — không load toàn bộ file vào RAM.
    """
    try:
        doc = LibraryDocument.objects.select_related('category').get(id=doc_id, is_visible=True)
    except LibraryDocument.DoesNotExist:
        raise Http404("Document not found")

    user = request.user
    if not user.is_staff and not user.is_superuser:
        from lms.djangoapps.landa_groups.models import SubGroupCategoryAssignment
        has_access = SubGroupCategoryAssignment.objects.filter(
            category=doc.category,
            subgroup__memberships__user=user
        ).exists()
        if not has_access:
            raise Http404("Document not found")

    if not doc.file:
        raise Http404("File not found")

    filename = os.path.basename(doc.file.name)
    response = FileResponse(
        doc.file.open('rb'),
        as_attachment=True,
        filename=filename,
    )
    return response


# ── Password Change API ──

@api_view(['POST'])
@authentication_classes([
    JwtAuthentication,
    BearerAuthenticationAllowInactiveUser,
    SessionAuthenticationAllowInactiveUser,
])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    """
    POST /api/landa/v1/account/change-password/

    Đổi mật khẩu trực tiếp cho user đã login.
    Không cần email — verify mật khẩu cũ → set mật khẩu mới.

    Request body (JSON):
        {
            "current_password": "old_password",
            "new_password": "new_secure_password"
        }

    Responses:
        200: Đổi mật khẩu thành công
        400: Thiếu field hoặc mật khẩu mới không hợp lệ
        403: Mật khẩu hiện tại không đúng
    """
    current_password = request.data.get('current_password', '').strip()
    new_password = request.data.get('new_password', '').strip()

    if not current_password or not new_password:
        return Response(
            {'success': False, 'message': 'Vui lòng nhập đầy đủ mật khẩu hiện tại và mật khẩu mới.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify mật khẩu hiện tại
    user = authenticate(
        username=request.user.username,
        password=current_password,
        request=request,
    )
    if user is None:
        return Response(
            {'success': False, 'message': 'Mật khẩu hiện tại không đúng.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Validate mật khẩu mới theo policy Open edX
    try:
        from openedx.core.djangoapps.user_api.accounts.api import get_password_validation_error
        validation_error = get_password_validation_error(
            new_password,
            username=user.username,
            email=user.email,
        )
        if validation_error:
            return Response(
                {'success': False, 'message': str(validation_error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except ImportError:
        # Fallback: kiểm tra độ dài tối thiểu nếu không import được
        if len(new_password) < 8:
            return Response(
                {'success': False, 'message': 'Mật khẩu mới phải có ít nhất 8 ký tự.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if current_password == new_password:
        return Response(
            {'success': False, 'message': 'Mật khẩu mới phải khác mật khẩu hiện tại.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Set mật khẩu mới
    user.set_password(new_password)
    user.save()

    log.info("User %s changed password successfully via LANDA API.", user.username)

    return Response({
        'success': True,
        'message': 'Đổi mật khẩu thành công.',
    })


class AccountStatusView(APIView):
    """
    GET /api/landa/v1/account/status/

    API siêu nhẹ để FE polling kiểm tra trạng thái tài khoản.
    Không query database — chỉ đọc Redis blacklist (< 1ms).
    Trả về: { "is_active": true/false }

    Nếu user đã bị blacklist bởi middleware → request này sẽ
    nhận 401 trước cả khi chạm tới view này. FE interceptor
    tự động logout khi nhận 401.

    View này serve trường hợp FE muốn check proactively
    (trước khi 401 xảy ra trên request chính).
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from lms.djangoapps.landa_library.blacklist import is_user_blacklisted
        blacklisted = is_user_blacklisted(request.user.id)
        return Response({'is_active': not blacklisted})


class CourseModalConfigPublicView(APIView):
    """
    GET /api/landa/v1/course-modal-config/?course_id=xxx

    Learner (authenticated) đọc cấu hình modal cho course đang học.
    Trả về chỉ những field cần thiết + fallback defaults.
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get('course_id', '')
        if not course_id:
            return Response({'error': 'course_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cfg = CourseModalConfig.objects.get(course_id=course_id)
            return Response({
                'welcome_enabled': cfg.welcome_enabled,
                'welcome_title': cfg.welcome_title or '',
                'welcome_description': cfg.welcome_description or '',
                'confirm_enabled': cfg.confirm_enabled,
                'confirm_title': cfg.confirm_title or '',
                'confirm_description': cfg.confirm_description or '',
                'confirm_checkbox_text': cfg.confirm_checkbox_text or '',
                'completion_enabled': cfg.completion_enabled,
                'completion_title': cfg.completion_title or '',
                'completion_description': cfg.completion_description or '',
                'completion_social_type': cfg.completion_social_type or '',
                'completion_social_link': cfg.completion_social_link or '',
            })
        except CourseModalConfig.DoesNotExist:
            return Response({
                'welcome_enabled': True,
                'welcome_title': '',
                'welcome_description': '',
                'confirm_enabled': True,
                'confirm_title': '',
                'confirm_description': '',
                'confirm_checkbox_text': '',
                'completion_enabled': True,
                'completion_title': '',
                'completion_description': '',
                'completion_social_type': '',
                'completion_social_link': '',
            })


class UserBadgeView(APIView):
    """
    GET /api/landa/v1/user-badges/
        Trả về danh sách danh hiệu của user hiện tại.
    POST /api/landa/v1/user-badges/
        Lưu danh hiệu mới (FE gọi khi pass điều kiện).
    PATCH /api/landa/v1/user-badges/
        Update trạng thái is_shown (FE gọi khi tắt modal chúc mừng).
    """
    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        badges = UserBadge.objects.filter(user=request.user)
        data = [
            {
                "badge_id": b.badge_id,
                "is_shown": b.is_shown,
                "earned_at": b.earned_at.isoformat()
            } for b in badges
        ]
        return Response(data)

    def post(self, request):
        badge_id = request.data.get("badge_id")
        if not badge_id:
            return Response({"error": "badge_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        badge, created = UserBadge.objects.get_or_create(
            user=request.user,
            badge_id=badge_id
        )
        return Response({
            "success": True,
            "badge_id": badge.badge_id,
            "is_shown": badge.is_shown,
            "earned_at": badge.earned_at.isoformat(),
            "created": created
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def patch(self, request):
        badge_id = request.data.get("badge_id")
        is_shown = request.data.get("is_shown")
        
        if not badge_id or is_shown is None:
            return Response({"error": "badge_id and is_shown are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            badge = UserBadge.objects.get(user=request.user, badge_id=badge_id)
            # is_shown có thể truyền lên boolean (true/false) hoặc chuỗi ('true'/'false')
            if isinstance(is_shown, str):
                is_shown = is_shown.lower() == 'true'
            
            badge.is_shown = bool(is_shown)
            badge.save(update_fields=['is_shown'])
            return Response({"success": True, "badge_id": badge_id, "is_shown": badge.is_shown})
        except UserBadge.DoesNotExist:
            return Response({"error": "Badge not found"}, status=status.HTTP_404_NOT_FOUND)
