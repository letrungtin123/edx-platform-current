"""
models.py — LANDA Library Models

DocumentCategory: Danh mục tài liệu do admin tạo
LibraryDocument:  File tài liệu (PDF/DOCX/XLSX/PPTX/MP4/JPEG/PNG)
"""

import os

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from lms.djangoapps.landa_library.validators import (
    ALLOWED_EXTENSIONS,
    get_file_extension,
    validate_library_file,
)


def library_upload_path(instance, filename):
    """
    Tạo đường dẫn upload theo cấu trúc:
      library_documents/<extension>/<filename>

    Tránh trùng tên bằng cách thêm suffix nếu cần
    (Django FileField tự xử lý trùng tên qua Storage backend).
    """
    ext = get_file_extension(filename)
    return os.path.join('library_documents', ext, filename)


class DocumentCategory(models.Model):
    """
    Danh mục tài liệu — admin tạo tùy ý.
    Ví dụ: "Nhân sự", "Chiến lược", "Đào tạo", "Nội quy"
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Tên danh mục"
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Tự động tạo từ tên, dùng cho URL filter"
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Thứ tự sắp xếp"
    )

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Document Category'
        verbose_name_plural = 'Document Categories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class LibraryDocument(models.Model):
    """
    Tài liệu trong Kho Thư Viện.

    - File lưu trên filesystem (MEDIA_ROOT) của Open edX
    - Chấp nhận: pdf, docx, xlsx, pptx, mp4, jpeg, jpg, png
    - is_visible=False (mặc định) → ẩn trên FE
    - is_visible=True → hiện trên FE
    """
    title = models.CharField(
        max_length=255,
        verbose_name="Tiêu đề"
    )
    file = models.FileField(
        upload_to=library_upload_path,
        validators=[validate_library_file],
        verbose_name="File tài liệu",
        help_text="Chấp nhận: PDF, DOCX, XLSX, PPTX, MP4, JPEG, JPG, PNG. Tối đa 20MB."
    )
    extension = models.CharField(
        max_length=10,
        editable=False,
        db_index=True,
        verbose_name="Đuôi file"
    )
    file_size = models.PositiveIntegerField(
        default=0,
        editable=False,
        verbose_name="Kích thước (bytes)"
    )
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents',
        verbose_name="Danh mục"
    )

    # ── Visibility ──
    is_visible = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Hiển thị",
        help_text="Bật = hiển thị trên Thư viện FE. Tắt = ẩn."
    )

    # ── Metadata ──
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Người upload"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Cập nhật")
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Thứ tự"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Library Document'
        verbose_name_plural = 'Library Documents'
        indexes = [
            models.Index(fields=['is_visible', 'extension']),
            models.Index(fields=['is_visible', 'category', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.extension})"

    def save(self, *args, **kwargs):
        # Auto-set extension và file_size từ file upload
        if self.file:
            self.extension = get_file_extension(self.file.name)
            if hasattr(self.file, 'size') and self.file.size:
                self.file_size = self.file.size
        super().save(*args, **kwargs)


class AdminAuditLog(models.Model):
    """
    Ghi lại hoạt động CRUD của staff/superuser trên admin panel.
    Denormalized actor_username để tránh JOIN khi query data lớn.
    Auto-cleanup sau 30 ngày.
    """
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_username = models.CharField(max_length=150, db_index=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_name = models.CharField(max_length=255)
    entity_id = models.CharField(max_length=100, blank=True, default='')
    details = models.TextField(blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Admin Audit Log'
        verbose_name_plural = 'Admin Audit Logs'
        indexes = [
            models.Index(fields=['-created_at', 'action']),
            models.Index(fields=['actor_username', '-created_at']),
            models.Index(fields=['entity_type', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.action}] {self.actor_username} → {self.entity_type}: {self.entity_name}"


class CourseModalConfig(models.Model):
    """
    Cấu hình 2 modal (Confirm + Completion) cho từng khóa học.
    Mỗi course có tối đa 1 record — tạo lần đầu khi admin cấu hình.
    """
    course_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name="Course ID",
        help_text="CourseKey dạng course-v1:Org+Number+Run"
    )

    # ── Welcome Modal ──
    welcome_enabled = models.BooleanField(default=False, verbose_name="Bật Welcome Modal")
    welcome_title = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name="Tiêu đề Welcome Modal"
    )
    welcome_description = models.TextField(
        blank=True, default="",
        verbose_name="Mô tả Welcome Modal"
    )

    # ── Confirm Modal (hiện khi progress = 0%) ──
    confirm_enabled = models.BooleanField(default=False, verbose_name="Bật Confirm Modal")
    confirm_title = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name="Tiêu đề Confirm Modal"
    )
    confirm_description = models.TextField(
        blank=True, default="",
        verbose_name="Mô tả Confirm Modal"
    )
    confirm_checkbox_text = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Nội dung checkbox xác nhận"
    )

    # ── Completion Modal (hiện khi progress = 100%) ──
    completion_enabled = models.BooleanField(default=False, verbose_name="Bật Completion Modal")
    completion_title = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name="Tiêu đề Completion Modal"
    )
    completion_description = models.TextField(
        blank=True, default="",
        verbose_name="Mô tả Completion Modal"
    )

    SOCIAL_TYPE_CHOICES = [
        ('zaloOA', 'Zalo OA'),
        ('facebook', 'Facebook'),
        ('website', 'Website'),
        ('instagram', 'Instagram'),
    ]
    completion_social_type = models.CharField(
        max_length=20, choices=SOCIAL_TYPE_CHOICES, blank=True, default='',
        verbose_name="Loại mạng xã hội"
    )
    completion_social_link = models.URLField(
        blank=True, default='',
        verbose_name="Link mạng xã hội"
    )

    # ── Metadata ──
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Người cập nhật gần nhất"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Course Modal Config"
        verbose_name_plural = "Course Modal Configs"

    def __str__(self):
        return f"ModalConfig({self.course_id})"


def help_image_upload_path(instance, filename):
    """Upload path: help_docs/images/<filename>"""
    return os.path.join('help_docs', 'images', filename)


class HelpFolder(models.Model):
    """
    Folder gốc trong cây Help Docs.
    Cấu trúc 2 cấp: Folder → Page (không có subfolder).
    Chỉ superuser mới được tạo/sửa/xóa.
    """
    title = models.CharField(max_length=200, verbose_name="Tên folder")
    slug = models.SlugField(max_length=200, unique=True, help_text="URL-friendly, auto-gen từ title")
    icon = models.CharField(max_length=50, blank=True, default='', verbose_name="Lucide icon name")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Thứ tự")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='help_folders_created',
        verbose_name="Người tạo",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        verbose_name = 'Help Folder'
        verbose_name_plural = 'Help Folders'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)


class HelpPage(models.Model):
    """
    Trang tài liệu hướng dẫn trong một HelpFolder.
    Nội dung HTML (rich text) + ảnh embed.
    Chỉ superuser mới được tạo/sửa/xóa. Staff chỉ xem.
    """
    folder = models.ForeignKey(
        HelpFolder,
        on_delete=models.CASCADE,
        related_name='pages',
        verbose_name="Folder",
    )
    title = models.CharField(max_length=300, verbose_name="Tiêu đề")
    slug = models.SlugField(max_length=300, help_text="Unique trong folder")
    content = models.TextField(blank=True, default='', verbose_name="Nội dung HTML")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Thứ tự trong folder")
    is_published = models.BooleanField(default=False, db_index=True, verbose_name="Đã xuất bản")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='help_pages_created',
        verbose_name="Người tạo",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='help_pages_updated',
        verbose_name="Người sửa gần nhất",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        verbose_name = 'Help Page'
        verbose_name_plural = 'Help Pages'
        unique_together = [('folder', 'slug')]
        indexes = [
            models.Index(fields=['folder', 'sort_order']),
            models.Index(fields=['is_published', 'folder']),
        ]

    def __str__(self):
        return f"{self.folder.title} / {self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)


class UserBadge(models.Model):
    """
    Lưu trữ danh hiệu (Gamification) do user đạt được.
    Được đánh giá và tạo từ Frontend (FE-5173).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='badges',
        verbose_name="Learner"
    )
    badge_id = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="Badge ID"
    )
    is_shown = models.BooleanField(
        default=False,
        verbose_name="Đã hiển thị chúc mừng"
    )
    earned_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Ngày đạt"
    )

    class Meta:
        ordering = ['-earned_at']
        unique_together = ['user', 'badge_id']
        verbose_name = 'User Badge'
        verbose_name_plural = 'User Badges'

    def __str__(self):
        return f"{self.user.username} - {self.badge_id}"


