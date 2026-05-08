"""
apps.py — LANDA Groups AppConfig
"""

from django.apps import AppConfig


class LandaGroupsConfig(AppConfig):
    name = 'lms.djangoapps.landa_groups'
    label = 'landa_groups'
    verbose_name = 'LANDA Groups'
    default_auto_field = 'django.db.models.BigAutoField'
