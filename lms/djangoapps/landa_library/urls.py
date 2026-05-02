"""
urls.py — LANDA Library URL patterns

Include vào lms/urls.py:
    path('api/landa/', include('lms.djangoapps.landa_library.urls')),
"""

from django.urls import path

from lms.djangoapps.landa_library.views import (
    CategorySummaryView,
    DocumentListView,
    change_password,
    document_download,
)

urlpatterns = [
    path(
        'v1/library/documents/',
        DocumentListView.as_view(),
        name='landa_library_documents',
    ),
    path(
        'v1/library/categories/',
        CategorySummaryView.as_view(),
        name='landa_library_categories',
    ),
    path(
        'v1/library/download/<int:doc_id>/',
        document_download,
        name='landa_library_download',
    ),
    # ── Account ──
    path(
        'v1/account/change-password/',
        change_password,
        name='landa_change_password',
    ),
]
