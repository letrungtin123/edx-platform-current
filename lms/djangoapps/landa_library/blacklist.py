"""
blacklist.py — Redis-backed User Blacklist (Instant Account Deactivation)

Khi admin lật cờ is_active = False, user bị thêm vào blacklist cache.
Middleware sẽ kiểm tra blacklist trên mỗi request (< 1ms qua Redis)
và từ chối ngay lập tức mà không cần query database.

Flow:
  1. Admin PUT /api/landa/admin/users/<id>/ → is_active = False
  2. admin_api.py gọi blacklist_user(user_id)
  3. Middleware đọc is_user_blacklisted(user_id) trên mọi request
  4. Nếu True → trả 401 → FE tự logout
  5. Admin bật lại is_active = True → gọi unblacklist_user(user_id)

Cache key: "landa:blacklist:<user_id>"
TTL: 7 ngày (safety net — nếu admin quên unblacklist, tự hết hạn)
"""

from django.core.cache import cache

BLACKLIST_PREFIX = "landa:blacklist:"
BLACKLIST_TTL = 7 * 24 * 3600  # 7 ngày


def blacklist_user(user_id):
    """Thêm user vào blacklist. Gọi khi admin set is_active = False."""
    cache.set(f"{BLACKLIST_PREFIX}{user_id}", True, BLACKLIST_TTL)


def unblacklist_user(user_id):
    """Xóa user khỏi blacklist. Gọi khi admin set is_active = True."""
    cache.delete(f"{BLACKLIST_PREFIX}{user_id}")


def is_user_blacklisted(user_id):
    """Kiểm tra user có đang bị blacklist không. < 1ms qua Redis."""
    return cache.get(f"{BLACKLIST_PREFIX}{user_id}") is True
