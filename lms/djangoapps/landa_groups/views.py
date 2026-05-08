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
    OrgGroup,
    SubGroup,
    SubGroupCourseAssignment,
    SubGroupMembership,
    SubGroupCategoryAssignment,
)
from lms.djangoapps.landa_library.models import DocumentCategory

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
            member_count=Count('memberships', distinct=True),
            course_count=Count('course_assignments', distinct=True),
        ).order_by('name')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)

        data = [{
            'id': sg.id,
            'name': sg.name,
            'org_group_id': group_id,
            'member_count': sg.member_count,
            'course_count': sg.course_count,
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

        memberships = SubGroupMembership.objects.filter(subgroup=sg).select_related('user').order_by('added_at')
        assignments = SubGroupCourseAssignment.objects.filter(subgroup=sg).order_by('assigned_at')

        # Lấy display_name cho từng course từ CourseOverview
        course_ids = [a.course_id for a in assignments]
        course_name_map = {}
        if course_ids:
            overviews = CourseOverview.objects.filter(id__in=course_ids).values('id', 'display_name')
            course_name_map = {str(o['id']): o['display_name'] for o in overviews}

        members = [{
            'id': m.user.id,
            'username': m.user.username,
            'email': m.user.email,
            'added_at': m.added_at.isoformat(),
        } for m in memberships]

        courses = [{
            'course_id': a.course_id,
            'display_name': course_name_map.get(a.course_id, a.course_id),
            'assigned_at': a.assigned_at.isoformat(),
        } for a in assignments]

        categories = SubGroupCategoryAssignment.objects.filter(subgroup=sg).select_related('category').order_by('assigned_at')
        categories_data = [{
            'category_id': c.category_id,
            'name': c.category.name,
            'assigned_at': c.assigned_at.isoformat(),
        } for c in categories]

        return Response({
            'id': sg.id,
            'name': sg.name,
            'org_group_id': sg.org_group_id,
            'org_group_name': sg.org_group.name,
            'member_count': len(members),
            'course_count': len(courses),
            'category_count': len(categories_data),
            'members': members,
            'courses': courses,
            'categories': categories_data,
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
    1. Lấy tất cả subgroup_ids user đang là member (SubGroupMembership)
    2. Lấy distinct course_ids từ SubGroupCourseAssignment
    3. Fetch CourseOverview cho từng course_id
    4. Return list courses
    """
    authentication_classes = ADMIN_AUTH_CLASSES
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Bước 1: Lấy subgroup_ids user đang là member
        subgroup_ids = SubGroupMembership.objects.filter(
            user=user,
        ).values_list('subgroup_id', flat=True)

        if not subgroup_ids:
            return Response({'results': [], 'count': 0, 'next': None, 'previous': None})

        # Bước 2: Lấy distinct course_ids được phân cho các subgroups đó
        course_ids = SubGroupCourseAssignment.objects.filter(
            subgroup_id__in=subgroup_ids,
        ).values_list('course_id', flat=True).distinct()

        if not course_ids:
            return Response({'results': [], 'count': 0, 'next': None, 'previous': None})

        # Bước 3: Fetch CourseOverview
        overviews = CourseOverview.objects.filter(id__in=list(course_ids))
        
        # CHỈ CHO PHÉP STAFF THẤY COURSE PRIVATE
        if not user.is_staff and not user.is_superuser:
            overviews = overviews.filter(visible_to_staff_only=False)
        
        search_term = request.query_params.get('search_term', '').strip()
        if search_term:
            overviews = overviews.filter(display_name__icontains=search_term)
            
        overviews = overviews.order_by('display_name')

        # Bước 4: Serialize theo format tương thích với /api/courses/v1/courses/
        # để FE-5173 CoursesPage không cần đổi logic render
        results = []
        for c in overviews:
            image_url = ''
            if hasattr(c, 'image_urls') and c.image_urls:
                image_url = c.image_urls.get('raw', '')
            elif hasattr(c, 'course_image_url'):
                image_url = c.course_image_url or ''

            results.append({
                'id': str(c.id),
                'name': c.display_name,
                'number': c.number,
                'org': c.org,
                'short_description': getattr(c, 'short_description', '') or '',
                # CourseOverview dùng self_paced (bool), map sang string cho FE
                'pacing': 'self' if getattr(c, 'self_paced', True) else 'instructor',
                'start': c.start.isoformat() if c.start else None,
                'end': c.end.isoformat() if c.end else None,
                'media': {
                    'image': {'large': image_url, 'raw': image_url, 'small': image_url},
                    'course_image': {'uri': image_url},
                    'course_video': {'uri': None},
                },
            })

        count = len(results)
        return Response({
            'pagination': {
                'count': count,
                'next': None,
                'previous': None,
                'num_pages': 1,
            },
            'results': results,
        })
