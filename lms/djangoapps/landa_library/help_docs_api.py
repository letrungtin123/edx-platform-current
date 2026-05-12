"""
help_docs_api.py — Help Docs API trên LMS

DRF views cho Help Docs module (frontend-shell).
Auth: Bearer token (OAuth2).
Permission:
  - GET: staff hoặc superuser
  - POST/PATCH/DELETE: chỉ superuser

Prefix: /api/landa/admin/help-*
"""
import logging
import os

from django.db.models import Count
from django.utils.text import slugify
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from lms.djangoapps.landa_library.admin_api import ADMIN_AUTH_CLASSES, IsStaffUser
from lms.djangoapps.landa_library.audit import log_admin_action
from lms.djangoapps.landa_library.models import HelpFolder, HelpPage, help_image_upload_path

log = logging.getLogger(__name__)


def _require_superuser(request):
    """Trả về Response 403 nếu không phải superuser, None nếu OK."""
    if not request.user.is_superuser:
        return Response(
            {'error': 'Chỉ superuser mới được thực hiện thao tác này'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _generate_unique_slug(model_class, title, exclude_id=None, scope_filter=None):
    """Tạo slug unique, thêm suffix nếu trùng."""
    base_slug = slugify(title, allow_unicode=True) or 'untitled'
    slug = base_slug
    counter = 1
    while True:
        qs = model_class.objects.filter(slug=slug)
        if scope_filter:
            qs = qs.filter(**scope_filter)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        if not qs.exists():
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


# ══════════════════════════════════════════════
# Help Folders API
# ══════════════════════════════════════════════

class HelpFoldersView(APIView):
    """
    GET  /api/landa/admin/help-folders/  — List folders kèm page_count
    POST /api/landa/admin/help-folders/  — Tạo folder (superuser only)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        folders = HelpFolder.objects.annotate(
            page_count=Count('pages')
        ).order_by('sort_order', 'title')

        data = [{
            'id': f.id,
            'title': f.title,
            'slug': f.slug,
            'icon': f.icon,
            'sort_order': f.sort_order,
            'page_count': f.page_count,
            'created_at': f.created_at.isoformat() if f.created_at else None,
            'updated_at': f.updated_at.isoformat() if f.updated_at else None,
        } for f in folders]

        return Response({'folders': data, 'total': len(data)})

    def post(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        title = (request.data.get('title') or '').strip()
        if not title:
            return Response({'error': 'Tên folder không được trống'}, status=status.HTTP_400_BAD_REQUEST)

        icon = (request.data.get('icon') or '').strip()

        # Auto sort_order: đặt cuối
        max_order = HelpFolder.objects.aggregate(m=Count('id'))['m'] or 0

        slug = _generate_unique_slug(HelpFolder, title)
        folder = HelpFolder.objects.create(
            title=title,
            slug=slug,
            icon=icon,
            sort_order=max_order,
            created_by=request.user,
        )
        log_admin_action(request, 'CREATE', 'HelpFolder', title, entity_id=str(folder.id))
        return Response({
            'success': True,
            'id': folder.id,
            'slug': folder.slug,
        }, status=status.HTTP_201_CREATED)


class HelpFolderDetailView(APIView):
    """
    PATCH  /api/landa/admin/help-folders/<id>/  — Sửa folder (superuser only)
    DELETE /api/landa/admin/help-folders/<id>/  — Xóa folder + cascade pages (superuser only)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request, folder_id):
        denied = _require_superuser(request)
        if denied:
            return denied

        try:
            folder = HelpFolder.objects.get(id=folder_id)
        except HelpFolder.DoesNotExist:
            return Response({'error': 'Folder không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'title' in data:
            title = (data['title'] or '').strip()
            if not title:
                return Response({'error': 'Tên folder không được trống'}, status=status.HTTP_400_BAD_REQUEST)
            folder.title = title
            folder.slug = _generate_unique_slug(HelpFolder, title, exclude_id=folder.id)

        if 'icon' in data:
            folder.icon = (data['icon'] or '').strip()

        folder.save()
        log_admin_action(request, 'UPDATE', 'HelpFolder', folder.title, entity_id=str(folder.id))
        return Response({'success': True})

    def delete(self, request, folder_id):
        denied = _require_superuser(request)
        if denied:
            return denied

        try:
            folder = HelpFolder.objects.get(id=folder_id)
        except HelpFolder.DoesNotExist:
            return Response({'error': 'Folder không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        folder_title = folder.title
        folder.delete()  # CASCADE sẽ xóa pages
        log_admin_action(request, 'DELETE', 'HelpFolder', folder_title, entity_id=str(folder_id))
        return Response({'success': True})


class HelpFolderReorderView(APIView):
    """PATCH /api/landa/admin/help-folders/reorder/ — Đổi thứ tự folders (superuser only)"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        ordered_ids = request.data.get('ordered_ids', [])
        if not ordered_ids:
            return Response({'error': 'ordered_ids required'}, status=status.HTTP_400_BAD_REQUEST)

        for idx, fid in enumerate(ordered_ids):
            HelpFolder.objects.filter(id=fid).update(sort_order=idx)

        return Response({'success': True, 'updated': len(ordered_ids)})


# ══════════════════════════════════════════════
# Help Pages API
# ══════════════════════════════════════════════

class HelpPagesView(APIView):
    """
    GET  /api/landa/admin/help-pages/      — List pages (filter by folder_id)
    POST /api/landa/admin/help-pages/      — Tạo page (superuser only)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        qs = HelpPage.objects.select_related('folder').order_by('folder__sort_order', 'sort_order', 'title')

        folder_id = request.query_params.get('folder_id')
        if folder_id:
            qs = qs.filter(folder_id=int(folder_id))

        data = [{
            'id': p.id,
            'folder_id': p.folder_id,
            'folder_title': p.folder.title,
            'title': p.title,
            'slug': p.slug,
            'sort_order': p.sort_order,
            'is_published': p.is_published,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        } for p in qs]

        return Response({'pages': data, 'total': len(data)})

    def post(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        folder_id = request.data.get('folder_id')
        title = (request.data.get('title') or '').strip()
        content = request.data.get('content', '')

        if not folder_id:
            return Response({'error': 'folder_id required'}, status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({'error': 'Tiêu đề không được trống'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            folder = HelpFolder.objects.get(id=int(folder_id))
        except HelpFolder.DoesNotExist:
            return Response({'error': 'Folder không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        # Auto sort_order: đặt cuối trong folder
        max_order = folder.pages.count()

        slug = _generate_unique_slug(HelpPage, title, scope_filter={'folder_id': folder.id})
        page = HelpPage.objects.create(
            folder=folder,
            title=title,
            slug=slug,
            content=content,
            sort_order=max_order,
            is_published=False,
            created_by=request.user,
            updated_by=request.user,
        )
        log_admin_action(request, 'CREATE', 'HelpPage', title, entity_id=str(page.id))
        return Response({
            'success': True,
            'id': page.id,
            'slug': page.slug,
        }, status=status.HTTP_201_CREATED)


class HelpPageDetailView(APIView):
    """
    GET    /api/landa/admin/help-pages/<id>/  — Chi tiết page (content)
    PATCH  /api/landa/admin/help-pages/<id>/  — Sửa page (superuser only)
    DELETE /api/landa/admin/help-pages/<id>/  — Xóa page (superuser only)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, page_id):
        try:
            page = HelpPage.objects.select_related('folder', 'created_by', 'updated_by').get(id=page_id)
        except HelpPage.DoesNotExist:
            return Response({'error': 'Page không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': page.id,
            'folder_id': page.folder_id,
            'folder_title': page.folder.title,
            'title': page.title,
            'slug': page.slug,
            'content': page.content,
            'sort_order': page.sort_order,
            'is_published': page.is_published,
            'created_by': page.created_by.username if page.created_by else None,
            'updated_by': page.updated_by.username if page.updated_by else None,
            'created_at': page.created_at.isoformat() if page.created_at else None,
            'updated_at': page.updated_at.isoformat() if page.updated_at else None,
        })

    def patch(self, request, page_id):
        denied = _require_superuser(request)
        if denied:
            return denied

        try:
            page = HelpPage.objects.get(id=page_id)
        except HelpPage.DoesNotExist:
            return Response({'error': 'Page không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'title' in data:
            title = (data['title'] or '').strip()
            if not title:
                return Response({'error': 'Tiêu đề không được trống'}, status=status.HTTP_400_BAD_REQUEST)
            page.title = title
            page.slug = _generate_unique_slug(
                HelpPage, title,
                exclude_id=page.id,
                scope_filter={'folder_id': page.folder_id},
            )

        if 'content' in data:
            page.content = data['content']

        if 'is_published' in data:
            page.is_published = bool(data['is_published'])

        page.updated_by = request.user
        page.save()
        log_admin_action(request, 'UPDATE', 'HelpPage', page.title, entity_id=str(page.id))
        return Response({'success': True})

    def delete(self, request, page_id):
        denied = _require_superuser(request)
        if denied:
            return denied

        try:
            page = HelpPage.objects.get(id=page_id)
        except HelpPage.DoesNotExist:
            return Response({'error': 'Page không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        page_title = page.title
        page.delete()
        log_admin_action(request, 'DELETE', 'HelpPage', page_title, entity_id=str(page_id))
        return Response({'success': True})


class HelpPageReorderView(APIView):
    """PATCH /api/landa/admin/help-pages/reorder/ — Đổi thứ tự pages trong folder (superuser only)"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        folder_id = request.data.get('folder_id')
        ordered_ids = request.data.get('ordered_ids', [])
        if not folder_id or not ordered_ids:
            return Response({'error': 'folder_id và ordered_ids required'}, status=status.HTTP_400_BAD_REQUEST)

        for idx, pid in enumerate(ordered_ids):
            HelpPage.objects.filter(id=pid, folder_id=folder_id).update(sort_order=idx)

        return Response({'success': True, 'updated': len(ordered_ids)})


class HelpImageUploadView(APIView):
    """
    POST /api/landa/admin/help-pages/upload-image/
    Upload ảnh, trả URL tuyệt đối để embed trong rich text editor.
    Superuser only.
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]
    parser_classes = [MultiPartParser, FormParser]

    ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

    def post(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        image = request.FILES.get('image')
        if not image:
            return Response({'error': 'Chưa chọn file ảnh'}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(image.name)[1].lstrip('.').lower()
        if ext not in self.ALLOWED_IMAGE_EXTS:
            return Response(
                {'error': f'Định dạng .{ext} không hỗ trợ. Cho phép: {", ".join(self.ALLOWED_IMAGE_EXTS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if image.size > self.MAX_FILE_SIZE:
            return Response({'error': 'File quá lớn (tối đa 5MB)'}, status=status.HTTP_400_BAD_REQUEST)

        # Lưu file vào MEDIA_ROOT/help_docs/images/
        from django.core.files.storage import default_storage
        path = help_image_upload_path(None, image.name)
        saved_path = default_storage.save(path, image)
        url = default_storage.url(saved_path)

        return Response({
            'success': True,
            'url': url,
            'filename': os.path.basename(saved_path),
        })
