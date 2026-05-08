"""
audit.py — Ghi log hoạt động group management

Helper function: log_group_action()
Dùng cùng pattern với landa_library/audit.py
"""
import logging

from lms.djangoapps.landa_groups.models import GroupAuditLog

log = logging.getLogger(__name__)


def _get_client_ip(request):
    """Lấy IP thật của client, hỗ trợ reverse proxy."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_group_action(request, action, entity_type, entity_name, entity_id='', detail=''):
    """
    Ghi 1 dòng group audit log.

    Args:
        request: DRF request object
        action: GroupAuditLog.ACTION_* constant
        entity_type: 'OrgGroup' | 'SubGroup' | 'Membership' | 'CourseAssignment' | 'CategoryAssignment'
        entity_name: tên hiển thị
        entity_id: ID của entity (optional)
        detail: mô tả thêm (optional)
    """
    try:
        user = request.user
        GroupAuditLog.objects.create(
            actor=user if user.is_authenticated else None,
            actor_username=user.username if user.is_authenticated else 'anonymous',
            action=action,
            entity_type=entity_type,
            entity_name=str(entity_name)[:255],
            entity_id=str(entity_id)[:255],
            detail=str(detail)[:2000],
            ip_address=_get_client_ip(request),
        )
    except Exception as exc:
        # Không để audit log lỗi crash request chính
        log.error('Failed to write group audit log: %s', exc)
