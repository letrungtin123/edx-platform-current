"""
urls.py — LANDA Library URL patterns

Include vào lms/urls.py:
    path('api/landa/', include('lms.djangoapps.landa_library.urls')),
"""

from django.urls import path

from lms.djangoapps.landa_library.views import (
    AccountStatusView,
    CategorySummaryView,
    DocumentListView,
    change_password,
    document_download,
)
from lms.djangoapps.landa_library.admin_api import (
    AdminDocumentsView,
    AdminDocumentDetailView,
    AdminDocumentBulkView,
    AdminCategoriesView,
    AdminCategoryDetailView,
    AdminCategoryBulkView,
    AdminCoursesView,
    AdminCourseDetailView,
    AdminCourseBulkView,
    AdminUsersView,
    AdminUserDetailView,
    AdminAuditLogsView,
)
from lms.djangoapps.landa_library.report_api import (
    ReportSummaryView,
    LearnerDetailView,
    MyCourseProgressView,
    ReportChartTrendView,
    TopCoursesView,
    UncompletedLearnersView,
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
    path(
        'v1/my-progress/',
        MyCourseProgressView.as_view(),
        name='landa_my_progress',
    ),
    path(
        'v1/account/status/',
        AccountStatusView.as_view(),
        name='landa_account_status',
    ),

    # ══════════════════════════════════════════
    # Admin API — dùng cho frontend-shell
    # Auth: Bearer token (OAuth2) + IsStaffUser
    # ══════════════════════════════════════════
    path('admin/documents/', AdminDocumentsView.as_view(), name='landa_admin_documents'),
    path('admin/documents/<int:doc_id>/', AdminDocumentDetailView.as_view(), name='landa_admin_document_detail'),
    path('admin/documents/bulk/', AdminDocumentBulkView.as_view(), name='landa_admin_document_bulk'),
    path('admin/categories/', AdminCategoriesView.as_view(), name='landa_admin_categories'),
    path('admin/categories/<int:cat_id>/', AdminCategoryDetailView.as_view(), name='landa_admin_category_detail'),
    path('admin/categories/bulk/', AdminCategoryBulkView.as_view(), name='landa_admin_category_bulk'),
    path('admin/courses/', AdminCoursesView.as_view(), name='landa_admin_courses'),
    path('admin/courses/<path:course_id>/', AdminCourseDetailView.as_view(), name='landa_admin_course_detail'),
    path('admin/courses-bulk/', AdminCourseBulkView.as_view(), name='landa_admin_course_bulk'),
    path('admin/users/', AdminUsersView.as_view(), name='landa_admin_users'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='landa_admin_user_detail'),
    path('admin/report-summary/', ReportSummaryView.as_view(), name='landa_admin_report_summary'),
    path('admin/report-chart/', ReportChartTrendView.as_view(), name='landa_admin_report_chart'),
    path('admin/report-top-courses/', TopCoursesView.as_view(), name='landa_admin_report_top_courses'),
    path('admin/report-uncompleted-learners/', UncompletedLearnersView.as_view(), name='landa_admin_report_uncompleted_learners'),
    path('admin/learner-detail/', LearnerDetailView.as_view(), name='landa_admin_learner_detail'),
    path('admin/audit-logs/', AdminAuditLogsView.as_view(), name='landa_admin_audit_logs'),
]
