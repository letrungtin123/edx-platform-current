"""
apps.py — LANDA Library AppConfig
"""

from django.apps import AppConfig


class LandaLibraryConfig(AppConfig):
    name = 'lms.djangoapps.landa_library'
    verbose_name = 'LANDA Library'
    default_auto_field = 'django.db.models.BigAutoField'
