"""
Migration 0001_initial — Tạo bảng DocumentCategory + LibraryDocument

Tạo thủ công vì makemigrations trên Tutor container không output.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import lms.djangoapps.landa_library.models
import lms.djangoapps.landa_library.validators


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── DocumentCategory ──
        migrations.CreateModel(
            name='DocumentCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Tên danh mục')),
                ('slug', models.SlugField(max_length=100, unique=True, help_text='Tự động tạo từ tên, dùng cho URL filter')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='Thứ tự sắp xếp')),
            ],
            options={
                'verbose_name': 'Document Category',
                'verbose_name_plural': 'Document Categories',
                'ordering': ['sort_order', 'name'],
            },
        ),

        # ── LibraryDocument ──
        migrations.CreateModel(
            name='LibraryDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='Tiêu đề')),
                ('file', models.FileField(
                    help_text='Chấp nhận: PDF, DOCX, XLSX, PPTX, MP4, JPEG, JPG, PNG. Tối đa 20MB.',
                    upload_to=lms.djangoapps.landa_library.models.library_upload_path,
                    validators=[lms.djangoapps.landa_library.validators.validate_library_file],
                    verbose_name='File tài liệu',
                )),
                ('extension', models.CharField(db_index=True, editable=False, max_length=10, verbose_name='Đuôi file')),
                ('file_size', models.PositiveIntegerField(default=0, editable=False, verbose_name='Kích thước (bytes)')),
                ('is_visible', models.BooleanField(
                    db_index=True, default=False,
                    help_text='Bật = hiển thị trên Thư viện FE. Tắt = ẩn.',
                    verbose_name='Hiển thị',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Cập nhật')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='Thứ tự')),
                ('category', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='documents',
                    to='landa_library.documentcategory',
                    verbose_name='Danh mục',
                )),
                ('uploaded_by', models.ForeignKey(
                    blank=True, editable=False, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người upload',
                )),
            ],
            options={
                'verbose_name': 'Library Document',
                'verbose_name_plural': 'Library Documents',
                'ordering': ['-created_at'],
            },
        ),

        # ── Indexes ──
        migrations.AddIndex(
            model_name='librarydocument',
            index=models.Index(fields=['is_visible', 'extension'], name='landa_libra_is_visi_idx01'),
        ),
        migrations.AddIndex(
            model_name='librarydocument',
            index=models.Index(fields=['is_visible', 'category', '-created_at'], name='landa_libra_is_visi_idx02'),
        ),
    ]
