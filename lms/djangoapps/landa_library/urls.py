"""
urls.py — LANDA Library URL patterns

Include vào lms/urls.py:
    path('api/landa/', include('lms.djangoapps.landa_library.urls')),
"""

from django.urls import include, path

from lms.djangoapps.landa_library.views import (
    AccountStatusView,
    CategorySummaryView,
    CourseModalConfigPublicView,
    DocumentListView,
    change_password,
    document_download,
    UserBadgeView,
    UserCourseModalStateView,
    SectionModalConfigPublicView,
    UserSectionModalShownView,
    StudyTimeSyncView,
    StudyTimeWeeklyView,
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
    AdminCourseModalConfigView,
    AdminCourseNotificationView,
    AdminUsersView,
    AdminUserDetailView,
    AdminAuditLogsView,
    TestNotsView,
    AdminSectionModalConfigView,
    CourseCategoryListView,
    CourseCategoryDetailView,
    CourseCategoryCoursesView,
    CourseCategoryCourseRemoveView,
)
from lms.djangoapps.landa_library.report_api import (
    ReportSummaryView,
    LearnerDetailView,
    MyCourseProgressView,
    ReportChartTrendView,
    TopCoursesView,
    UncompletedLearnersView,
    AdminUserBadgesView,
    AdminUserStudyTimeView,
)
from lms.djangoapps.landa_library.help_docs_api import (
    HelpFoldersView,
    HelpFolderDetailView,
    HelpFolderReorderView,
    HelpPagesView,
    HelpPageDetailView,
    HelpPageReorderView,
    HelpImageUploadView,
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
    path(
        'v1/course-modal-config/',
        CourseModalConfigPublicView.as_view(),
        name='landa_course_modal_config',
    ),
    path(
        'v1/user-badges/',
        UserBadgeView.as_view(),
        name='landa_user_badges',
    ),
    path(
        'v1/course-modal-state/',
        UserCourseModalStateView.as_view(),
        name='landa_course_modal_state',
    ),
    path(
        'v1/section-modal-config/',
        SectionModalConfigPublicView.as_view(),
        name='landa_section_modal_config',
    ),
    path(
        'v1/section-modal-shown/',
        UserSectionModalShownView.as_view(),
        name='landa_section_modal_shown',
    ),
    # ── Study Time ──
    path(
        'v1/study-time/sync/',
        StudyTimeSyncView.as_view(),
        name='landa_study_time_sync',
    ),
    path(
        'v1/study-time/weekly/',
        StudyTimeWeeklyView.as_view(),
        name='landa_study_time_weekly',
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
    path('admin/courses-bulk/', AdminCourseBulkView.as_view(), name='landa_admin_course_bulk'),
    path('admin/courses/<path:course_id>/modal-config/', AdminCourseModalConfigView.as_view(), name='landa_admin_course_modal_config'),
    path('admin/courses/<path:course_id>/send-notification/', AdminCourseNotificationView.as_view(), name='landa_admin_course_send_notification'),
    path('admin/courses/<path:course_id>/section-modal-config/', AdminSectionModalConfigView.as_view(), name='landa_admin_section_modal_config'),
    path('admin/courses/<path:course_id>/', AdminCourseDetailView.as_view(), name='landa_admin_course_detail'),
    path('admin/users/', AdminUsersView.as_view(), name='landa_admin_users'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='landa_admin_user_detail'),
    path('admin/report-summary/', ReportSummaryView.as_view(), name='landa_admin_report_summary'),
    path('admin/report-chart/', ReportChartTrendView.as_view(), name='landa_admin_report_chart'),
    path('admin/report-top-courses/', TopCoursesView.as_view(), name='landa_admin_report_top_courses'),
    path('admin/report-uncompleted-learners/', UncompletedLearnersView.as_view(), name='landa_admin_report_uncompleted_learners'),
    path('admin/learner-detail/', LearnerDetailView.as_view(), name='landa_admin_learner_detail'),
    path('admin/audit-logs/', AdminAuditLogsView.as_view(), name='landa_admin_audit_logs'),
    path('admin/user-badges/', AdminUserBadgesView.as_view(), name='landa_admin_user_badges'),
    path('admin/user-study-time/', AdminUserStudyTimeView.as_view(), name='landa_admin_user_study_time'),
    path('v1/public/test-nots/', TestNotsView.as_view(), name='test_nots'),

    # ── Help Docs API (superuser write, staff read) ──
    path('admin/help-folders/', HelpFoldersView.as_view(), name='landa_help_folders'),
    path('admin/help-folders/reorder/', HelpFolderReorderView.as_view(), name='landa_help_folders_reorder'),
    path('admin/help-folders/<int:folder_id>/', HelpFolderDetailView.as_view(), name='landa_help_folder_detail'),
    path('admin/help-pages/', HelpPagesView.as_view(), name='landa_help_pages'),
    path('admin/help-pages/reorder/', HelpPageReorderView.as_view(), name='landa_help_pages_reorder'),
    path('admin/help-pages/upload-image/', HelpImageUploadView.as_view(), name='landa_help_image_upload'),
    path('admin/help-pages/<int:page_id>/', HelpPageDetailView.as_view(), name='landa_help_page_detail'),

    # ── Course Categories API ──
    path('admin/course-categories/', CourseCategoryListView.as_view(), name='landa_admin_course_categories'),
    path('admin/course-categories/<int:pk>/', CourseCategoryDetailView.as_view(), name='landa_admin_course_category_detail'),
    path('admin/course-categories/<int:pk>/courses/', CourseCategoryCoursesView.as_view(), name='landa_admin_course_category_courses'),
    path('admin/course-categories/<int:pk>/courses/<path:course_id>/', CourseCategoryCourseRemoveView.as_view(), name='landa_admin_course_category_course_remove'),

    # ── Group Management (landa_groups app) ──
    path('', include('lms.djangoapps.landa_groups.urls')),
]