class UserCourseModalState(models.Model):
    """
    Lưu trữ trạng thái hiển thị của các Modals khóa học (Welcome, 100%, Confirm).
    Được đánh giá và tạo từ Frontend (FE-5173).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_modal_states',
        verbose_name="Learner"
    )
    course_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Course ID"
    )
    welcome_shown = models.BooleanField(
        default=False,
        verbose_name="Đã hiện Welcome"
    )
    confirm_shown = models.BooleanField(
        default=False,
        verbose_name="Đã hiện Confirm"
    )
    complete_shown = models.BooleanField(
        default=False,
        verbose_name="Đã hiện Complete"
    )

    class Meta:
        # unique_together tự động tạo index phức hợp (user_id, course_id)
        # Giúp truy vấn O(1) và cực kỳ tối ưu cho hàng triệu record dưới DB
        unique_together = ['user', 'course_id']
        verbose_name = 'Course Modal State'
        verbose_name_plural = 'Course Modal States'

    def __str__(self):
        return f"{self.user.username} - {self.course_id}"


class SectionModalConfig(models.Model):
    """
    Cấu hình modal khích lệ cho từng Section (Chapter) trong khóa học.
    Mỗi section có tối đa 1 record config — admin tạo/sửa qua Course Editor.
    """
    course_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Course ID"
    )
    section_id = models.CharField(
        max_length=255,
        verbose_name="Section Block ID",
        help_text="Block ID của chapter, vd: block-v1:Org+Num+Run+type@chapter+block@xxx"
    )
    enabled = models.BooleanField(
        default=False,
        verbose_name="Bật popup khích lệ"
    )
    title = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name="Tiêu đề modal"
    )
    description = models.TextField(
        blank=True, default="",
        verbose_name="Nội dung khích lệ"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Người cập nhật"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['course_id', 'section_id']
        verbose_name = 'Section Modal Config'
        verbose_name_plural = 'Section Modal Configs'

    def __str__(self):
        return f"SectionModal({self.course_id} / {self.section_id})"


class UserSectionModalShown(models.Model):
    """
    Track trạng thái user đã xem popup khích lệ section nào.
    Tách bảng riêng (không dùng JSONField) để tối ưu cho hàng triệu records.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='section_modal_shown',
        verbose_name="Learner"
    )
    course_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Course ID"
    )
    section_id = models.CharField(
        max_length=255,
        verbose_name="Section Block ID"
    )
    shown_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Thời điểm xem"
    )

    class Meta:
        # Index composite 3 cột → lookup O(1) ngay cả với hàng chục triệu rows
        unique_together = ['user', 'course_id', 'section_id']
        verbose_name = 'User Section Modal Shown'
        verbose_name_plural = 'User Section Modal Shown'

    def __str__(self):
        return f"{self.user.username} - {self.course_id} / {self.section_id}"


