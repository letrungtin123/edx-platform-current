"""
cleanup_audit_logs — Xóa audit logs cũ hơn 30 ngày.

Usage:
    python manage.py cleanup_audit_logs
    python manage.py cleanup_audit_logs --days 60
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Delete audit logs older than N days (default: 30).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to keep (default: 30)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=5000,
            help='Batch size for deletion (default: 5000)',
        )

    def handle(self, *args, **options):
        from lms.djangoapps.landa_library.models import AdminAuditLog

        days = options['days']
        batch_size = options['batch_size']
        cutoff = timezone.now() - timedelta(days=days)

        total_deleted = 0
        while True:
            # Batch delete to avoid locking the table for too long
            ids = list(
                AdminAuditLog.objects.filter(created_at__lt=cutoff)
                .values_list('id', flat=True)[:batch_size]
            )
            if not ids:
                break
            deleted, _ = AdminAuditLog.objects.filter(id__in=ids).delete()
            total_deleted += deleted
            self.stdout.write(f'  Deleted batch: {deleted} logs')

        self.stdout.write(
            self.style.SUCCESS(f'Done. Deleted {total_deleted} audit logs older than {days} days.')
        )
