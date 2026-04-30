"""
views.py — LANDA Library API Views

GET /api/landa/v1/library/documents/
    → Danh sách tài liệu visible, phân trang + filter + search

GET /api/landa/v1/library/categories/
    → Danh sách category + số file visible

GET /api/landa/v1/library/download/<id>/
    → Download file (protected — yêu cầu đăng nhập)

Auth: JWT hoặc Session — user phải đăng nhập.
"""

import logging
import os

from django.db.models import Count, Q
from django.http import FileResponse, Http404
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

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument
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
        qs = (
            LibraryDocument.objects
            .filter(is_visible=True)
            .select_related('category', 'uploaded_by')
        )

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

        serializer = DocumentCategorySerializer(categories, many=True)

        # Tổng số file visible (tất cả category)
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
        doc = LibraryDocument.objects.get(id=doc_id, is_visible=True)
    except LibraryDocument.DoesNotExist:
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
