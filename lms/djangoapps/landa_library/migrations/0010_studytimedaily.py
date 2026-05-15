"""
Migration: StudyTimeDaily — lưu số phút học/ngày per user.
Tối ưu cho hàng triệu user: unique (user, date), index (user, -date).
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('landa_library', '0009_sectionmodalconfig'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudyTimeDaily',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True, verbose_name='Ngày')),
                ('minutes', models.PositiveIntegerField(default=0, verbose_name='Số phút học')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='study_times',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Learner',
                )),
            ],
            options={
                'verbose_name': 'Study Time Daily',
                'verbose_name_plural': 'Study Time Daily',
                'unique_together': {('user', 'date')},
            },
        ),
        migrations.AddIndex(
            model_name='studytimedaily',
            index=models.Index(fields=['user', '-date'], name='landa_libra_user_id_study_idx'),
        ),
    ]
