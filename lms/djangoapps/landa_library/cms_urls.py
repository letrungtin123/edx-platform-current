"""
cms_urls.py — CMS Studio URL patterns cho LANDA Admin
"""
from django.urls import path

from lms.djangoapps.landa_library.cms_views import (
    library_admin_page,
    documents_api,
    document_detail_api,
    document_bulk_api,
    categories_api,
    category_detail_api,
    category_bulk_api,
    courses_api,
    course_detail_api,
    course_bulk_api,
)

from lms.djangoapps.landa_library.authoring_api import (
    CourseAPIView,
    XBlockCRUDAPIView,
    XBlockHandlerAPIView,
    AssetAPIView,
)

urlpatterns = [
    # ── Trang quản lý chính ──
    path('', library_admin_page, name='landa_library_admin'),

    # ── Library API ──
    path('api/documents/', documents_api, name='landa_library_api_documents'),
    path('api/documents/<int:doc_id>/', document_detail_api, name='landa_library_api_document_detail'),
    path('api/documents/bulk/', document_bulk_api, name='landa_library_api_document_bulk'),
    path('api/categories/', categories_api, name='landa_library_api_categories'),
    path('api/categories/bulk/', category_bulk_api, name='landa_library_api_category_bulk'),
    path('api/categories/<int:cat_id>/', category_detail_api, name='landa_library_api_category_detail'),

    # ── Course Admin API ──
    path('api/courses/', courses_api, name='landa_admin_api_courses'),
    path('api/courses/<path:course_id>/', course_detail_api, name='landa_admin_api_course_detail'),
    path('api/courses-bulk/', course_bulk_api, name='landa_admin_api_course_bulk'),

    # ── JWT Authoring: Course ──
    path('api/authoring/courses/', CourseAPIView.as_view(), name='landa_authoring_courses'),

    # ── JWT Authoring: Assets ──
    path('api/authoring/assets/<path:course_key_string>/', AssetAPIView.as_view(), name='landa_authoring_assets'),
    path('api/authoring/assets/<path:course_key_string>/<path:asset_key_string>', AssetAPIView.as_view(), name='landa_authoring_assets_detail'),

    # ── JWT Authoring: Custom XBlock handlers ──
    path(
        'api/authoring/xblock/<path:usage_key_string>/handler/<str:handler>',
        XBlockHandlerAPIView.as_view(),
        name='landa_authoring_xblock_handler',
    ),

    # ── JWT Authoring: XBlock CRUD ──
    # POST (no key) = create, POST (with key) = update, DELETE (with key) = delete
    path('api/authoring/xblock/', XBlockCRUDAPIView.as_view(), name='landa_authoring_xblock_create'),
    path('api/authoring/xblock/<path:usage_key_string>', XBlockCRUDAPIView.as_view(), name='landa_authoring_xblock_detail'),
]
