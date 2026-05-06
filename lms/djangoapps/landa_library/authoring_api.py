"""
authoring_api.py — Backend endpoints cho Course Authoring

Architecture:
- CourseAPIView: tạo/list courses (không có Studio native endpoint cho JWT auth)
- XBlockCRUDAPIView: CREATE/UPDATE/DELETE xblock bằng cách gọi Python functions nội bộ.
  KHÔNG dùng Studio /xblock/ endpoint trực tiếp vì:
  1. CSRF token của Studio khác LMS — frontend bị 403
  2. @expect_json decorator đọc lại request.body đã bị DRF consume → 500
  Giải pháp: gọi create_xblock(), _save_xblock(), _delete_item() trực tiếp.
- XBlockHandlerAPIView: proxy component_handler cho custom XBlocks
"""
import logging
import datetime

from django.core.exceptions import PermissionDenied
from django.http import Http404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from cms.djangoapps.contentstore.xblock_storage_handlers.xblock_helpers import usage_key_with_run
from cms.djangoapps.contentstore.views.component import component_handler
from cms.djangoapps.contentstore.asset_storage_handlers import handle_assets
from cms.djangoapps.contentstore.views.course import create_new_course
from xmodule.modulestore.django import modulestore
from common.djangoapps.student.auth import has_studio_read_access, has_studio_write_access
from common.djangoapps.util.json_request import JsonResponse

log = logging.getLogger(__name__)



from lms.djangoapps.landa_library.admin_api import ADMIN_AUTH_CLASSES

