"""
views.py — LANDA Groups API Views

10 endpoints cho group management.
Pattern giống landa_library/admin_api.py
"""
import logging

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import Count, Q
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from lms.djangoapps.landa_groups.audit import log_group_action
from lms.djangoapps.landa_groups.models import (
    GroupAuditLog,
    LandaUserRole,
    OrgGroup,
    SubGroup,
    SubGroupCourseAssignment,
    SubGroupMembership,
    SubGroupCategoryAssignment,
    SubGroupCourseCategoryAssignment,
    Team,
    TeamMembership,
    TeamCourseAssignment,
    TeamCategoryAssignment,
    TeamCourseCategoryAssignment,
)
from lms.djangoapps.landa_library.models import DocumentCategory, CourseCategory, CourseCategoryMembership

log = logging.getLogger(__name__)

# ── Auth classes dùng chung ──
ADMIN_AUTH_CLASSES = [
    JwtAuthentication,
    BearerAuthenticationAllowInactiveUser,
    SessionAuthenticationAllowInactiveUser,
]


class IsStaffUser(permissions.BasePermission):
    """Chỉ staff/superuser mới được dùng admin endpoints."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)


# ══════════════════════════════════════════════
# Org Group API
# ══════════════════════════════════════════════

class OrgGroupListView(APIView):
    """
    GET  /api/landa/admin/groups/  — List tất cả org groups (có search + pagination)
    POST /api/landa/admin/groups/  — Tạo org group mới
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        qs = OrgGroup.objects.annotate(subgroup_count=Count('subgroups')).order_by('name')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)

        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(int(request.query_params.get('page_size', 50)), 100)
        total = qs.count()
        items = qs[(page - 1) * page_size: page * page_size]

        data = [{
            'id': g.id,
            'name': g.name,
            'description': g.description,
            'subgroup_count': g.subgroup_count,
            'created_at': g.created_at.isoformat(),
        } for g in items]

        return Response({'groups': data, 'total': total, 'page': page, 'page_size': page_size})

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
        if OrgGroup.objects.filter(name=name).exists():
            return Response({'error': f'"{name}" đã tồn tại'}, status=status.HTTP_400_BAD_REQUEST)

        group = OrgGroup.objects.create(
            name=name,
            description=request.data.get('description', '').strip(),
            created_by=request.user,
        )
        log_group_action(request, GroupAuditLog.ACTION_CREATE_GROUP, 'OrgGroup', name, entity_id=str(group.id))
        return Response({'id': group.id, 'name': group.name}, status=status.HTTP_201_CREATED)


