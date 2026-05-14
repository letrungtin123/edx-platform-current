"""
admin_api.py — LANDA Admin API trên LMS

DRF views cho admin panel (frontend-shell).
Auth: Bearer token (OAuth2) — tự động qua LMS DRF pipeline.
Permission: chỉ staff/superuser.

Prefix: /api/landa/admin/
"""
import json
import logging
import os

from django.db.models import Count, Q
from django.template.defaultfilters import filesizeformat
from django.utils.text import slugify
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import (
    SessionAuthenticationAllowInactiveUser,
)
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument, CourseModalConfig
from lms.djangoapps.landa_library.validators import ALLOWED_EXTENSIONS, get_file_extension
from lms.djangoapps.landa_library.audit import log_admin_action
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

log = logging.getLogger(__name__)

# Auth classes dùng chung cho tất cả admin views
ADMIN_AUTH_CLASSES = [
    JwtAuthentication,
    BearerAuthenticationAllowInactiveUser,
    SessionAuthenticationAllowInactiveUser,
]


class IsStaffUser(permissions.BasePermission):
    """Chỉ cho phép staff/superuser."""
    def has_permission(self, request, view):
        return request.user and request.user.is_staff


# ══════════════════════════════════════════════
# Documents API
# ══════════════════════════════════════════════

class AdminDocumentsView(APIView):
    """
    GET  /api/landa/admin/documents/   — List tài liệu (admin, không filter is_visible)
    POST /api/landa/admin/documents/   — Upload file(s)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        qs = LibraryDocument.objects.select_related('category', 'uploaded_by').order_by('-created_at')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(title__icontains=search)

        cat_id = request.query_params.get('category_id')
        if cat_id:
            qs = qs.filter(category_id=int(cat_id))

        ext = request.query_params.get('extension')
        if ext:
            qs = qs.filter(extension=ext.lower())

        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 50)), 100)
        total = qs.count()
        offset = (page - 1) * page_size
        docs = qs[offset:offset + page_size]

        data = []
        for doc in docs:
            data.append({
                'id': doc.id,
                'title': doc.title,
                'extension': doc.extension,
                'file_size': doc.file_size,
                'file_size_display': filesizeformat(doc.file_size) if doc.file_size else '-',
                'category_id': doc.category_id or '',
                'category_name': doc.category.name if doc.category else '',
                'is_visible': doc.is_visible,
                'uploaded_by_name': (
                    doc.uploaded_by.get_full_name() or doc.uploaded_by.username
                ) if doc.uploaded_by else 'Admin',
                'created_at': doc.created_at.strftime('%d/%m/%Y %H:%M') if doc.created_at else '',
            })

        return Response({
            'documents': data,
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    def post(self, request):
        files = request.FILES.getlist('file')
        if not files:
            return Response({'error': 'Chưa chọn file'}, status=status.HTTP_400_BAD_REQUEST)

        title = request.data.get('title', '').strip()
        category_id = request.data.get('category_id')
        created = []
        errors = []

        for f in files:
            ext = get_file_extension(f.name)
            if ext not in ALLOWED_EXTENSIONS:
                errors.append(f"'{f.name}': đuôi .{ext} không hỗ trợ")
                continue

            doc_title = title or os.path.splitext(f.name)[0]
            if len(files) > 1 and title:
                doc_title = f"{title} - {os.path.splitext(f.name)[0]}"

            doc = LibraryDocument(title=doc_title, file=f, uploaded_by=request.user)
            if category_id:
                try:
                    doc.category = DocumentCategory.objects.get(id=int(category_id))
                except (DocumentCategory.DoesNotExist, ValueError):
                    pass
            doc.save()
            created.append(doc.id)

        result = {'success': True, 'created': len(created)}
        if errors:
            result['errors'] = errors
        for cid in created:
            log_admin_action(request, 'CREATE', 'Document', title or 'upload', entity_id=str(cid))
        return Response(result)


class AdminDocumentDetailView(APIView):
    """
    PATCH  /api/landa/admin/documents/<id>/  — Sửa tài liệu
    DELETE /api/landa/admin/documents/<id>/  — Xóa tài liệu
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request, doc_id):
        try:
            doc = LibraryDocument.objects.get(id=doc_id)
        except LibraryDocument.DoesNotExist:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'is_visible' in data:
            doc.is_visible = bool(data['is_visible'])
        if 'title' in data and data['title'].strip():
            doc.title = data['title'].strip()
        if 'category_id' in data:
            cat_id = data['category_id']
            if cat_id:
                try:
                    doc.category = DocumentCategory.objects.get(id=int(cat_id))
                except (DocumentCategory.DoesNotExist, ValueError):
                    pass
            else:
                doc.category = None
        doc.save()
        log_admin_action(request, 'UPDATE', 'Document', doc.title, entity_id=str(doc.id))
        return Response({'success': True})

    def delete(self, request, doc_id):
        try:
            doc = LibraryDocument.objects.get(id=doc_id)
        except LibraryDocument.DoesNotExist:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        doc_title = doc.title
        doc_id = doc.id
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        log_admin_action(request, 'DELETE', 'Document', doc_title, entity_id=str(doc_id))
        return Response({'success': True})


