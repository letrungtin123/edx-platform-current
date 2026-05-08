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
    GroupAuditLogView,
    MemberListAddView,
    MemberRemoveView,
    MyGroupCoursesView,
    OrgGroupDetailView,
    OrgGroupListView,
    SubGroupDetailView,
    SubGroupListView,
)

urlpatterns = [
    # Org Groups
    path('admin/groups/', OrgGroupListView.as_view(), name='landa_groups_list'),
    path('admin/groups/<int:pk>/', OrgGroupDetailView.as_view(), name='landa_groups_detail'),

    # Sub Groups (nested dưới org group)
    path('admin/groups/<int:group_id>/subgroups/', SubGroupListView.as_view(), name='landa_subgroups_list'),

    # Sub Group detail (trực tiếp bằng sg_id)
    path('admin/subgroups/<int:pk>/', SubGroupDetailView.as_view(), name='landa_subgroup_detail'),

    # Members
    path('admin/subgroups/<int:sg_id>/members/', MemberListAddView.as_view(), name='landa_members_list'),
    path('admin/subgroups/<int:sg_id>/members/<int:user_id>/', MemberRemoveView.as_view(), name='landa_member_remove'),

    # Course Assignments (dùng path converter để course_id chứa dấu /)
    path('admin/subgroups/<int:sg_id>/courses/', CourseAssignView.as_view(), name='landa_course_assign'),
    path('admin/subgroups/<int:sg_id>/courses/<path:course_id>/', CourseRevokeView.as_view(), name='landa_course_revoke'),

    # Category Assignments
    path('admin/subgroups/<int:sg_id>/categories/', CategoryAssignView.as_view(), name='landa_category_assign'),
    path('admin/subgroups/<int:sg_id>/categories/<int:cat_id>/', CategoryRevokeView.as_view(), name='landa_category_revoke'),

    # Audit Logs
    path('admin/group-audit-logs/', GroupAuditLogView.as_view(), name='landa_group_audit_logs'),

    # Learner API
    path('v0/my-group-courses/', MyGroupCoursesView.as_view(), name='landa_my_group_courses'),
]
