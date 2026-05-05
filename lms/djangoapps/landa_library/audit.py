"""
audit.py — Ghi log hoạt động admin

Helper function duy nhất: log_admin_action()
Gọi từ bất kỳ admin view nào sau khi action thành công.
"""
import logging

from lms.djangoapps.landa_library.models import AdminAuditLog

log = logging.getLogger(__name__)


def _get_client_ip(request):
    """Lấy IP thật của client, hỗ trợ reverse proxy."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_admin_action(request, action, entity_type, entity_name, entity_id='', details=''):
    """
    Ghi 1 dòng audit log.

    Args:
        request: DRF request object (cần request.user)
        action: 'CREATE' | 'UPDATE' | 'DELETE'
        entity_type: 'Document' | 'Category' | 'User' | 'Course' | 'Account'
        entity_name: tên hiển thị (VD: "report.pdf", "admin@example.com")
        entity_id: ID của entity (optional)
        details: mô tả thêm (optional, plain text hoặc JSON string)
    """
    try:
        user = request.user
        AdminAuditLog.objects.create(
            actor=user if user.is_authenticated else None,
            actor_username=user.username if user.is_authenticated else 'anonymous',
            action=action,
            entity_type=entity_type,
            entity_name=str(entity_name)[:255],
            entity_id=str(entity_id)[:100],
            details=str(details)[:2000],
            ip_address=_get_client_ip(request),
        )
    except Exception as e:
        # Không bao giờ để audit log lỗi crash request chính
        log.error(f'Failed to write audit log: {e}')
