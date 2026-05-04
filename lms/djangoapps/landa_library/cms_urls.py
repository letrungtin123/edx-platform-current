"""
cms_urls.py — CMS Studio URL patterns cho LANDA Admin

Trang quản lý nằm trên Studio UI:
  http://studio.local.openedx.io/landa-admin/

Include vào cms/urls.py:
    path('landa-admin/', include('lms.djangoapps.landa_library.cms_urls')),
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

urlpatterns = [
    # ── Trang quản lý chính ──
    path('', library_admin_page, name='landa_library_admin'),

    # ── Library API endpoints (AJAX) ──
    path('api/documents/', documents_api, name='landa_library_api_documents'),
    path('api/documents/<int:doc_id>/', document_detail_api, name='landa_library_api_document_detail'),
    path('api/documents/bulk/', document_bulk_api, name='landa_library_api_document_bulk'),
    path('api/categories/', categories_api, name='landa_library_api_categories'),
    path('api/categories/bulk/', category_bulk_api, name='landa_library_api_category_bulk'),
    path('api/categories/<int:cat_id>/', category_detail_api, name='landa_library_api_category_detail'),

    # ── Course Admin API endpoints (AJAX) ──
    path('api/courses/', courses_api, name='landa_admin_api_courses'),
    path('api/courses/<path:course_id>/', course_detail_api, name='landa_admin_api_course_detail'),
    path('api/courses-bulk/', course_bulk_api, name='landa_admin_api_course_bulk'),
]
