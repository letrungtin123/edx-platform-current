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
