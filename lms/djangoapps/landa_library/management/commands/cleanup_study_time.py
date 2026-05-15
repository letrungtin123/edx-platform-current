"""
cleanup_study_time.py — Xóa dữ liệu study time cũ hơn 7 ngày.

Chạy cron hàng ngày lúc 3h sáng:
    0 3 * * * cd /edx/app/edxapp && python manage.py lms cleanup_study_time

Hoặc Celery Beat:
    CELERYBEAT_SCHEDULE['cleanup_study_time'] = {
        'task': 'lms.djangoapps.landa_library.tasks.cleanup_study_time',
        'schedule': crontab(hour=3, minute=0),
    }

Với 1M users, xóa ~1M rows/ngày (rows > 7 ngày) mất < 1 giây.
Dùng batch delete (chunk 10K) để tránh lock table quá lâu.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Xóa study time data cũ hơn 7 ngày. Chạy hàng ngày qua cron.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Xóa data cũ hơn N ngày (default: 7)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10000,
            help='Số rows xóa mỗi batch (default: 10000)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Chỉ đếm rows sẽ bị xóa, không xóa thật.',
        )

    def handle(self, *args, **options):
        from lms.djangoapps.landa_library.models import StudyTimeDaily

        days = options['days']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        cutoff = timezone.now().date() - timedelta(days=days)
        qs = StudyTimeDaily.objects.filter(date__lt=cutoff)

        total_count = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would delete {total_count} rows older than {cutoff}'
                )
            )
            return

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS(f'No rows older than {cutoff}. Nothing to delete.'))
            return

        # Batch delete để tránh lock table quá lâu trên production
        deleted_total = 0
        while True:
            # Lấy batch IDs → delete by IDs (tránh subquery lock)
            batch_ids = list(
                StudyTimeDaily.objects.filter(date__lt=cutoff)
                .values_list('id', flat=True)[:batch_size]
            )
            if not batch_ids:
                break

            deleted, _ = StudyTimeDaily.objects.filter(id__in=batch_ids).delete()
            deleted_total += deleted
            self.stdout.write(f'  Deleted batch: {deleted} rows (total: {deleted_total})')

        self.stdout.write(
            self.style.SUCCESS(
                f'Done! Deleted {deleted_total} rows older than {cutoff} ({days} days).'
            )
        )
