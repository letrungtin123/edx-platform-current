"""
urls.py — LANDA Groups URL patterns

Được include vào landa_library/urls.py (cùng prefix /api/landa/)
"""
from django.urls import path

from lms.djangoapps.landa_groups.views import (
    CourseAssignView,
    CourseRevokeView,
    CategoryAssignView,
    CategoryRevokeView,
    CourseCategoryAssignView,
    CourseCategoryRevokeView,
    GroupAuditLogView,
    MemberListAddView,
    MemberRemoveView,
    MyGroupCoursesView,
    MyRoleView,
    OrgGroupDetailView,
    OrgGroupListView,
    SubGroupDetailView,
    SubGroupListView,
    TeamListView,
    TeamDetailView,
    TeamMemberListAddView,
    TeamMemberRemoveView,
    TeamCourseAssignView,
    TeamCourseRevokeView,
    TeamCategoryAssignView,
    TeamCategoryRevokeView,
    TeamCourseCategoryAssignView,
    TeamCourseCategoryRevokeView,
)

urlpatterns = [
    # Org Groups
    path('admin/groups/', OrgGroupListView.as_view(), name='landa_groups_list'),
    path('admin/groups/<int:pk>/', OrgGroupDetailView.as_view(), name='landa_groups_detail'),

    # Sub Groups (nested dưới org group)
    path('admin/groups/<int:group_id>/subgroups/', SubGroupListView.as_view(), name='landa_subgroups_list'),

    # Sub Group detail (trực tiếp bằng sg_id)
    path('admin/subgroups/<int:pk>/', SubGroupDetailView.as_view(), name='landa_subgroup_detail'),

    # Teams (nested dưới subgroup)
    path('admin/subgroups/<int:sg_id>/teams/', TeamListView.as_view(), name='landa_teams_list'),

    # Team detail
    path('admin/teams/<int:pk>/', TeamDetailView.as_view(), name='landa_team_detail'),

    # Team Members
    path('admin/teams/<int:team_id>/members/', TeamMemberListAddView.as_view(), name='landa_team_members_list'),
    path('admin/teams/<int:team_id>/members/<int:user_id>/', TeamMemberRemoveView.as_view(), name='landa_team_member_remove'),

    # Team Course Assignments
    path('admin/teams/<int:team_id>/courses/', TeamCourseAssignView.as_view(), name='landa_team_course_assign'),
    path('admin/teams/<int:team_id>/courses/<path:course_id>/', TeamCourseRevokeView.as_view(), name='landa_team_course_revoke'),

    # Team Category Assignments (Document categories)
    path('admin/teams/<int:team_id>/categories/', TeamCategoryAssignView.as_view(), name='landa_team_category_assign'),
    path('admin/teams/<int:team_id>/categories/<int:cat_id>/', TeamCategoryRevokeView.as_view(), name='landa_team_category_revoke'),

    # Team Course Category Assignments
    path('admin/teams/<int:team_id>/course-categories/', TeamCourseCategoryAssignView.as_view(), name='landa_team_course_category_assign'),
    path('admin/teams/<int:team_id>/course-categories/<int:cat_id>/', TeamCourseCategoryRevokeView.as_view(), name='landa_team_course_category_revoke'),

    # Legacy SubGroup member/assignment endpoints (kept for migration period)
    # Members
    path('admin/subgroups/<int:sg_id>/members/', MemberListAddView.as_view(), name='landa_members_list'),
    path('admin/subgroups/<int:sg_id>/members/<int:user_id>/', MemberRemoveView.as_view(), name='landa_member_remove'),

    # Course Assignments (dùng path converter để course_id chứa dấu /)
    path('admin/subgroups/<int:sg_id>/courses/', CourseAssignView.as_view(), name='landa_course_assign'),
    path('admin/subgroups/<int:sg_id>/courses/<path:course_id>/', CourseRevokeView.as_view(), name='landa_course_revoke'),

    # Category Assignments (Document categories)
    path('admin/subgroups/<int:sg_id>/categories/', CategoryAssignView.as_view(), name='landa_category_assign'),
    path('admin/subgroups/<int:sg_id>/categories/<int:cat_id>/', CategoryRevokeView.as_view(), name='landa_category_revoke'),

    # Course Category Assignments
    path('admin/subgroups/<int:sg_id>/course-categories/', CourseCategoryAssignView.as_view(), name='landa_course_category_assign'),
    path('admin/subgroups/<int:sg_id>/course-categories/<int:cat_id>/', CourseCategoryRevokeView.as_view(), name='landa_course_category_revoke'),

    # Audit Logs
    path('admin/group-audit-logs/', GroupAuditLogView.as_view(), name='landa_group_audit_logs'),

    # Learner API
    path('v0/my-group-courses/', MyGroupCoursesView.as_view(), name='landa_my_group_courses'),
    path('v0/my-role/', MyRoleView.as_view(), name='landa_my_role'),
]
