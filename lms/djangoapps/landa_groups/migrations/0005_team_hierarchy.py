"""
Migration: Team hierarchy — Thêm cấp Team (OrgGroup → SubGroup → Team)
Tạo 5 models: Team, TeamMembership, TeamCourseAssignment,
              TeamCategoryAssignment, TeamCourseCategoryAssignment
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('landa_groups', '0004_subgroupcoursecategoryassignment'),
        ('landa_library', '0011_coursecategory_coursecategorymembership'),
    ]

    operations = [
        # ── 1. Team ──────────────────────────────────────────
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Tên team')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')),
                ('subgroup', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='teams',
                    to='landa_groups.subgroup',
                    verbose_name='Sub Group',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người tạo',
                )),
            ],
            options={
                'verbose_name': 'Team',
                'verbose_name_plural': 'Teams',
                'ordering': ['name'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='team',
            unique_together={('subgroup', 'name')},
        ),
        migrations.AddIndex(
            model_name='team',
            index=models.Index(fields=['subgroup', 'name'], name='landa_group_team_sg_name_idx'),
        ),

        # ── 2. TeamMembership ────────────────────────────────
        migrations.CreateModel(
            name='TeamMembership',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('added_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày thêm')),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships',
                    to='landa_groups.team',
                    verbose_name='Team',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='team_memberships',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='User',
                )),
                ('added_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người thêm',
                )),
            ],
            options={
                'verbose_name': 'Team Membership',
                'verbose_name_plural': 'Team Memberships',
            },
        ),
        migrations.AlterUniqueTogether(
            name='teammembership',
            unique_together={('team', 'user')},
        ),
        migrations.AddIndex(
            model_name='teammembership',
            index=models.Index(fields=['user', 'team'], name='landa_group_tm_user_team_idx'),
        ),

        # ── 3. TeamCourseAssignment ──────────────────────────
        migrations.CreateModel(
            name='TeamCourseAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_id', models.CharField(
                    db_index=True, max_length=255,
                    verbose_name='Course ID',
                    help_text='VD: course-v1:org+course+run',
                )),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='course_assignments',
                    to='landa_groups.team',
                    verbose_name='Team',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người phân',
                )),
            ],
            options={
                'verbose_name': 'Team Course Assignment',
                'verbose_name_plural': 'Team Course Assignments',
            },
        ),
        migrations.AlterUniqueTogether(
            name='teamcourseassignment',
            unique_together={('team', 'course_id')},
        ),
        migrations.AddIndex(
            model_name='teamcourseassignment',
            index=models.Index(fields=['team', 'course_id'], name='landa_group_tca_team_cid_idx'),
        ),
        migrations.AddIndex(
            model_name='teamcourseassignment',
            index=models.Index(fields=['course_id'], name='landa_group_tca_cid_idx'),
        ),

        # ── 4. TeamCategoryAssignment ────────────────────────
        migrations.CreateModel(
            name='TeamCategoryAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='category_assignments',
                    to='landa_groups.team',
                    verbose_name='Team',
                )),
                ('category', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='team_assignments',
                    to='landa_library.documentcategory',
                    verbose_name='Danh mục tài liệu',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người phân',
                )),
            ],
            options={
                'verbose_name': 'Team Category Assignment',
                'verbose_name_plural': 'Team Category Assignments',
            },
        ),
        migrations.AlterUniqueTogether(
            name='teamcategoryassignment',
            unique_together={('team', 'category')},
        ),
        migrations.AddIndex(
            model_name='teamcategoryassignment',
            index=models.Index(fields=['team', 'category'], name='landa_group_tcata_team_cat_idx'),
        ),
        migrations.AddIndex(
            model_name='teamcategoryassignment',
            index=models.Index(fields=['category'], name='landa_group_tcata_cat_idx'),
        ),

        # ── 5. TeamCourseCategoryAssignment ──────────────────
        migrations.CreateModel(
            name='TeamCourseCategoryAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='course_category_assignments',
                    to='landa_groups.team',
                    verbose_name='Team',
                )),
                ('category', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='team_assignments',
                    to='landa_library.coursecategory',
                    verbose_name='Danh mục khóa học',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người phân',
                )),
            ],
            options={
                'verbose_name': 'Team Course Category Assignment',
                'verbose_name_plural': 'Team Course Category Assignments',
            },
        ),
        migrations.AlterUniqueTogether(
            name='teamcoursecategoryassignment',
            unique_together={('team', 'category')},
        ),
        migrations.AddIndex(
            model_name='teamcoursecategoryassignment',
            index=models.Index(fields=['team', 'category'], name='landa_group_tccca_team_cat_idx'),
        ),
        migrations.AddIndex(
            model_name='teamcoursecategoryassignment',
            index=models.Index(fields=['category'], name='landa_group_tccca_cat_idx'),
        ),
    ]
