"""
Migration 0003 — Thêm model LandaUserRole
Lưu custom role (learner_plus) cho user ngoài is_staff/is_superuser.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('landa_groups', '0002_subgroupcategoryassignment'),
    ]

    operations = [
        migrations.CreateModel(
            name='LandaUserRole',
            fields=[
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='landa_role',
                    serialize=False,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='User',
                )),
                ('role', models.CharField(
                    choices=[('learner_plus', 'Learner Plus')],
                    db_index=True,
                    default='learner_plus',
                    max_length=30,
                    verbose_name='Role',
                )),
                ('created_at', models.DateTimeField(
                    auto_now_add=True,
                    verbose_name='Ngày tạo',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Người gán',
                )),
            ],
            options={
                'verbose_name': 'Landa User Role',
                'verbose_name_plural': 'Landa User Roles',
            },
        ),
    ]