class OrgGroupDetailView(APIView):
    """
    GET    /api/landa/admin/groups/<id>/  — Chi tiết group cha
    PATCH  /api/landa/admin/groups/<id>/  — Cập nhật tên/mô tả
    DELETE /api/landa/admin/groups/<id>/  — Xóa (cascade xóa subgroups + assignments)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_or_404(self, pk):
        try:
            return OrgGroup.objects.get(id=pk)
        except OrgGroup.DoesNotExist:
            return None

    def get(self, request, pk):
        group = self._get_or_404(pk)
        if not group:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'created_at': group.created_at.isoformat(),
            'updated_at': group.updated_at.isoformat(),
        })

    def patch(self, request, pk):
        group = self._get_or_404(pk)
        if not group:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        changed = False
        if 'name' in request.data:
            name = request.data['name'].strip()
            if not name:
                return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
            if OrgGroup.objects.filter(name=name).exclude(id=pk).exists():
                return Response({'error': f'"{name}" đã tồn tại'}, status=status.HTTP_400_BAD_REQUEST)
            group.name = name
            changed = True
        if 'description' in request.data:
            group.description = request.data['description'].strip()
            changed = True
        if changed:
            group.save()
            log_group_action(request, GroupAuditLog.ACTION_UPDATE_GROUP, 'OrgGroup', group.name, entity_id=str(group.id))
        return Response({'success': True})

    def delete(self, request, pk):
        group = self._get_or_404(pk)
        if not group:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        group_name = group.name
        group.delete()  # cascade xóa SubGroup → SubGroupMembership + SubGroupCourseAssignment
        log_group_action(request, GroupAuditLog.ACTION_DELETE_GROUP, 'OrgGroup', group_name, entity_id=str(pk))
        return Response({'success': True})


# ══════════════════════════════════════════════
# Sub Group API
# ══════════════════════════════════════════════

class SubGroupListView(APIView):
    """
    GET  /api/landa/admin/groups/<group_id>/subgroups/  — List sub groups của org group
    POST /api/landa/admin/groups/<group_id>/subgroups/  — Tạo sub group mới
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, group_id):
        if not OrgGroup.objects.filter(id=group_id).exists():
            return Response({'error': 'Org Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        qs = SubGroup.objects.filter(org_group_id=group_id).annotate(
            team_count=Count('teams', distinct=True),
        ).order_by('name')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)

        data = [{
            'id': sg.id,
            'name': sg.name,
            'org_group_id': group_id,
            'team_count': sg.team_count,
            'created_at': sg.created_at.isoformat(),
        } for sg in qs]

        return Response({'subgroups': data, 'total': len(data)})

    def post(self, request, group_id):
        try:
            org_group = OrgGroup.objects.get(id=group_id)
        except OrgGroup.DoesNotExist:
            return Response({'error': 'Org Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
        if SubGroup.objects.filter(org_group=org_group, name=name).exists():
            return Response({'error': f'"{name}" đã tồn tại trong group này'}, status=status.HTTP_400_BAD_REQUEST)

        sg = SubGroup.objects.create(org_group=org_group, name=name, created_by=request.user)
        log_group_action(
            request, GroupAuditLog.ACTION_CREATE_SUBGROUP, 'SubGroup', name,
            entity_id=str(sg.id), detail=f'org_group={org_group.name}',
        )
        return Response({'id': sg.id, 'name': sg.name}, status=status.HTTP_201_CREATED)


class SubGroupDetailView(APIView):
    """
    GET    /api/landa/admin/subgroups/<id>/  — Chi tiết + members + courses
    PATCH  /api/landa/admin/subgroups/<id>/  — Đổi tên
    DELETE /api/landa/admin/subgroups/<id>/  — Xóa
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_or_404(self, pk):
        try:
            return SubGroup.objects.select_related('org_group').get(id=pk)
        except SubGroup.DoesNotExist:
            return None

    def get(self, request, pk):
        sg = self._get_or_404(pk)
        if not sg:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        # SubGroup giờ chỉ là container — trả danh sách Teams
        teams = Team.objects.filter(subgroup=sg).annotate(
            member_count=Count('memberships', distinct=True),
            course_count=Count('course_assignments', distinct=True),
            course_category_count=Count('course_category_assignments', distinct=True),
        ).order_by('name')

        teams_data = [{
            'id': t.id,
            'name': t.name,
            'subgroup_id': sg.id,
            'member_count': t.member_count,
            'course_count': t.course_count,
            'course_category_count': t.course_category_count,
            'created_at': t.created_at.isoformat(),
        } for t in teams]

        return Response({
            'id': sg.id,
            'name': sg.name,
            'org_group_id': sg.org_group_id,
            'org_group_name': sg.org_group.name,
            'team_count': len(teams_data),
            'teams': teams_data,
            'created_at': sg.created_at.isoformat(),
        })

    def patch(self, request, pk):
        sg = self._get_or_404(pk)
        if not sg:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
        if SubGroup.objects.filter(org_group=sg.org_group, name=name).exclude(id=pk).exists():
            return Response({'error': f'"{name}" đã tồn tại trong group này'}, status=status.HTTP_400_BAD_REQUEST)
        sg.name = name
        sg.save()
        log_group_action(request, GroupAuditLog.ACTION_UPDATE_SUBGROUP, 'SubGroup', name, entity_id=str(pk))
        return Response({'success': True})

    def delete(self, request, pk):
        sg = self._get_or_404(pk)
        if not sg:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        sg_name = sg.name
        sg.delete()  # cascade xóa memberships + course_assignments
        log_group_action(request, GroupAuditLog.ACTION_DELETE_SUBGROUP, 'SubGroup', sg_name, entity_id=str(pk))
        return Response({'success': True})


# ══════════════════════════════════════════════
# Members API
# ══════════════════════════════════════════════

class MemberListAddView(APIView):
    """
    GET  /api/landa/admin/subgroups/<sg_id>/members/  — List members
    POST /api/landa/admin/subgroups/<sg_id>/members/  — Add members (bulk)

    POST body: { "user_ids": [1, 2, 3] }
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_sg_or_404(self, sg_id):
        try:
            return SubGroup.objects.get(id=sg_id)
        except SubGroup.DoesNotExist:
            return None

    def get(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        memberships = SubGroupMembership.objects.filter(subgroup=sg).select_related('user').order_by('added_at')
        data = [{
            'id': m.user.id,
            'username': m.user.username,
            'email': m.user.email,
            'added_at': m.added_at.isoformat(),
        } for m in memberships]
        return Response({'members': data, 'total': len(data)})

    def post(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        user_ids = request.data.get('user_ids', [])
        if not user_ids or not isinstance(user_ids, list):
            return Response({'error': 'user_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        users = User.objects.filter(id__in=user_ids)
        if not users.exists():
            return Response({'error': 'Không tìm thấy users'}, status=status.HTTP_404_NOT_FOUND)

        added = 0
        skipped = 0
        for user in users:
            membership, created = SubGroupMembership.objects.get_or_create(
                subgroup=sg, user=user,
                defaults={'added_by': request.user},
            )
            if created:
                added += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ADD_MEMBER, 'Membership',
                    user.username, entity_id=str(membership.id),
                    detail=f'subgroup={sg.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'added': added, 'skipped': skipped})


class MemberRemoveView(APIView):
    """
    DELETE /api/landa/admin/subgroups/<sg_id>/members/<user_id>/  — Remove member

    KHÔNG unenroll user khỏi course.
    User sẽ không thấy course qua /my-group-courses/ nữa (vì mất membership).
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, sg_id, user_id):
        try:
            membership = SubGroupMembership.objects.select_related('user', 'subgroup').get(
                subgroup_id=sg_id, user_id=user_id,
            )
        except SubGroupMembership.DoesNotExist:
            return Response({'error': 'User không thuộc sub group này'}, status=status.HTTP_404_NOT_FOUND)

        username = membership.user.username
        sg_name = membership.subgroup.name
        membership.delete()

        log_group_action(
            request, GroupAuditLog.ACTION_REMOVE_MEMBER, 'Membership',
            username, entity_id=str(user_id),
            detail=f'subgroup={sg_name}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Course Assignment API
# ══════════════════════════════════════════════

class CourseAssignView(APIView):
    """
    GET  /api/landa/admin/subgroups/<sg_id>/courses/  — List courses đã phân
    POST /api/landa/admin/subgroups/<sg_id>/courses/  — Phân courses cho subgroup (bulk)

    POST body: { "course_ids": ["course-v1:...", "course-v1:..."] }
    Không phải enroll — chỉ tạo visibility record.
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_sg_or_404(self, sg_id):
        try:
            return SubGroup.objects.get(id=sg_id)
        except SubGroup.DoesNotExist:
            return None

    def get(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = SubGroupCourseAssignment.objects.filter(subgroup=sg).order_by('assigned_at')
        course_ids = [a.course_id for a in assignments]

        course_name_map = {}
        if course_ids:
            overviews = CourseOverview.objects.filter(id__in=course_ids).values('id', 'display_name')
            course_name_map = {str(o['id']): o['display_name'] for o in overviews}

        data = [{
            'course_id': a.course_id,
            'display_name': course_name_map.get(a.course_id, a.course_id),
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]

        return Response({'courses': data, 'total': len(data)})

    def post(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        course_ids = request.data.get('course_ids', [])
        if not course_ids or not isinstance(course_ids, list):
            return Response({'error': 'course_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate tồn tại trong CourseOverview
        valid_ids = set(
            str(cid) for cid in CourseOverview.objects.filter(id__in=course_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in course_ids if cid not in valid_ids]
        if invalid:
            return Response(
                {'error': f'Course không tồn tại: {", ".join(invalid)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assigned = 0
        skipped = 0
        for course_id in course_ids:
            assignment, created = SubGroupCourseAssignment.objects.get_or_create(
                subgroup=sg, course_id=course_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_COURSE, 'CourseAssignment',
                    course_id, entity_id=str(assignment.id),
                    detail=f'subgroup={sg.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class CourseRevokeView(APIView):
    """
    DELETE /api/landa/admin/subgroups/<sg_id>/courses/<course_id>/  — Revoke course

    Xóa visibility record. Không unenroll user.
    course_id được encode trong URL (path converter).
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, sg_id, course_id):
        try:
            assignment = SubGroupCourseAssignment.objects.get(subgroup_id=sg_id, course_id=course_id)
        except SubGroupCourseAssignment.DoesNotExist:
            return Response({'error': 'Course chưa được phân cho sub group này'}, status=status.HTTP_404_NOT_FOUND)

        sg_name = assignment.subgroup.name if hasattr(assignment, '_subgroup_cache') else SubGroup.objects.get(id=sg_id).name
        assignment.delete()

        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_COURSE, 'CourseAssignment',
            course_id, entity_id=course_id,
            detail=f'subgroup_id={sg_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Category Assignment API
# ══════════════════════════════════════════════

class CategoryAssignView(APIView):
    """
    GET  /api/landa/admin/subgroups/<sg_id>/categories/  — List categories đã phân
    POST /api/landa/admin/subgroups/<sg_id>/categories/  — Phân categories cho subgroup (bulk)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_sg_or_404(self, sg_id):
        try:
            return SubGroup.objects.get(id=sg_id)
        except SubGroup.DoesNotExist:
            return None

    def get(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = SubGroupCategoryAssignment.objects.filter(subgroup=sg).select_related('category').order_by('assigned_at')
        data = [{
            'category_id': a.category_id,
            'name': a.category.name,
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]
        return Response({'categories': data, 'total': len(data)})

    def post(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        category_ids = request.data.get('category_ids', [])
        if not category_ids or not isinstance(category_ids, list):
            return Response({'error': 'category_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        valid_ids = set(
            DocumentCategory.objects.filter(id__in=category_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in category_ids if cid not in valid_ids]
        if invalid:
            return Response({'error': f'Category không tồn tại: {", ".join(map(str, invalid))}'}, status=status.HTTP_400_BAD_REQUEST)

        assigned = 0
        skipped = 0
        for category_id in category_ids:
            assignment, created = SubGroupCategoryAssignment.objects.get_or_create(
                subgroup=sg, category_id=category_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_CATEGORY, 'CategoryAssignment',
                    str(category_id), entity_id=str(assignment.id),
                    detail=f'subgroup={sg.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class CategoryRevokeView(APIView):
    """
    DELETE /api/landa/admin/subgroups/<sg_id>/categories/<cat_id>/  — Revoke category
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, sg_id, cat_id):
        try:
            assignment = SubGroupCategoryAssignment.objects.get(subgroup_id=sg_id, category_id=cat_id)
        except SubGroupCategoryAssignment.DoesNotExist:
            return Response({'error': 'Category chưa được phân cho sub group này'}, status=status.HTTP_404_NOT_FOUND)

        sg_name = assignment.subgroup.name if hasattr(assignment, '_subgroup_cache') else SubGroup.objects.get(id=sg_id).name
        assignment.delete()

        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_CATEGORY, 'CategoryAssignment',
            str(cat_id), entity_id=str(cat_id),
            detail=f'subgroup_id={sg_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Course Category Assignment API
# ══════════════════════════════════════════════

class CourseCategoryAssignView(APIView):
    """
    GET  /api/landa/admin/subgroups/<sg_id>/course-categories/  — List course categories đã phân
    POST /api/landa/admin/subgroups/<sg_id>/course-categories/  — Phân course categories cho subgroup (bulk)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_sg_or_404(self, sg_id):
        try:
            return SubGroup.objects.get(id=sg_id)
        except SubGroup.DoesNotExist:
            return None

    def get(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = SubGroupCourseCategoryAssignment.objects.filter(
            subgroup=sg
        ).select_related('category').order_by('assigned_at')
        data = [{
            'category_id': a.category_id,
            'name': a.category.name,
            'slug': a.category.slug,
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]
        return Response({'course_categories': data, 'total': len(data)})

    def post(self, request, sg_id):
        sg = self._get_sg_or_404(sg_id)
        if not sg:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        category_ids = request.data.get('category_ids', [])
        if not category_ids or not isinstance(category_ids, list):
            return Response({'error': 'category_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        valid_ids = set(
            CourseCategory.objects.filter(id__in=category_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in category_ids if cid not in valid_ids]
        if invalid:
            return Response(
                {'error': f'Course Category không tồn tại: {", ".join(map(str, invalid))}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assigned = 0
        skipped = 0
        for category_id in category_ids:
            assignment, created = SubGroupCourseCategoryAssignment.objects.get_or_create(
                subgroup=sg, category_id=category_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_COURSE_CATEGORY,
                    'CourseCategoryAssignment',
                    str(category_id), entity_id=str(assignment.id),
                    detail=f'subgroup={sg.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class CourseCategoryRevokeView(APIView):
    """
    DELETE /api/landa/admin/subgroups/<sg_id>/course-categories/<cat_id>/  — Revoke course category
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, sg_id, cat_id):
        try:
            assignment = SubGroupCourseCategoryAssignment.objects.get(
                subgroup_id=sg_id, category_id=cat_id,
            )
        except SubGroupCourseCategoryAssignment.DoesNotExist:
            return Response(
                {'error': 'Course Category chưa được phân cho sub group này'},
                status=status.HTTP_404_NOT_FOUND,
            )

        assignment.delete()
        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_COURSE_CATEGORY,
            'CourseCategoryAssignment',
            str(cat_id), entity_id=str(cat_id),
            detail=f'subgroup_id={sg_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Team API
# ══════════════════════════════════════════════

class TeamListView(APIView):
    """
    GET  /api/landa/admin/subgroups/<sg_id>/teams/  — List teams của subgroup
    POST /api/landa/admin/subgroups/<sg_id>/teams/  — Tạo team mới
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, sg_id):
        if not SubGroup.objects.filter(id=sg_id).exists():
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        qs = Team.objects.filter(subgroup_id=sg_id).annotate(
            member_count=Count('memberships', distinct=True),
            course_count=Count('course_assignments', distinct=True),
            course_category_count=Count('course_category_assignments', distinct=True),
        ).order_by('name')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)

        data = [{
            'id': t.id,
            'name': t.name,
            'subgroup_id': sg_id,
            'member_count': t.member_count,
            'course_count': t.course_count,
            'course_category_count': t.course_category_count,
            'created_at': t.created_at.isoformat(),
        } for t in qs]

        return Response({'teams': data, 'total': len(data)})

    def post(self, request, sg_id):
        try:
            subgroup = SubGroup.objects.get(id=sg_id)
        except SubGroup.DoesNotExist:
            return Response({'error': 'Sub Group không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
        if Team.objects.filter(subgroup=subgroup, name=name).exists():
            return Response({'error': f'"{name}" đã tồn tại trong nhóm này'}, status=status.HTTP_400_BAD_REQUEST)

        team = Team.objects.create(subgroup=subgroup, name=name, created_by=request.user)
        log_group_action(
            request, GroupAuditLog.ACTION_CREATE_TEAM, 'Team', name,
            entity_id=str(team.id), detail=f'subgroup={subgroup.name}',
        )
        return Response({'id': team.id, 'name': team.name}, status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    """
    GET    /api/landa/admin/teams/<id>/  — Chi tiết + members + courses + categories
    PATCH  /api/landa/admin/teams/<id>/  — Đổi tên
    DELETE /api/landa/admin/teams/<id>/  — Xóa
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def _get_or_404(self, pk):
        try:
            return Team.objects.select_related('subgroup', 'subgroup__org_group').get(id=pk)
        except Team.DoesNotExist:
            return None

    def get(self, request, pk):
        team = self._get_or_404(pk)
        if not team:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        memberships = TeamMembership.objects.filter(team=team).select_related('user').order_by('added_at')
        assignments = TeamCourseAssignment.objects.filter(team=team).order_by('assigned_at')

        # Lấy display_name cho từng course từ CourseOverview
        course_ids = [a.course_id for a in assignments]
        course_name_map = {}
        if course_ids:
            overviews = CourseOverview.objects.filter(id__in=course_ids).values('id', 'display_name')
            course_name_map = {str(o['id']): o['display_name'] for o in overviews}

        from openedx.core.djangoapps.user_api.accounts.image_helpers import get_profile_image_urls_for_user
        from common.djangoapps.student.models import UserProfile

        member_user_ids = [m.user.id for m in memberships]
        profile_has_image = set(
            UserProfile.objects.filter(
                user_id__in=member_user_ids,
                profile_image_uploaded_at__isnull=False,
            ).values_list('user_id', flat=True)
        )

        members = []
        for m in memberships:
            avatar = ''
            if m.user.id in profile_has_image:
                try:
                    avatar_urls = get_profile_image_urls_for_user(m.user)
                    avatar = avatar_urls.get('small', '')
                except Exception:
                    pass
            members.append({
                'id': m.user.id,
                'username': m.user.username,
                'email': m.user.email,
                'avatar': avatar,
                'added_at': m.added_at.isoformat(),
            })

        courses = [{
            'course_id': a.course_id,
            'display_name': course_name_map.get(a.course_id, a.course_id),
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]

        categories = TeamCategoryAssignment.objects.filter(team=team).select_related('category').order_by('assigned_at')
        categories_data = [{
            'category_id': c.category_id,
            'name': c.category.name,
            'assigned_at': c.assigned_at.isoformat(),
        } for c in categories]

        # Course categories
        course_cat_assignments = TeamCourseCategoryAssignment.objects.filter(
            team=team
        ).select_related('category').order_by('assigned_at')
        course_categories_data = [{
            'category_id': cc.category_id,
            'name': cc.category.name,
            'slug': cc.category.slug,
            'assigned_at': cc.assigned_at.isoformat(),
        } for cc in course_cat_assignments]

        return Response({
            'id': team.id,
            'name': team.name,
            'subgroup_id': team.subgroup_id,
            'subgroup_name': team.subgroup.name,
            'org_group_id': team.subgroup.org_group_id,
            'org_group_name': team.subgroup.org_group.name,
            'member_count': len(members),
            'course_count': len(courses),
            'category_count': len(categories_data),
            'course_category_count': len(course_categories_data),
            'members': members,
            'courses': courses,
            'categories': categories_data,
            'course_categories': course_categories_data,
            'created_at': team.created_at.isoformat(),
        })

    def patch(self, request, pk):
        team = self._get_or_404(pk)
        if not team:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Tên không được để trống'}, status=status.HTTP_400_BAD_REQUEST)
        if Team.objects.filter(subgroup=team.subgroup, name=name).exclude(id=pk).exists():
            return Response({'error': f'"{name}" đã tồn tại trong nhóm này'}, status=status.HTTP_400_BAD_REQUEST)
        team.name = name
        team.save()
        log_group_action(request, GroupAuditLog.ACTION_UPDATE_TEAM, 'Team', name, entity_id=str(pk))
        return Response({'success': True})

    def delete(self, request, pk):
        team = self._get_or_404(pk)
        if not team:
            return Response({'error': 'Không tìm thấy'}, status=status.HTTP_404_NOT_FOUND)
        team_name = team.name
        team.delete()  # cascade xóa memberships + assignments
        log_group_action(request, GroupAuditLog.ACTION_DELETE_TEAM, 'Team', team_name, entity_id=str(pk))
        return Response({'success': True})


# ══════════════════════════════════════════════
# Team Members API
# ══════════════════════════════════════════════

class TeamMemberListAddView(APIView):
    """
    GET  /api/landa/admin/teams/<team_id>/members/  — List members
    POST /api/landa/admin/teams/<team_id>/members/  — Add members (bulk)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        memberships = TeamMembership.objects.filter(team=team).select_related('user').order_by('added_at')
        data = [{
            'id': m.user.id,
            'username': m.user.username,
            'email': m.user.email,
            'added_at': m.added_at.isoformat(),
        } for m in memberships]
        return Response({'members': data, 'total': len(data)})

    def post(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        user_ids = request.data.get('user_ids', [])
        if not user_ids or not isinstance(user_ids, list):
            return Response({'error': 'user_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        users = User.objects.filter(id__in=user_ids)
        if not users.exists():
            return Response({'error': 'Không tìm thấy users'}, status=status.HTTP_404_NOT_FOUND)

        added = 0
        skipped = 0
        for user in users:
            membership, created = TeamMembership.objects.get_or_create(
                team=team, user=user,
                defaults={'added_by': request.user},
            )
            if created:
                added += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ADD_MEMBER, 'Membership',
                    user.username, entity_id=str(membership.id),
                    detail=f'team={team.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'added': added, 'skipped': skipped})


class TeamMemberRemoveView(APIView):
    """
    DELETE /api/landa/admin/teams/<team_id>/members/<user_id>/  — Remove member
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, team_id, user_id):
        try:
            membership = TeamMembership.objects.select_related('user', 'team').get(
                team_id=team_id, user_id=user_id,
            )
        except TeamMembership.DoesNotExist:
            return Response({'error': 'User không thuộc team này'}, status=status.HTTP_404_NOT_FOUND)

        username = membership.user.username
        team_name = membership.team.name
        membership.delete()

        log_group_action(
            request, GroupAuditLog.ACTION_REMOVE_MEMBER, 'Membership',
            username, entity_id=str(user_id),
            detail=f'team={team_name}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Team Course Assignment API
# ══════════════════════════════════════════════

class TeamCourseAssignView(APIView):
    """
    GET  /api/landa/admin/teams/<team_id>/courses/
    POST /api/landa/admin/teams/<team_id>/courses/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = TeamCourseAssignment.objects.filter(team=team).order_by('assigned_at')
        course_ids = [a.course_id for a in assignments]

        course_name_map = {}
        if course_ids:
            overviews = CourseOverview.objects.filter(id__in=course_ids).values('id', 'display_name')
            course_name_map = {str(o['id']): o['display_name'] for o in overviews}

        data = [{
            'course_id': a.course_id,
            'display_name': course_name_map.get(a.course_id, a.course_id),
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]

        return Response({'courses': data, 'total': len(data)})

    def post(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        course_ids = request.data.get('course_ids', [])
        if not course_ids or not isinstance(course_ids, list):
            return Response({'error': 'course_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        valid_ids = set(
            str(cid) for cid in CourseOverview.objects.filter(id__in=course_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in course_ids if cid not in valid_ids]
        if invalid:
            return Response(
                {'error': f'Course không tồn tại: {", ".join(invalid)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assigned = 0
        skipped = 0
        for course_id in course_ids:
            assignment, created = TeamCourseAssignment.objects.get_or_create(
                team=team, course_id=course_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_COURSE, 'CourseAssignment',
                    course_id, entity_id=str(assignment.id),
                    detail=f'team={team.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class TeamCourseRevokeView(APIView):
    """
    DELETE /api/landa/admin/teams/<team_id>/courses/<course_id>/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, team_id, course_id):
        try:
            assignment = TeamCourseAssignment.objects.get(team_id=team_id, course_id=course_id)
        except TeamCourseAssignment.DoesNotExist:
            return Response({'error': 'Course chưa được phân cho team này'}, status=status.HTTP_404_NOT_FOUND)

        assignment.delete()
        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_COURSE, 'CourseAssignment',
            course_id, entity_id=course_id,
            detail=f'team_id={team_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Team Category Assignment API
# ══════════════════════════════════════════════

class TeamCategoryAssignView(APIView):
    """
    GET  /api/landa/admin/teams/<team_id>/categories/
    POST /api/landa/admin/teams/<team_id>/categories/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = TeamCategoryAssignment.objects.filter(team=team).select_related('category').order_by('assigned_at')
        data = [{
            'category_id': a.category_id,
            'name': a.category.name,
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]
        return Response({'categories': data, 'total': len(data)})

    def post(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        category_ids = request.data.get('category_ids', [])
        if not category_ids or not isinstance(category_ids, list):
            return Response({'error': 'category_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        valid_ids = set(
            DocumentCategory.objects.filter(id__in=category_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in category_ids if cid not in valid_ids]
        if invalid:
            return Response({'error': f'Category không tồn tại: {", ".join(map(str, invalid))}'}, status=status.HTTP_400_BAD_REQUEST)

        assigned = 0
        skipped = 0
        for category_id in category_ids:
            assignment, created = TeamCategoryAssignment.objects.get_or_create(
                team=team, category_id=category_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_CATEGORY, 'CategoryAssignment',
                    str(category_id), entity_id=str(assignment.id),
                    detail=f'team={team.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class TeamCategoryRevokeView(APIView):
    """
    DELETE /api/landa/admin/teams/<team_id>/categories/<cat_id>/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, team_id, cat_id):
        try:
            assignment = TeamCategoryAssignment.objects.get(team_id=team_id, category_id=cat_id)
        except TeamCategoryAssignment.DoesNotExist:
            return Response({'error': 'Category chưa được phân cho team này'}, status=status.HTTP_404_NOT_FOUND)

        assignment.delete()
        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_CATEGORY, 'CategoryAssignment',
            str(cat_id), entity_id=str(cat_id),
            detail=f'team_id={team_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Team Course Category Assignment API
# ══════════════════════════════════════════════

class TeamCourseCategoryAssignView(APIView):
    """
    GET  /api/landa/admin/teams/<team_id>/course-categories/
    POST /api/landa/admin/teams/<team_id>/course-categories/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        assignments = TeamCourseCategoryAssignment.objects.filter(
            team=team
        ).select_related('category').order_by('assigned_at')
        data = [{
            'category_id': a.category_id,
            'name': a.category.name,
            'slug': a.category.slug,
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]
        return Response({'course_categories': data, 'total': len(data)})

    def post(self, request, team_id):
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({'error': 'Team không tồn tại'}, status=status.HTTP_404_NOT_FOUND)

        category_ids = request.data.get('category_ids', [])
        if not category_ids or not isinstance(category_ids, list):
            return Response({'error': 'category_ids phải là danh sách'}, status=status.HTTP_400_BAD_REQUEST)

        valid_ids = set(
            CourseCategory.objects.filter(id__in=category_ids).values_list('id', flat=True)
        )
        invalid = [cid for cid in category_ids if cid not in valid_ids]
        if invalid:
            return Response(
                {'error': f'Course Category không tồn tại: {", ".join(map(str, invalid))}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assigned = 0
        skipped = 0
        for category_id in category_ids:
            assignment, created = TeamCourseCategoryAssignment.objects.get_or_create(
                team=team, category_id=category_id,
                defaults={'assigned_by': request.user},
            )
            if created:
                assigned += 1
                log_group_action(
                    request, GroupAuditLog.ACTION_ASSIGN_COURSE_CATEGORY,
                    'CourseCategoryAssignment',
                    str(category_id), entity_id=str(assignment.id),
                    detail=f'team={team.name}',
                )
            else:
                skipped += 1

        return Response({'success': True, 'assigned': assigned, 'skipped': skipped})


class TeamCourseCategoryRevokeView(APIView):
    """
    DELETE /api/landa/admin/teams/<team_id>/course-categories/<cat_id>/
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def delete(self, request, team_id, cat_id):
        try:
            assignment = TeamCourseCategoryAssignment.objects.get(
                team_id=team_id, category_id=cat_id,
            )
        except TeamCourseCategoryAssignment.DoesNotExist:
            return Response(
                {'error': 'Course Category chưa được phân cho team này'},
                status=status.HTTP_404_NOT_FOUND,
            )

        assignment.delete()
        log_group_action(
            request, GroupAuditLog.ACTION_REVOKE_COURSE_CATEGORY,
            'CourseCategoryAssignment',
            str(cat_id), entity_id=str(cat_id),
            detail=f'team_id={team_id}',
        )
        return Response({'success': True})


# ══════════════════════════════════════════════
# Group Audit Logs API
# ══════════════════════════════════════════════

class GroupAuditLogView(APIView):
    """
    GET /api/landa/admin/group-audit-logs/

    Query params: page, page_size, search, action, date_from, date_to
    Permission: superuser only (cùng pattern với landa_library audit logs)
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [IsStaffUser]

    def get(self, request):
        from django.utils.dateparse import parse_date

        qs = GroupAuditLog.objects.all()

        action = request.query_params.get('action', '').strip().upper()
        if action:
            qs = qs.filter(action=action)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(actor_username__icontains=search) | Q(entity_name__icontains=search)
            )

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

        try:
            page = max(1, int(request.query_params.get('page', 1)))
            page_size = min(max(1, int(request.query_params.get('page_size', 20))), 100)
        except (ValueError, TypeError):
            page, page_size = 1, 20

        total = qs.count()
        offset = (page - 1) * page_size
        logs = qs[offset: offset + page_size]

        results = [{
            'id': lg.id,
            'actor_username': lg.actor_username,
            'action': lg.action,
            'entity_type': lg.entity_type,
            'entity_id': lg.entity_id,
            'entity_name': lg.entity_name,
            'detail': lg.detail,
            'ip_address': lg.ip_address or '',
            'created_at': lg.created_at.isoformat(),
        } for lg in logs]

        return Response({
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'results': results,
        })


# ══════════════════════════════════════════════
# Learner API — My Group Courses
# ══════════════════════════════════════════════

class MyGroupCoursesView(APIView):
    """
    GET /api/landa/v0/my-group-courses/

    Learner gọi để lấy danh sách courses được phân qua group membership.
    Response format tương thích với /api/courses/v1/courses/ để FE-5173
    không cần thay đổi logic render.

    Logic:
    1. Lấy tất cả team_ids user đang là member (TeamMembership)
    2. Lấy distinct course_ids từ TeamCourseCategoryAssignment
    3. Fetch CourseOverview cho từng course_id
    4. Return list courses
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Bước 1: Lấy team_ids user đang là member
        team_ids = TeamMembership.objects.filter(
            user=user,
        ).values_list('team_id', flat=True)

        if not team_ids:
            return Response({
                'pagination': {'count': 0, 'next': None, 'previous': None, 'num_pages': 1},
                'results': [],
                'categories': [],
            })

        # Bước 2: Course IDs từ category-based assignment (Team level)
        category_ids = TeamCourseCategoryAssignment.objects.filter(
            team_id__in=team_ids,
        ).values_list('category_id', flat=True).distinct()

        category_course_ids = set()
        # Build course → categories mapping
        course_categories_map = {}  # course_id → [{id, name, slug}]
        if category_ids:
            memberships = CourseCategoryMembership.objects.filter(
                category_id__in=category_ids,
            ).select_related('category')
            for m in memberships:
                category_course_ids.add(m.course_id)
                if m.course_id not in course_categories_map:
                    course_categories_map[m.course_id] = []
                cat_info = {'id': m.category_id, 'name': m.category.name, 'slug': m.category.slug}
                # Tránh duplicate
                if cat_info not in course_categories_map[m.course_id]:
                    course_categories_map[m.course_id].append(cat_info)

        # Merge all course_ids (hiện tại chỉ dùng category_course_ids)
        all_course_ids = category_course_ids

        if not all_course_ids:
            return Response({
                'pagination': {'count': 0, 'next': None, 'previous': None, 'num_pages': 1},
                'results': [],
                'categories': [],
            })

        # Bước 3: Fetch CourseOverview
        overviews = CourseOverview.objects.filter(id__in=list(all_course_ids))

        # CHỈ CHO PHÉP STAFF THẤY COURSE PRIVATE
        if not user.is_staff and not user.is_superuser:
            overviews = overviews.filter(visible_to_staff_only=False)

        search_term = request.query_params.get('search_term', '').strip()
        if search_term:
            overviews = overviews.filter(display_name__icontains=search_term)

        overviews = overviews.order_by('display_name')

        # Bước 4: Serialize
        results = []
        for c in overviews:
            image_url = ''
            if hasattr(c, 'image_urls') and c.image_urls:
                image_url = c.image_urls.get('raw', '')
            elif hasattr(c, 'course_image_url'):
                image_url = c.course_image_url or ''

            course_id_str = str(c.id)
            results.append({
                'id': course_id_str,
                'name': c.display_name,
                'number': c.number,
                'org': c.org,
                'short_description': getattr(c, 'short_description', '') or '',
                'pacing': 'self' if getattr(c, 'self_paced', True) else 'instructor',
                'start': c.start.isoformat() if c.start else None,
                'end': c.end.isoformat() if c.end else None,
                'media': {
                    'image': {'large': image_url, 'raw': image_url, 'small': image_url},
                    'course_image': {'uri': image_url},
                    'course_video': {'uri': None},
                },
                'categories': course_categories_map.get(course_id_str, []),
            })

        # Bước 5: Build unique categories list cho FE filter
        seen_cats = {}
        for cats in course_categories_map.values():
            for cat in cats:
                if cat['id'] not in seen_cats:
                    seen_cats[cat['id']] = cat
        all_categories = sorted(seen_cats.values(), key=lambda x: x['name'])

        count = len(results)
        return Response({
            'pagination': {
                'count': count,
                'next': None,
                'previous': None,
                'num_pages': 1,
            },
            'results': results,
            'categories': all_categories,
        })


# ══════════════════════════════════════════════
# Learner API — My Role
# ══════════════════════════════════════════════

class MyRoleView(APIView):
    """
    GET /api/landa/v0/my-role/

    Trả về custom role và danh sách OrgGroup IDs mà user thuộc về.
    Dùng bởi frontend-shell để xác định quyền truy cập cho learner_plus.
    Auth: IsAuthenticated (không cần staff).
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Lấy custom role (nếu có)
        custom_role = None
        try:
            landa_role = LandaUserRole.objects.get(user=user)
            custom_role = landa_role.role
        except LandaUserRole.DoesNotExist:
            pass

        # Lấy danh sách OrgGroup mà user thuộc về (deduplicated)
        group_ids = []
        group_names = []
        if custom_role:
            memberships = TeamMembership.objects.filter(
                user=user,
            ).select_related('team__subgroup__org_group').order_by('team__subgroup__org_group__name')

            seen = set()
            for m in memberships:
                og = m.team.subgroup.org_group
                if og.id not in seen:
                    seen.add(og.id)
                    group_ids.append(og.id)
                    group_names.append(og.name)

        return Response({
            'role': custom_role,
            'group_ids': group_ids,
            'group_names': group_names,
        })