class BaseAuthoringView(APIView):
    """
    Base view: Sử dụng authentication chuẩn gồm JWT Bearer và Session.
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsAuthenticated]


class CourseAPIView(BaseAuthoringView):
    """
    Tạo/list courses qua JWT auth.
    GET  /landa-admin/api/authoring/courses/
    POST /landa-admin/api/authoring/courses/
    """

    def get(self, request):
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

        result = []
        for course in CourseOverview.get_all_courses():
            if has_studio_read_access(request.user, course.id):
                result.append({
                    'id': str(course.id),
                    'display_name': course.display_name,
                    'org': course.org,
                    'number': course.number,
                    'run': course.id.run,
                    'start': course.start.isoformat() if course.start else None,
                    'end': course.end.isoformat() if course.end else None,
                })
        return Response(result)

    def post(self, request):
        data = request.data
        org = data.get('org', '').strip()
        number = data.get('number', '').strip()
        run = data.get('run', '').strip()
        display_name = data.get('display_name', '').strip()
        start_str = data.get('start')

        if not all([org, number, run, display_name]):
            return Response({'error': 'Thiếu org, number, run hoặc display_name'}, status=400)

        try:
            if start_str:
                start = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            else:
                start = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)

            fields = {'display_name': display_name, 'start': start}
            new_course = create_new_course(request.user, org, number, run, fields)
            return Response({
                'id': str(new_course.id),
                'display_name': new_course.display_name,
                'org': new_course.location.org,
                'number': new_course.location.course,
                'run': new_course.location.run,
            }, status=201)
        except Exception as e:
            log.exception('Error creating course: %s', e)
            return Response({'error': str(e)}, status=400)


class AssetAPIView(BaseAuthoringView):
    """
    Xử lý assets (upload ảnh, files) thông qua JWT.
    POST /landa-admin/api/authoring/assets/{course_key}/
    """
    def get(self, request, course_key_string, asset_key_string=None):
        return handle_assets(request._request, course_key_string, asset_key_string)

    def post(self, request, course_key_string, asset_key_string=None):
        return handle_assets(request._request, course_key_string, asset_key_string)

    def put(self, request, course_key_string, asset_key_string=None):
        return handle_assets(request._request, course_key_string, asset_key_string)

    def delete(self, request, course_key_string, asset_key_string=None):
        return handle_assets(request._request, course_key_string, asset_key_string)

class XBlockCRUDAPIView(BaseAuthoringView):
    """
    CRUD cho XBlock — gọi trực tiếp internal CMS Python functions.
    Tránh hoàn toàn @expect_json decorator và Studio CSRF validation.

    POST   /landa-admin/api/authoring/xblock/              — tạo xblock mới
    POST   /landa-admin/api/authoring/xblock/{key}         — update xblock
    DELETE /landa-admin/api/authoring/xblock/{key}         — xóa xblock
    """

    def post(self, request, usage_key_string=None):
        if usage_key_string:
            return self._update_xblock(request, usage_key_string)
        return self._create_xblock(request)

    def get(self, request, usage_key_string=None):
        if not usage_key_string:
            return JsonResponse({'error': 'Missing usage_key_string'}, status=400)
        return self._get_xblock(request, usage_key_string)

    def delete(self, request, usage_key_string):
        return self._delete_xblock(request, usage_key_string)

    # ── Create ──────────────────────────────────────────────────────────────

    def _create_xblock(self, request):
        """
        Tạo XBlock mới. Payload: { parent_locator, category, display_name?, boilerplate? }
        Gọi create_xblock() Python function trực tiếp — KHÔNG qua handle_xblock.
        """
        from cms.djangoapps.contentstore.xblock_storage_handlers.create_xblock import create_xblock

        data = request.data
        parent_locator = data.get('parent_locator')
        category = data.get('category') or data.get('type')

        if not parent_locator or not category:
            return JsonResponse({'error': 'parent_locator và category là bắt buộc'}, status=400)

        try:
            parent_key = usage_key_with_run(parent_locator)
        except Exception:
            return JsonResponse({'error': f'parent_locator không hợp lệ: {parent_locator}'}, status=400)

        if not has_studio_write_access(request.user, parent_key.course_key):
            raise PermissionDenied()

        try:
            from xmodule.modulestore.django import modulestore
            store = modulestore()
            
            with store.bulk_operations(parent_key.course_key):
                # Ensure the category is in advanced_modules if it's a custom block
                if category in ['la_crossword', 'la_sortable', 'la_diagram']:
                    course = store.get_course(parent_key.course_key)
                    if course and category not in course.advanced_modules:
                        course.advanced_modules.append(category)
                        store.update_item(course, request.user.id)

                created = create_xblock(
                    parent_locator=parent_locator,
                    user=request.user,
                    category=category,
                    display_name=data.get('display_name'),
                    boilerplate=data.get('boilerplate'),
                )
            
            return JsonResponse({
                'locator': str(created.location),
                'courseKey': str(created.location.course_key),
            })
        except Exception as e:
            log.exception('Error creating xblock (category=%s): %s', category, e)
            return JsonResponse({'error': str(e)}, status=500)

    # ── Get ─────────────────────────────────────────────────────────────────

    def _get_xblock(self, request, usage_key_string):
        """
        Lấy thông tin XBlock: data, metadata, children
        """
        try:
            usage_key = usage_key_with_run(usage_key_string)
        except Exception:
            return JsonResponse({'error': 'usage_key không hợp lệ'}, status=400)

        if not has_studio_read_access(request.user, usage_key.course_key):
            raise PermissionDenied()

        from cms.djangoapps.contentstore.views.block import create_xblock_info
        from cms.djangoapps.contentstore.xblock_storage_handlers.view_handlers import own_metadata
        from common.djangoapps.static_replace import replace_static_urls

        store = modulestore()
        try:
            with store.bulk_operations(usage_key.course_key):
                root_xblock = store.get_item(usage_key, depth=None)
                data = getattr(root_xblock, "data", "")
                data = replace_static_urls(data, None, course_id=root_xblock.location.course_key)
                
                return JsonResponse(
                    create_xblock_info(
                        root_xblock,
                        data=data,
                        metadata=own_metadata(root_xblock),
                        include_child_info=True,
                        course_outline=True,
                        include_children_predicate=lambda xblock: not xblock.category == "vertical",
                    )
                )
        except Exception as e:
            log.exception('Error getting xblock (usage_key=%s): %s', usage_key_string, e)
            return JsonResponse({'error': str(e)}, status=500)

    # ── Update ──────────────────────────────────────────────────────────────

    def _update_xblock(self, request, usage_key_string):
        """
        Update XBlock: metadata, data, publish.
        Gọi modulestore().update_item() trực tiếp, không qua handle_xblock.
        """
        try:
            usage_key = usage_key_with_run(usage_key_string)
        except Exception:
            return JsonResponse({'error': 'usage_key không hợp lệ'}, status=400)

        if not has_studio_write_access(request.user, usage_key.course_key):
            raise PermissionDenied()

        data = request.data
        store = modulestore()

        try:
            with store.bulk_operations(usage_key.course_key):
                xblock = store.get_item(usage_key)

                # Update metadata fields
                metadata = data.get('metadata', {})
                for key, value in metadata.items():
                    if hasattr(xblock, key):
                        setattr(xblock, key, value)

                # Update data (HTML content, problem XML, etc.)
                if 'data' in data and hasattr(xblock, 'data'):
                    xblock.data = data['data']

                # Update children order
                if 'children' in data and hasattr(xblock, 'children'):
                    from opaque_keys.edx.keys import UsageKey
                    xblock.children = [UsageKey.from_string(c) for c in data['children']]

                store.update_item(xblock, request.user.id)

                # Handle publish
                publish = data.get('publish')
                if publish == 'make_public':
                    store.publish(usage_key, request.user.id)
                elif publish == 'republish':
                    if store.has_published_version(xblock):
                        store.publish(usage_key, request.user.id)

                # Cập nhật CourseOverview nếu thay đổi root course (ví dụ: đổi course_image)
                if xblock.category == 'course':
                    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
                    CourseOverview.update_select_courses([usage_key.course_key], force_update=True)

            return JsonResponse({
                'id': str(xblock.location),
                'display_name': xblock.display_name,
            })
        except Exception as e:
            log.exception('Error updating xblock %s: %s', usage_key_string, e)
            return JsonResponse({'error': str(e)}, status=500)

    # ── Delete ──────────────────────────────────────────────────────────────

    def _delete_xblock(self, request, usage_key_string):
        """
        Xóa XBlock và toàn bộ children.
        """
        try:
            usage_key = usage_key_with_run(usage_key_string)
        except Exception:
            return JsonResponse({'error': 'usage_key không hợp lệ'}, status=400)

        if not has_studio_write_access(request.user, usage_key.course_key):
            raise PermissionDenied()

        try:
            store = modulestore()
            store.delete_item(usage_key, request.user.id)
            return JsonResponse({'deleted': str(usage_key)})
        except Exception as e:
            log.exception('Error deleting xblock %s: %s', usage_key_string, e)
            return JsonResponse({'error': str(e)}, status=500)


class XBlockHandlerAPIView(BaseAuthoringView):
    """
    Proxy component_handler cho custom XBlocks.
    POST /landa-admin/api/authoring/xblock/{key}/handler/{handler_name}
    """

    def post(self, request, usage_key_string, handler):
        import json
        django_req = request._request
        if not hasattr(django_req, 'json'):
            django_req.json = dict(request.data) if isinstance(request.data, dict) else {}
            
        # DRF consumes the stream, causing XBlock @json_handler (which accesses request.body) to crash.
        # Fix: explicitly set _body to avoid reading from the consumed stream.
        if not hasattr(django_req, '_body'):
            django_req._body = json.dumps(request.data).encode('utf-8')

        try:
            return component_handler(django_req, usage_key_string, handler, suffix='')
        except Http404:
            raise
        except Exception as e:
            log.exception('Error in XBlockHandlerAPIView %s/%s: %s', usage_key_string, handler, e)
            return JsonResponse({'error': str(e)}, status=500)
