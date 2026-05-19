"""
Migration: SubGroupCourseCategoryAssignment
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('landa_groups', '0003_landauserrole'),
        ('landa_library', '0011_coursecategory_coursecategorymembership'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubGroupCourseCategoryAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Người phân')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='group_assignments', to='landa_library.coursecategory', verbose_name='Danh mục khóa học')),
                ('subgroup', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='course_category_assignments', to='landa_groups.subgroup', verbose_name='Sub Group')),
            ],
            options={
                'verbose_name': 'Sub Group Course Category Assignment',
                'verbose_name_plural': 'Sub Group Course Category Assignments',
            },
        ),
        migrations.AddIndex(
            model_name='subgroupcoursecategoryassignment',
            index=models.Index(fields=['subgroup', 'category'], name='landa_group_subgrp_cca_idx'),
        ),
        migrations.AddIndex(
            model_name='subgroupcoursecategoryassignment',
            index=models.Index(fields=['category'], name='landa_group_cat_cca_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='subgroupcoursecategoryassignment',
            unique_together={('subgroup', 'category')},
        ),
    ]
