"""
models.py — LANDA Groups Models

OrgGroup: Group cha (tổ chức)
SubGroup: Group con (lớp học, đội nhóm)
SubGroupMembership: M2M through — user thuộc subgroup
SubGroupCourseAssignment: Course được phân cho subgroup (visibility record)
GroupAuditLog: Audit trail cho mọi action group management
"""

from django.conf import settings
from django.db import models


class OrgGroup(models.Model):
    """
    Group cha — tổ chức, phòng ban, công ty.
    Không gắn với course cụ thể nào.
    """
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name='Tên group',
    )
    description = models.TextField(
        blank=True,
        default='',
        verbose_name='Mô tả',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người tạo',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Cập nhật')

    class Meta:
        ordering = ['name']
        verbose_name = 'Org Group'
        verbose_name_plural = 'Org Groups'
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


class SubGroup(models.Model):
    """
    Group con — lớp học, đội nhóm.
    Thuộc 1 OrgGroup, chứa nhiều users.
    """
    org_group = models.ForeignKey(
        OrgGroup,
        on_delete=models.CASCADE,
        related_name='subgroups',
        verbose_name='Group cha',
    )
    name = models.CharField(
        max_length=255,
        verbose_name='Tên nhóm',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người tạo',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')

    class Meta:
        unique_together = (('org_group', 'name'),)
        ordering = ['name']
        verbose_name = 'Sub Group'
        verbose_name_plural = 'Sub Groups'
        indexes = [
            models.Index(fields=['org_group', 'name']),
        ]

    def __str__(self):
        return f'{self.org_group.name} / {self.name}'


class Team(models.Model):
    """
    Cấp thứ 3 — Team thuộc SubGroup.
    Members + assignments gắn vào Team (không gắn vào SubGroup).
    SubGroup chỉ là container chứa Teams.
    """
    subgroup = models.ForeignKey(
        SubGroup,
        on_delete=models.CASCADE,
        related_name='teams',
        verbose_name='Sub Group',
    )
    name = models.CharField(
        max_length=255,
        verbose_name='Tên team',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người tạo',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')

    class Meta:
        unique_together = (('subgroup', 'name'),)
        ordering = ['name']
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'
        indexes = [
            models.Index(fields=['subgroup', 'name']),
        ]

    def __str__(self):
        return f'{self.subgroup.org_group.name} / {self.subgroup.name} / {self.name}'


class SubGroupMembership(models.Model):
    """
    M2M through model — track user thuộc subgroup nào.
    Một user có thể thuộc nhiều subgroup khác nhau.
    """
    subgroup = models.ForeignKey(
        SubGroup,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name='Sub Group',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_memberships',
        verbose_name='User',
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người thêm',
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày thêm')

    class Meta:
        unique_together = (('subgroup', 'user'),)
        verbose_name = 'Sub Group Membership'
        verbose_name_plural = 'Sub Group Memberships'
        indexes = [
            models.Index(fields=['user', 'subgroup']),
        ]

    def __str__(self):
        return f'{self.user.username} → {self.subgroup}'


class SubGroupCourseAssignment(models.Model):
    """
    Course được phân cho sub group — đây là visibility record.

    Ý nghĩa: learner trong subgroup này được NHÌN THẤY course này.
    Không phải tự động enroll — learner phải tự click "Đăng ký".

    Khi user bị remove khỏi subgroup:
    - Record này vẫn còn (không xóa)
    - Nhưng /my-group-courses/ sẽ không trả về course này nữa
    - Vì query dựa trên SubGroupMembership hiện tại
    """
    subgroup = models.ForeignKey(
        SubGroup,
        on_delete=models.CASCADE,
        related_name='course_assignments',
        verbose_name='Sub Group',
    )
    course_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name='Course ID',
        help_text='VD: course-v1:org+course+run',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('subgroup', 'course_id'),)
        verbose_name = 'Sub Group Course Assignment'
        verbose_name_plural = 'Sub Group Course Assignments'
        indexes = [
            models.Index(fields=['subgroup', 'course_id']),
            models.Index(fields=['course_id']),
        ]

    def __str__(self):
        return f'{self.subgroup} ← {self.course_id}'


