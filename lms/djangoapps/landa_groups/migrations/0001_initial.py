"""
Initial migration for landa_groups app.
Creates: OrgGroup, SubGroup, SubGroupMembership, SubGroupCourseAssignment, GroupAuditLog
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='Tên group')),
                ('description', models.TextField(blank=True, default='', verbose_name='Mô tả')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Cập nhật')),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người tạo',
                )),
            ],
            options={
                'verbose_name': 'Org Group',
                'verbose_name_plural': 'Org Groups',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='SubGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Tên nhóm')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày tạo')),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người tạo',
                )),
                ('org_group', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subgroups',
                    to='landa_groups.orggroup',
                    verbose_name='Group cha',
                )),
            ],
            options={
                'verbose_name': 'Sub Group',
                'verbose_name_plural': 'Sub Groups',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='SubGroupMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('added_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày thêm')),
                ('added_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người thêm',
                )),
                ('subgroup', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships',
                    to='landa_groups.subgroup',
                    verbose_name='Sub Group',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='group_memberships',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='User',
                )),
            ],
            options={
                'verbose_name': 'Sub Group Membership',
                'verbose_name_plural': 'Sub Group Memberships',
            },
        ),
        migrations.CreateModel(
            name='SubGroupCourseAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_id', models.CharField(
                    db_index=True, max_length=255,
                    verbose_name='Course ID',
                    help_text='VD: course-v1:org+course+run',
                )),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='Ngày phân')),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người phân',
                )),
                ('subgroup', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='course_assignments',
                    to='landa_groups.subgroup',
                    verbose_name='Sub Group',
                )),
            ],
            options={
                'verbose_name': 'Sub Group Course Assignment',
                'verbose_name_plural': 'Sub Group Course Assignments',
            },
        ),
        migrations.CreateModel(
            name='GroupAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actor_username', models.CharField(db_index=True, max_length=150, verbose_name='Actor username')),
                ('action', models.CharField(
                    choices=[
                        ('CREATE_GROUP', 'Create Org Group'),
                        ('UPDATE_GROUP', 'Update Org Group'),
                        ('DELETE_GROUP', 'Delete Org Group'),
                        ('CREATE_SUBGROUP', 'Create Sub Group'),
                        ('UPDATE_SUBGROUP', 'Update Sub Group'),
                        ('DELETE_SUBGROUP', 'Delete Sub Group'),
                        ('ADD_MEMBER', 'Add Member'),
                        ('REMOVE_MEMBER', 'Remove Member'),
                        ('ASSIGN_COURSE', 'Assign Course'),
                        ('REVOKE_COURSE', 'Revoke Course'),
                    ],
                    db_index=True, max_length=20, verbose_name='Action',
                )),
                ('entity_type', models.CharField(
                    db_index=True, max_length=30,
                    verbose_name='Entity type',
                    help_text='OrgGroup | SubGroup | Membership | CourseAssignment',
                )),
                ('entity_id', models.CharField(blank=True, default='', max_length=255, verbose_name='Entity ID')),
                ('entity_name', models.CharField(blank=True, default='', max_length=255, verbose_name='Entity name')),
                ('detail', models.TextField(blank=True, default='', verbose_name='Detail')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP Address')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Created at')),
                ('actor', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Actor',
                )),
            ],
            options={
                'verbose_name': 'Group Audit Log',
                'verbose_name_plural': 'Group Audit Logs',
                'ordering': ['-created_at'],
            },
        ),
        # Unique constraints
        migrations.AddConstraint(
            model_name='subgroup',
            constraint=models.UniqueConstraint(fields=['org_group', 'name'], name='unique_subgroup_per_org'),
        ),
        migrations.AddConstraint(
            model_name='subgroupmembership',
            constraint=models.UniqueConstraint(fields=['subgroup', 'user'], name='unique_user_per_subgroup'),
        ),
        migrations.AddConstraint(
            model_name='subgroupcourseassignment',
            constraint=models.UniqueConstraint(fields=['subgroup', 'course_id'], name='unique_course_per_subgroup'),
        ),
        # Indexes
        migrations.AddIndex(
            model_name='orggroup',
            index=models.Index(fields=['name'], name='landa_org_name_idx'),
        ),
        migrations.AddIndex(
            model_name='subgroup',
            index=models.Index(fields=['org_group', 'name'], name='landa_sg_org_name_idx'),
        ),
        migrations.AddIndex(
            model_name='subgroupmembership',
            index=models.Index(fields=['user', 'subgroup'], name='landa_sgm_user_sg_idx'),
        ),
        migrations.AddIndex(
            model_name='subgroupcourseassignment',
            index=models.Index(fields=['subgroup', 'course_id'], name='landa_sgca_sg_course_idx'),
        ),
        migrations.AddIndex(
            model_name='subgroupcourseassignment',
            index=models.Index(fields=['course_id'], name='landa_sgca_course_idx'),
        ),
        migrations.AddIndex(
            model_name='groupauditlog',
            index=models.Index(fields=['-created_at', 'action'], name='landa_gal_date_action_idx'),
        ),
        migrations.AddIndex(
            model_name='groupauditlog',
            index=models.Index(fields=['actor_username', '-created_at'], name='landa_gal_actor_date_idx'),
        ),
        migrations.AddIndex(
            model_name='groupauditlog',
            index=models.Index(fields=['entity_type', '-created_at'], name='landa_gal_etype_date_idx'),
        ),
    ]
