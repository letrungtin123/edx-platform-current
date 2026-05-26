"""
Data Migration: Chuyển dữ liệu từ SubGroup sang Team

Logic:
1. Mỗi SubGroup hiện tại → tạo 1 Team mặc định cùng tên
2. SubGroupMembership → TeamMembership
3. SubGroupCourseAssignment → TeamCourseAssignment
4. SubGroupCategoryAssignment → TeamCategoryAssignment
5. SubGroupCourseCategoryAssignment → TeamCourseCategoryAssignment

Giữ nguyên SubGroup data (không xóa) — chỉ copy sang Team.
"""

from django.db import migrations


def migrate_subgroups_to_teams(apps, schema_editor):
    """Tạo Team mặc định cho mỗi SubGroup và copy toàn bộ data."""
    SubGroup = apps.get_model('landa_groups', 'SubGroup')
    Team = apps.get_model('landa_groups', 'Team')
    SubGroupMembership = apps.get_model('landa_groups', 'SubGroupMembership')
    TeamMembership = apps.get_model('landa_groups', 'TeamMembership')
    SubGroupCourseAssignment = apps.get_model('landa_groups', 'SubGroupCourseAssignment')
    TeamCourseAssignment = apps.get_model('landa_groups', 'TeamCourseAssignment')
    SubGroupCategoryAssignment = apps.get_model('landa_groups', 'SubGroupCategoryAssignment')
    TeamCategoryAssignment = apps.get_model('landa_groups', 'TeamCategoryAssignment')
    SubGroupCourseCategoryAssignment = apps.get_model('landa_groups', 'SubGroupCourseCategoryAssignment')
    TeamCourseCategoryAssignment = apps.get_model('landa_groups', 'TeamCourseCategoryAssignment')

    for sg in SubGroup.objects.all():
        # 1. Tạo Team mặc định — tên = tên SubGroup
        team, _created = Team.objects.get_or_create(
            subgroup=sg,
            name=sg.name,
            defaults={'created_by': None},
        )

        # 2. Copy memberships
        for m in SubGroupMembership.objects.filter(subgroup=sg):
            TeamMembership.objects.get_or_create(
                team=team,
                user=m.user,
                defaults={'added_by': m.added_by},
            )

        # 3. Copy course assignments
        for ca in SubGroupCourseAssignment.objects.filter(subgroup=sg):
            TeamCourseAssignment.objects.get_or_create(
                team=team,
                course_id=ca.course_id,
                defaults={'assigned_by': ca.assigned_by},
            )

        # 4. Copy category assignments (documents)
        for cat in SubGroupCategoryAssignment.objects.filter(subgroup=sg):
            TeamCategoryAssignment.objects.get_or_create(
                team=team,
                category=cat.category,
                defaults={'assigned_by': cat.assigned_by},
            )

        # 5. Copy course category assignments
        for cca in SubGroupCourseCategoryAssignment.objects.filter(subgroup=sg):
            TeamCourseCategoryAssignment.objects.get_or_create(
                team=team,
                category=cca.category,
                defaults={'assigned_by': cca.assigned_by},
            )


def reverse_noop(apps, schema_editor):
    """Reverse: không xóa data — phải handle thủ công nếu cần rollback."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('landa_groups', '0005_team_hierarchy'),
    ]

    operations = [
        migrations.RunPython(
            migrate_subgroups_to_teams,
            reverse_noop,
            hints={'model_name': 'team'},
        ),
    ]