class SubGroupCategoryAssignment(models.Model):
    """
    Danh mục tài liệu được phân cho sub group — đây là visibility record.

    Ý nghĩa: learner trong subgroup này được NHÌN THẤY các danh mục tài liệu này.
    Nếu user bị remove khỏi subgroup, các record assignment vẫn còn nhưng user
    sẽ không thấy danh mục này (nếu không được phân quyền qua group khác).
    """
    subgroup = models.ForeignKey(
        SubGroup,
        on_delete=models.CASCADE,
        related_name='category_assignments',
        verbose_name='Sub Group',
    )
    category = models.ForeignKey(
        'landa_library.DocumentCategory',
        on_delete=models.CASCADE,
        related_name='group_assignments',
        verbose_name='Danh mục tài liệu',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('subgroup', 'category'),)
        verbose_name = 'Sub Group Category Assignment'
        verbose_name_plural = 'Sub Group Category Assignments'
        indexes = [
            models.Index(fields=['subgroup', 'category']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'{self.subgroup} ← {self.category}'


class SubGroupCourseCategoryAssignment(models.Model):
    """
    Danh mục khóa học được phân cho sub group — đây là visibility record.

    Ý nghĩa: learner trong subgroup này được NHÌN THẤY các courses
    thuộc danh mục khóa học này.
    Tương tự SubGroupCategoryAssignment (dùng cho DocumentCategory).
    """
    subgroup = models.ForeignKey(
        SubGroup,
        on_delete=models.CASCADE,
        related_name='course_category_assignments',
        verbose_name='Sub Group',
    )
    category = models.ForeignKey(
        'landa_library.CourseCategory',
        on_delete=models.CASCADE,
        related_name='group_assignments',
        verbose_name='Danh mục khóa học',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('subgroup', 'category'),)
        verbose_name = 'Sub Group Course Category Assignment'
        verbose_name_plural = 'Sub Group Course Category Assignments'
        indexes = [
            models.Index(fields=['subgroup', 'category']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'{self.subgroup} ← {self.category}'


class TeamMembership(models.Model):
    """
    M2M through model — track user thuộc team nào.
    Một user có thể thuộc nhiều team khác nhau.
    Đây là model chính cho membership (thay thế SubGroupMembership).
    """
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name='Team',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='team_memberships',
        verbose_name='User',
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người thêm',
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày thêm')

    class Meta:
        unique_together = (('team', 'user'),)
        verbose_name = 'Team Membership'
        verbose_name_plural = 'Team Memberships'
        indexes = [
            models.Index(fields=['user', 'team']),
        ]

    def __str__(self):
        return f'{self.user.username} → {self.team}'


class TeamCourseAssignment(models.Model):
    """
    Course được phân cho team — đây là visibility record.
    Ý nghĩa: learner trong team này được NHÌN THẤY course này.
    """
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='course_assignments',
        verbose_name='Team',
    )
    course_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name='Course ID',
        help_text='VD: course-v1:org+course+run',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('team', 'course_id'),)
        verbose_name = 'Team Course Assignment'
        verbose_name_plural = 'Team Course Assignments'
        indexes = [
            models.Index(fields=['team', 'course_id']),
            models.Index(fields=['course_id']),
        ]

    def __str__(self):
        return f'{self.team} ← {self.course_id}'


class TeamCategoryAssignment(models.Model):
    """
    Danh mục tài liệu được phân cho team — visibility record.
    Learner trong team này được NHÌN THẤY các danh mục tài liệu này.
    """
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='category_assignments',
        verbose_name='Team',
    )
    category = models.ForeignKey(
        'landa_library.DocumentCategory',
        on_delete=models.CASCADE,
        related_name='team_assignments',
        verbose_name='Danh mục tài liệu',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('team', 'category'),)
        verbose_name = 'Team Category Assignment'
        verbose_name_plural = 'Team Category Assignments'
        indexes = [
            models.Index(fields=['team', 'category']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'{self.team} ← {self.category}'


class TeamCourseCategoryAssignment(models.Model):
    """
    Danh mục khóa học được phân cho team — visibility record.
    Learner trong team này được NHÌN THẤY các courses thuộc danh mục này.
    """
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='course_category_assignments',
        verbose_name='Team',
    )
    category = models.ForeignKey(
        'landa_library.CourseCategory',
        on_delete=models.CASCADE,
        related_name='team_assignments',
        verbose_name='Danh mục khóa học',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người phân',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')

    class Meta:
        unique_together = (('team', 'category'),)
        verbose_name = 'Team Course Category Assignment'
        verbose_name_plural = 'Team Course Category Assignments'
        indexes = [
            models.Index(fields=['team', 'category']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'{self.team} ← {self.category}'


class GroupAuditLog(models.Model):
    """
    Audit log cho mọi action trong group management.
    Denormalize actor_username để tránh JOIN khi query.
    """
    ACTION_CREATE_GROUP = 'CREATE_GROUP'
    ACTION_UPDATE_GROUP = 'UPDATE_GROUP'
    ACTION_DELETE_GROUP = 'DELETE_GROUP'
    ACTION_CREATE_SUBGROUP = 'CREATE_SUBGROUP'
    ACTION_UPDATE_SUBGROUP = 'UPDATE_SUBGROUP'
    ACTION_DELETE_SUBGROUP = 'DELETE_SUBGROUP'
    ACTION_CREATE_TEAM = 'CREATE_TEAM'
    ACTION_UPDATE_TEAM = 'UPDATE_TEAM'
    ACTION_DELETE_TEAM = 'DELETE_TEAM'
    ACTION_ADD_MEMBER = 'ADD_MEMBER'
    ACTION_REMOVE_MEMBER = 'REMOVE_MEMBER'
    ACTION_ASSIGN_COURSE = 'ASSIGN_COURSE'
    ACTION_REVOKE_COURSE = 'REVOKE_COURSE'
    ACTION_ASSIGN_CATEGORY = 'ASSIGN_CATEGORY'
    ACTION_REVOKE_CATEGORY = 'REVOKE_CATEGORY'
    ACTION_ASSIGN_COURSE_CATEGORY = 'ASSIGN_COURSE_CAT'
    ACTION_REVOKE_COURSE_CATEGORY = 'REVOKE_COURSE_CAT'

    ACTION_CHOICES = [
        (ACTION_CREATE_GROUP, 'Create Org Group'),
        (ACTION_UPDATE_GROUP, 'Update Org Group'),
        (ACTION_DELETE_GROUP, 'Delete Org Group'),
        (ACTION_CREATE_SUBGROUP, 'Create Sub Group'),
        (ACTION_UPDATE_SUBGROUP, 'Update Sub Group'),
        (ACTION_DELETE_SUBGROUP, 'Delete Sub Group'),
        (ACTION_CREATE_TEAM, 'Create Team'),
        (ACTION_UPDATE_TEAM, 'Update Team'),
        (ACTION_DELETE_TEAM, 'Delete Team'),
        (ACTION_ADD_MEMBER, 'Add Member'),
        (ACTION_REMOVE_MEMBER, 'Remove Member'),
        (ACTION_ASSIGN_COURSE, 'Assign Course'),
        (ACTION_REVOKE_COURSE, 'Revoke Course'),
        (ACTION_ASSIGN_CATEGORY, 'Assign Category'),
        (ACTION_REVOKE_CATEGORY, 'Revoke Category'),
        (ACTION_ASSIGN_COURSE_CATEGORY, 'Assign Course Category'),
        (ACTION_REVOKE_COURSE_CATEGORY, 'Revoke Course Category'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Actor',
    )
    actor_username = models.CharField(
        max_length=150,
        db_index=True,
        verbose_name='Actor username',
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        db_index=True,
        verbose_name='Action',
    )
    entity_type = models.CharField(
        max_length=30,
        db_index=True,
        verbose_name='Entity type',
        help_text='OrgGroup | SubGroup | Team | Membership | CourseAssignment | CategoryAssignment',
    )
    entity_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Entity ID',
    )
    entity_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Entity name',
    )
    detail = models.TextField(
        blank=True,
        default='',
        verbose_name='Detail',
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='IP Address',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='Created at',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Group Audit Log'
        verbose_name_plural = 'Group Audit Logs'
        indexes = [
            models.Index(fields=['-created_at', 'action']),
            models.Index(fields=['actor_username', '-created_at']),
            models.Index(fields=['entity_type', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.action}] {self.actor_username} → {self.entity_type}: {self.entity_name}'


class LandaUserRole(models.Model):
    """
    Custom role mở rộng cho hệ thống LANDA.
    Tách biệt khỏi is_staff/is_superuser của Django User.
    Hiện tại dùng cho role 'learner_plus' — user không phải staff
    nhưng được phép truy cập report summary của group mình.
    """
    ROLE_LEARNER_PLUS = 'learner_plus'
    ROLE_CHOICES = [
        (ROLE_LEARNER_PLUS, 'Learner Plus'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='landa_role',
        primary_key=True,
        verbose_name='User',
    )
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default=ROLE_LEARNER_PLUS,
        db_index=True,
        verbose_name='Role',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Người gán',
    )

    class Meta:
        verbose_name = 'Landa User Role'
        verbose_name_plural = 'Landa User Roles'

    def __str__(self):
        return f'{self.user.username} → {self.role}'
