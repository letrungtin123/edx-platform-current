"""
Migration: CourseCategory + CourseCategoryMembership
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('landa_library', '0010_studytimedaily'),
    ]

    operations = [
        migrations.CreateModel(
            name='CourseCategory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Tên danh mục')),
                ('slug', models.SlugField(max_length=100, unique=True, help_text='Tự động tạo từ tên, dùng cho URL filter')),
                ('description', models.TextField(blank=True, default='', verbose_name='Mô tả')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='Thứ tự sắp xếp')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Cập nhật')),
            ],
            options={
                'verbose_name': 'Course Category',
                'verbose_name_plural': 'Course Categories',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='CourseCategoryMembership',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_id', models.CharField(db_index=True, help_text='VD: course-v1:org+course+run', max_length=255, verbose_name='Course ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Người phân')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='course_memberships', to='landa_library.coursecategory', verbose_name='Danh mục')),
            ],
            options={
                'verbose_name': 'Course Category Membership',
                'verbose_name_plural': 'Course Category Memberships',
            },
        ),
        migrations.AddIndex(
            model_name='coursecategorymembership',
            index=models.Index(fields=['category', 'course_id'], name='landa_libra_categor_ccm_idx'),
        ),
        migrations.AddIndex(
            model_name='coursecategorymembership',
            index=models.Index(fields=['course_id'], name='landa_libra_course__ccm_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='coursecategorymembership',
            unique_together={('category', 'course_id')},
        ),
    ]