class AdminDocumentBulkView(APIView):
    """POST /api/landa/admin/documents/bulk/ — Bulk show/hide/set_category"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def post(self, request):
        ids = request.data.get('ids', [])
        action = request.data.get('action')
        if not ids or action not in ('show', 'hide', 'set_category'):
            return Response({'error': 'Invalid'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'set_category':
            cat_id = request.data.get('category_id')
            category = None
            if cat_id:
                try:
                    category = DocumentCategory.objects.get(id=int(cat_id))
                except (DocumentCategory.DoesNotExist, ValueError):
                    return Response({'error': 'Danh mục không tồn tại'}, status=status.HTTP_400_BAD_REQUEST)
            updated = LibraryDocument.objects.filter(id__in=ids).update(category=category)
            return Response({'success': True, 'updated': updated})

        updated = LibraryDocument.objects.filter(id__in=ids).update(is_visible=(action == 'show'))
        return Response({'success': True, 'updated': updated})


# ══════════════════════════════════════════════
# Categories API
# ══════════════════════════════════════════════

class AdminCategoriesView(APIView):
    """
    GET  /api/landa/admin/categories/  — List danh mục
    POST /api/landa/admin/categories/  — Tạo danh mục
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        qs = DocumentCategory.objects.annotate(
            doc_count=Count('documents')
        ).order_by('sort_order', 'name')

        # Search theo tên hoặc slug
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(slug__icontains=search))

        # Filter theo số tài liệu
        doc_filter = request.query_params.get('doc_count')
        if doc_filter == 'has_docs':
            qs = qs.filter(doc_count__gt=0)
        elif doc_filter == 'empty':
            qs = qs.filter(doc_count=0)

        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 50)), 100)
        total = qs.count()
        offset = (page - 1) * page_size
        cats = qs[offset:offset + page_size]

        data = [{
            'id': c.id,
            'name': c.name,
            'slug': c.slug,
            'sort_order': c.sort_order,
            'doc_count': c.doc_count,
        } for c in cats]
        return Response({
            'categories': data,
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên trống'}, status=status.HTTP_400_BAD_REQUEST)
        if DocumentCategory.objects.filter(name=name).exists():
            return Response({'error': f'"{name}" đã tồn tại'}, status=status.HTTP_400_BAD_REQUEST)
        cat = DocumentCategory.objects.create(
            name=name,
            slug=slugify(name, allow_unicode=True),
        )
        log_admin_action(request, 'CREATE', 'Category', name, entity_id=str(cat.id))
        return Response({'success': True, 'id': cat.id, 'slug': cat.slug})


class AdminCategoryDetailView(APIView):
    """
    PATCH  /api/landa/admin/categories/<id>/  — Sửa tên
    DELETE /api/landa/admin/categories/<id>/  — Xóa
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request, cat_id):
        try:
            cat = DocumentCategory.objects.get(id=cat_id)
        except DocumentCategory.DoesNotExist:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên trống'}, status=status.HTTP_400_BAD_REQUEST)
        if DocumentCategory.objects.filter(name=name).exclude(id=cat_id).exists():
            return Response({'error': f'"{name}" đã tồn tại'}, status=status.HTTP_400_BAD_REQUEST)

        cat.name = name
        cat.slug = slugify(name, allow_unicode=True)
        cat.save()
        log_admin_action(request, 'UPDATE', 'Category', name, entity_id=str(cat.id))
        return Response({'success': True})

    def delete(self, request, cat_id):
        try:
            cat = DocumentCategory.objects.get(id=cat_id)
        except DocumentCategory.DoesNotExist:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        cat_name = cat.name
        cat.delete()
        log_admin_action(request, 'DELETE', 'Category', cat_name, entity_id=str(cat_id))
        return Response({'success': True})


class AdminCategoryBulkView(APIView):
    """POST /api/landa/admin/categories/bulk/ — Bulk delete"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def post(self, request):
        ids = request.data.get('ids', [])
        action = request.data.get('action')
        if not ids or action != 'delete':
            return Response({'error': 'Invalid'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = DocumentCategory.objects.filter(id__in=ids).delete()
        return Response({'success': True, 'deleted': deleted})


# ══════════════════════════════════════════════
# Courses API
# ══════════════════════════════════════════════

class AdminCoursesView(APIView):
    """GET /api/landa/admin/courses/ — List khóa học"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        qs = CourseOverview.objects.all().order_by('-modified')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(display_name__icontains=search) | Q(id__icontains=search))

        visibility = request.query_params.get('visibility', 'all')
        if visibility == 'staff_only':
            qs = qs.filter(visible_to_staff_only=True)
        elif visibility == 'public':
            qs = qs.filter(visible_to_staff_only=False)

        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 20)), 100)
        total = qs.count()
        offset = (page - 1) * page_size
        courses = qs[offset:offset + page_size]

        data = []
        for c in courses:
            data.append({
                'id': str(c.id),
                'display_name': c.display_name,
                'org': c.org,
                'visible_to_staff_only': c.visible_to_staff_only,
                'start': c.start.strftime('%d/%m/%Y') if c.start else '-',
                'end': c.end.strftime('%d/%m/%Y') if c.end else '-',
                'created': c.created.strftime('%d/%m/%Y %H:%M') if c.created else '',
                'modified': c.modified.strftime('%d/%m/%Y %H:%M') if c.modified else '',
                'image_url': c.image_urls.get('raw', '') if hasattr(c, 'image_urls') else getattr(c, 'course_image_url', ''),
            })

        return Response({
            'courses': data,
            'total': total,
            'page': page,
            'page_size': page_size,
        })


class AdminCourseDetailView(APIView):
    """PATCH /api/landa/admin/courses/<course_id>/ — Sửa visibility/tên"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def patch(self, request, course_id):
        from opaque_keys.edx.keys import CourseKey
        try:
            key = CourseKey.from_string(course_id)
            course = CourseOverview.objects.get(id=key)
        except Exception:
            return Response({'error': 'Không tìm thấy khóa học'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        changed = False

        if 'visible_to_staff_only' in data:
            course.visible_to_staff_only = bool(data['visible_to_staff_only'])
            changed = True
        if 'display_name' in data and data['display_name'].strip():
            course.display_name = data['display_name'].strip()
            changed = True

        if changed:
            course.save()
            log.info(
                "LANDA Admin API: user %s updated course %s",
                request.user.username, course_id,
            )
            log_admin_action(request, 'UPDATE', 'Course', course.display_name, entity_id=str(course_id))
        return Response({'success': True})


class AdminCourseBulkView(APIView):
    """POST /api/landa/admin/courses-bulk/ — Bulk staff_only/public"""
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def post(self, request):
        from opaque_keys.edx.keys import CourseKey
        ids = request.data.get('ids', [])
        action = request.data.get('action')

        if not ids or action not in ('staff_only', 'public'):
            return Response({'error': 'Invalid'}, status=status.HTTP_400_BAD_REQUEST)

        keys = []
        for cid in ids:
            try:
                keys.append(CourseKey.from_string(cid))
            except Exception:
                pass

        new_value = (action == 'staff_only')
        updated = CourseOverview.objects.filter(id__in=keys).update(visible_to_staff_only=new_value)

        log.info(
            "LANDA Admin API: user %s bulk set %d courses visible_to_staff_only=%s",
            request.user.username, updated, new_value,
        )
        return Response({'success': True, 'updated': updated})

# ══════════════════════════════════════════════
# Course Modal Config API
# ══════════════════════════════════════════════

class AdminCourseModalConfigView(APIView):
    """
    GET  /api/landa/admin/courses/<course_id>/modal-config/ — Lấy cấu hình modal
    PUT  /api/landa/admin/courses/<course_id>/modal-config/ — Tạo hoặc cập nhật cấu hình
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    DEFAULTS = {
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
    }

    def get(self, request, course_id):
        try:
            cfg = CourseModalConfig.objects.get(course_id=course_id)
            data = {
                'course_id': cfg.course_id,
                'welcome_enabled': cfg.welcome_enabled,
                'welcome_title': cfg.welcome_title,
                'welcome_description': cfg.welcome_description,
                'confirm_enabled': cfg.confirm_enabled,
                'confirm_title': cfg.confirm_title,
                'confirm_description': cfg.confirm_description,
                'confirm_checkbox_text': cfg.confirm_checkbox_text,
                'completion_enabled': cfg.completion_enabled,
                'completion_title': cfg.completion_title,
                'completion_description': cfg.completion_description,
                'completion_social_type': cfg.completion_social_type,
                'completion_social_link': cfg.completion_social_link,
                'updated_at': cfg.updated_at.isoformat() if cfg.updated_at else None,
            }
        except CourseModalConfig.DoesNotExist:
            data = {'course_id': course_id, **self.DEFAULTS, 'updated_at': None}
        return Response(data)

    def put(self, request, course_id):
        data = request.data
        cfg, created = CourseModalConfig.objects.update_or_create(
            course_id=course_id,
            defaults={
                'welcome_enabled': data.get('welcome_enabled', True),
                'welcome_title': data.get('welcome_title', ''),
                'welcome_description': data.get('welcome_description', ''),
                'confirm_enabled': data.get('confirm_enabled', True),
                'confirm_title': data.get('confirm_title', ''),
                'confirm_description': data.get('confirm_description', ''),
                'confirm_checkbox_text': data.get('confirm_checkbox_text', ''),
                'completion_enabled': data.get('completion_enabled', True),
                'completion_title': data.get('completion_title', ''),
                'completion_description': data.get('completion_description', ''),
                'completion_social_type': data.get('completion_social_type', ''),
                'completion_social_link': data.get('completion_social_link', ''),
                'updated_by': request.user,
            }
        )
        log_admin_action(
            request, 'UPDATE' if not created else 'CREATE',
            'CourseModalConfig', course_id, entity_id=course_id,
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Course Notification API (gửi thông báo cho learner)
# ══════════════════════════════════════════════

class AdminCourseNotificationView(APIView):
    """
    POST /api/landa/admin/courses/<course_id>/send-notification/
    Gửi notification cho tất cả learner enrolled trong course.

    Request body:
    {
        "title": "Tiêu đề thông báo",
        "message": "Nội dung thông báo HTML"
    }
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def post(self, request, course_id):
        title = (request.data.get('title') or '').strip()
        message = (request.data.get('message') or '').strip()

        if not message:
            return Response(
                {'error': 'message is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lấy danh sách user_ids enrolled trong course
        from common.djangoapps.student.models import CourseEnrollment
        from opaque_keys.edx.keys import CourseKey

        try:
            course_key = CourseKey.from_string(course_id)
        except Exception:
            return Response(
                {'error': 'Invalid course_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from lms.djangoapps.landa_groups.models import SubGroupCourseAssignment, SubGroupMembership

        # 1. Tìm các subgroups được assign course này
        assigned_subgroups = SubGroupCourseAssignment.objects.filter(
            course_id=str(course_key)
        ).values_list('subgroup_id', flat=True)

        # 2. Tìm tất cả users đang ở trong các subgroups đó
        allowed_user_ids = set(SubGroupMembership.objects.filter(
            subgroup_id__in=assigned_subgroups
        ).values_list('user_id', flat=True))

        # 3. Chỉ lấy những enrolled users có mặt trong group đó
        enrolled_user_ids = list(
            CourseEnrollment.objects
            .filter(course_id=course_key, is_active=True, user_id__in=allowed_user_ids)
            .values_list('user_id', flat=True)
        )

        import logging
        logger = logging.getLogger(__name__)
        logger.error(f">>>>> DEBUG NOTIFICATION <<<<<")
        logger.error(f"COURSE: {course_id}")
        logger.error(f"ENROLLED USERS (is_active=True): {enrolled_user_ids}")
        logger.error(f"REQUEST USER: {request.user.id} - {request.user.username}")

        if not enrolled_user_ids:
            return Response(
                {'error': 'No enrolled learners found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Tạo Notification trực tiếp cho mỗi enrolled user
        from openedx.core.djangoapps.notifications.models import Notification

        content_html = message
        if title:
            content_html = f'<p><strong>{title}</strong></p>{message}'

        created_count = 0
        for uid in enrolled_user_ids:
            notif = Notification(
                user_id=uid,
                app_name='updates',
                notification_type='course_updates',
                content_context={
                    'course_update_content': content_html,
                },
                course_id=course_key,
                web=True,
                email=False,
                push=False,
            )
            notif.save()
            created_count += 1

        log_admin_action(
            request, 'NOTIFY',
            'Course', course_id, entity_id=course_id,
        )

        log.info(
            "Admin %s sent notification to %d learners in %s",
            request.user.username, len(enrolled_user_ids), course_id,
        )

        return Response({
            'success': True,
            'recipients': created_count,
        })


from rest_framework.permissions import AllowAny
class TestNotsView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        uid = request.GET.get('uid')
        if not uid:
            from openedx.core.djangoapps.notifications.models import Notification
            nots = Notification.objects.order_by('-created')[:10]
        else:
            from openedx.core.djangoapps.notifications.models import Notification
            nots = Notification.objects.filter(user_id=uid).order_by('-created')[:10]
        
        data = []
        for n in nots:
            data.append({
                'id': n.id,
                'user_id': n.user_id,
                'course_id': str(n.course_id),
                'app_name': n.app_name,
                'notification_type': n.notification_type,
                'content_context': n.content_context,
                'web': n.web,
                'created': n.created.isoformat() if n.created else None,
            })
        return Response({'count': len(data), 'data': data})
# ══════════════════════════════════════════════
# User Management API
# ══════════════════════════════════════════════

class AdminUsersView(APIView):
    """
    GET /api/landa/admin/users/ - Lấy danh sách users
    POST /api/landa/admin/users/ - Tạo user mới
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        from django.contrib.auth.models import User
        from openedx.core.djangoapps.user_api.models import UserPreference
        
        # Pagination
        try:
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 10))
        except ValueError:
            page, page_size = 1, 10
            
        offset = (page - 1) * page_size
        
        # Filter
        search = request.GET.get('search', '').strip()
        role = request.GET.get('role', '').strip()
        
        qs = User.objects.all().order_by('-date_joined')
        
        if search:
            qs = qs.filter(Q(username__icontains=search) | Q(email__icontains=search))
            
        if role == 'superuser':
            qs = qs.filter(is_superuser=True)
        elif role == 'staff':
            qs = qs.filter(is_superuser=False, is_staff=True)
        elif role == 'learner':
            qs = qs.filter(is_superuser=False, is_staff=False)
            
        total = qs.count()
        users = list(qs[offset:offset+page_size])
        user_ids = [u.id for u in users]
        
        # Optimize Phone number query (N+1 safe)
        # Ưu tiên profile.phone_number (nguồn chính), fallback UserPreference (dữ liệu cũ)
        from common.djangoapps.student.models import UserProfile
        profiles = UserProfile.objects.filter(user_id__in=user_ids).values_list('user_id', 'phone_number')
        profile_phone_map = {uid: phone for uid, phone in profiles if phone}

        prefs = UserPreference.objects.filter(user_id__in=user_ids, key='phone')
        pref_phone_map = {p.user_id: p.value for p in prefs}
        
        data = []
        for u in users:
            if u.is_superuser:
                u_role = 'superuser'
            elif u.is_staff:
                u_role = 'staff'
            else:
                u_role = 'learner'
                
            data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'phone': profile_phone_map.get(u.id) or pref_phone_map.get(u.id, ''),
                'role': u_role,
                'is_active': u.is_active,
                'date_joined': u.date_joined.isoformat() if u.date_joined else None
            })
            
        return Response({
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'results': data
        })

    def post(self, request):
        from django.contrib.auth.models import User
        from openedx.core.djangoapps.user_api.preferences.api import set_user_preference
        
        data = request.data
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'learner')
        
        if not username or not email or not password or not phone:
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)
            
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
            
        if User.objects.filter(email=email).exists():
            return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Role Validation
        if role in ['superuser', 'staff'] and not request.user.is_superuser:
            return Response({'error': 'Only superuser can create staff or superuser'}, status=status.HTTP_403_FORBIDDEN)
            
        # Create User
        user = User.objects.create_user(username=username, email=email, password=password)
        
        if role == 'superuser':
            user.is_superuser = True
            user.is_staff = True
        elif role == 'staff':
            user.is_superuser = False
            user.is_staff = True
        else:
            user.is_superuser = False
            user.is_staff = False
            
        user.save()
        
        # Save phone
        set_user_preference(user, 'phone', phone)
        
        log_admin_action(request, 'CREATE', 'User', f'{username} ({email})', entity_id=str(user.id))
        return Response({'success': True, 'id': user.id})

class AdminUserDetailView(APIView):
    """
    PUT /api/landa/admin/users/<id>/ - Cập nhật user
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def put(self, request, user_id):
        from django.contrib.auth.models import User
        from openedx.core.djangoapps.user_api.preferences.api import set_user_preference
        
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
            
        # Permission check
        if not request.user.is_superuser:
            if target_user.is_superuser:
                return Response({'error': 'Staff cannot modify superuser'}, status=status.HTTP_403_FORBIDDEN)
            if target_user.is_staff and target_user.id != request.user.id:
                return Response({'error': 'Staff cannot modify another staff'}, status=status.HTTP_403_FORBIDDEN)
                
        data = request.data
        changed = False
        
        if 'email' in data and data['email'].strip() and target_user.email != data['email'].strip():
            if User.objects.filter(email=data['email'].strip()).exclude(id=user_id).exists():
                return Response({'error': 'Email already in use'}, status=status.HTTP_400_BAD_REQUEST)
            target_user.email = data['email'].strip()
            changed = True
            
        if 'phone' in data:
            phone_val = data['phone'].strip()
            set_user_preference(target_user, 'phone', phone_val)
            # Đồng bộ vào profile.phone_number (nguồn chính cho accounts API)
            from common.djangoapps.student.models import UserProfile
            UserProfile.objects.filter(user=target_user).update(phone_number=phone_val)
            
        if 'password' in data and data['password']:
            target_user.set_password(data['password'])
            changed = True
            
        if 'is_active' in data:
            target_user.is_active = bool(data['is_active'])
            changed = True
            # Ghi/xóa Redis blacklist → kick user tức thời
            from lms.djangoapps.landa_library.blacklist import blacklist_user, unblacklist_user
            if target_user.is_active:
                unblacklist_user(target_user.id)
            else:
                blacklist_user(target_user.id)
            
        if 'role' in data:
            new_role = data['role']
            if new_role in ['superuser', 'staff'] and not request.user.is_superuser:
                return Response({'error': 'Only superuser can grant superuser or staff role'}, status=status.HTTP_403_FORBIDDEN)
                
            if new_role == 'superuser':
                target_user.is_superuser = True
                target_user.is_staff = True
            elif new_role == 'staff':
                target_user.is_superuser = False
                target_user.is_staff = True
            elif new_role == 'learner':
                target_user.is_superuser = False
                target_user.is_staff = False
            changed = True
            
        if changed:
            target_user.save()
            changes = [k for k in ('email', 'password', 'is_active', 'role') if k in data]
            log_admin_action(request, 'UPDATE', 'User', f'{target_user.username} ({target_user.email})', entity_id=str(user_id), details=f'Changed: {", ".join(changes)}')
        return Response({'success': True})


# ══════════════════════════════════════════════
# Audit Logs API
# ══════════════════════════════════════════════

class IsSuperUser(permissions.BasePermission):
    """Chỉ cho phép superuser."""
    def has_permission(self, request, view):
        return request.user and request.user.is_superuser


class AdminAuditLogsView(APIView):
    """
    GET /api/landa/admin/audit-logs/ — Xem audit logs
    Permission: chỉ superuser
    
    Query params:
      - page (int, default 1)
      - page_size (int, default 20, max 100)
      - search (string, tìm theo actor_username hoặc entity_name)
      - action (CREATE|UPDATE|DELETE)
      - date_from (ISO date, VD: 2026-05-01)
      - date_to (ISO date, VD: 2026-05-06)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsSuperUser]

    def get(self, request):
        from lms.djangoapps.landa_library.models import AdminAuditLog
        from django.utils.dateparse import parse_date

        qs = AdminAuditLog.objects.all()

        # Filter by action
        action = request.query_params.get('action', '').strip().upper()
        if action in ('CREATE', 'UPDATE', 'DELETE'):
            qs = qs.filter(action=action)

        # Filter by date range
        date_from = request.query_params.get('date_from', '').strip()
        if date_from:
            parsed = parse_date(date_from)
            if parsed:
                qs = qs.filter(created_at__date__gte=parsed)

        date_to = request.query_params.get('date_to', '').strip()
        if date_to:
            parsed = parse_date(date_to)
            if parsed:
                qs = qs.filter(created_at__date__lte=parsed)

        # Search by actor_username or entity_name
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(actor_username__icontains=search) |
                Q(entity_name__icontains=search)
            )

        # Pagination
        try:
            page = max(1, int(request.query_params.get('page', 1)))
            page_size = min(max(1, int(request.query_params.get('page_size', 20))), 100)
        except (ValueError, TypeError):
            page, page_size = 1, 20

        total = qs.count()
        offset = (page - 1) * page_size
        logs = qs.only(
            'id', 'actor_username', 'action', 'entity_type',
            'entity_name', 'entity_id', 'details', 'ip_address', 'created_at'
        )[offset:offset + page_size]

        results = [
            {
                'id': lg.id,
                'actor_username': lg.actor_username,
                'action': lg.action,
                'entity_type': lg.entity_type,
                'entity_name': lg.entity_name,
                'entity_id': lg.entity_id,
                'details': lg.details,
                'ip_address': lg.ip_address or '',
                'created_at': lg.created_at.isoformat(),
            }
            for lg in logs
        ]

        return Response({
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'results': results,
        })

