"""
admin.py — Django Admin registration cho landa_groups models
"""
from django.contrib import admin

from lms.djangoapps.landa_groups.models import (
    GroupAuditLog,
    OrgGroup,
    SubGroup,
    SubGroupCourseAssignment,
    SubGroupMembership,
)


@admin.register(OrgGroup)
class OrgGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_by', 'created_at')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(SubGroup)
class SubGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'org_group', 'created_by', 'created_at')
    list_filter = ('org_group',)
    search_fields = ('name', 'org_group__name')
    readonly_fields = ('created_at',)


@admin.register(SubGroupMembership)
class SubGroupMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'subgroup', 'added_by', 'added_at')
    list_filter = ('subgroup__org_group',)
    search_fields = ('user__username', 'subgroup__name')
    readonly_fields = ('added_at',)


@admin.register(SubGroupCourseAssignment)
class SubGroupCourseAssignmentAdmin(admin.ModelAdmin):
    list_display = ('subgroup', 'course_id', 'assigned_by', 'assigned_at')
    list_filter = ('subgroup__org_group',)
    search_fields = ('course_id', 'subgroup__name')
    readonly_fields = ('assigned_at',)


@admin.register(GroupAuditLog)
class GroupAuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor_username', 'entity_type', 'entity_name', 'created_at')
    list_filter = ('action', 'entity_type')
    search_fields = ('actor_username', 'entity_name')
    readonly_fields = ('created_at',)