class StudyTimeDaily(models.Model):
    """
    Lưu số phút học mỗi ngày per user.

    FE buffer trong localStorage và sync lên server mỗi 5 phút.
    Server dùng GREATEST() pattern khi upsert → tránh double-count
    khi user mở nhiều tab hoặc đa thiết bị.

    Cleanup: management command xóa rows > 7 ngày (chạy cron hàng ngày).
    Với 1M users × 7 ngày = tối đa 7M rows (~140MB) — cực nhẹ.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='study_times',
        verbose_name="Learner",
    )
    date = models.DateField(
        db_index=True,
        verbose_name="Ngày",
    )
    minutes = models.PositiveIntegerField(
        default=0,
        verbose_name="Số phút học",
    )

    class Meta:
        unique_together = ['user', 'date']
        verbose_name = 'Study Time Daily'
        verbose_name_plural = 'Study Time Daily'
        indexes = [
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.date}: {self.minutes}m"


class CourseCategory(models.Model):
    """
    Danh mục khóa học — admin tạo tùy ý.
    Ví dụ: "Onboarding", "Kỹ năng mềm", "Chuyên môn", "An toàn lao động"

    Tương tự DocumentCategory nhưng dành cho courses.
    Một course có thể thuộc nhiều danh mục (qua CourseCategoryMembership).
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Tên danh mục",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Tự động tạo từ tên, dùng cho URL filter",
    )
    description = models.TextField(
        blank=True,
        default='',
        verbose_name="Mô tả",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Thứ tự sắp xếp",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Cập nhật")

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Course Category'
        verbose_name_plural = 'Course Categories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class CourseCategoryMembership(models.Model):
    """
    Course thuộc danh mục nào — M2M through table.

    Một course có thể thuộc nhiều danh mục.
    course_id lưu dạng string (VD: course-v1:Org+Number+Run)
    vì CourseOverview.id là CourseKey, không phải integer FK.
    """
    category = models.ForeignKey(
        CourseCategory,
        on_delete=models.CASCADE,
        related_name='course_memberships',
        verbose_name='Danh mục',
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
        unique_together = (('category', 'course_id'),)
        verbose_name = 'Course Category Membership'
        verbose_name_plural = 'Course Category Memberships'
        indexes = [
            models.Index(fields=['category', 'course_id']),
            models.Index(fields=['course_id']),
        ]

    def __str__(self):
        return f'{self.category.name} ← {self.course_id}'

