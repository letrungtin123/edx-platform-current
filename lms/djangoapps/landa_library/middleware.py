"""
middleware.py — Inject nút "📚 Thư viện" vào mọi trang CMS Studio

Middleware này chèn một floating button ở góc dưới-trái trên mọi trang
HTML mà CMS Django trả về (course outline, settings, xblock editor...).
Admin click vào sẽ đến trang quản lý Library.

Đăng ký trong cms/envs/common.py → MIDDLEWARE:
    'lms.djangoapps.landa_library.middleware.LibraryButtonMiddleware',
"""


class LibraryButtonMiddleware:
    """Inject floating Library Admin button vào HTML response của CMS."""

    BUTTON_HTML = b'''
<!-- LANDA Library Admin Button -->
<div id="landa-lib-btn" style="
  position:fixed;bottom:24px;left:24px;z-index:99999;
  display:flex;align-items:center;gap:8px;
  padding:10px 20px;
  background:linear-gradient(135deg,#0075b4,#005a8c);
  color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:14px;font-weight:600;
  border-radius:12px;box-shadow:0 4px 16px rgba(0,117,180,.4);
  cursor:pointer;transition:all .3s ease;text-decoration:none;
" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 6px 20px rgba(0,117,180,.5)'"
  onmouseout="this.style.transform='';this.style.boxShadow='0 4px 16px rgba(0,117,180,.4)'"
  onclick="window.location.href='/landa-admin/'"
>
  <span style="font-size:18px">&#128218;</span>
  <span>LANDA Admin</span>
</div>
'''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Chỉ inject vào HTML response (không inject vào API/JSON/file)
        content_type = response.get('Content-Type', '')
        if 'text/html' not in content_type:
            return response

        # Không inject vào chính trang landa-admin (đã có header riêng)
        if request.path.startswith('/landa-admin'):
            return response

        # Chỉ inject cho staff
        if not hasattr(request, 'user') or not request.user.is_staff:
            return response

        # Chèn trước </body>
        if hasattr(response, 'content'):
            content = response.content
            if b'</body>' in content:
                response.content = content.replace(
                    b'</body>',
                    self.BUTTON_HTML + b'</body>'
                )
                if 'Content-Length' in response:
                    response['Content-Length'] = len(response.content)

        return response


class BearerTokenAuthMiddleware:
    """
    Authenticate landa-admin API requests bằng Bearer token từ LMS OAuth2.

    Vì CMS và LMS dùng chung database, middleware này query trực tiếp bảng
    oauth2_provider_accesstoken để validate token mà không cần
    oauth2_provider phải nằm trong CMS INSTALLED_APPS.

    Chỉ áp dụng cho /landa-admin/api/ paths (không ảnh hưởng trang admin HTML).

    Đăng ký trong cms/envs/common.py → MIDDLEWARE (sau AuthenticationMiddleware):
        'lms.djangoapps.landa_library.middleware.BearerTokenAuthMiddleware',
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Chỉ xử lý landa-admin API paths
        if not request.path.startswith('/landa-admin/api/'):
            return self.get_response(request)

        # Nếu đã authenticated qua session → bỏ qua
        if hasattr(request, 'user') and request.user.is_authenticated:
            return self.get_response(request)

        # Kiểm tra Bearer token
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return self.get_response(request)

        token_str = auth_header[7:]
        user = self._get_user_from_token(token_str)
        if user is not None:
            request.user = user
            # Bearer token đã là proof of auth → bypass CSRF check
            # (CSRF chỉ cần thiết cho session/cookie-based auth)
            request._dont_enforce_csrf_checks = True

        return self.get_response(request)

    @staticmethod
    def _get_user_from_token(token_str):
        """
        Validate access token bằng raw DB query.
        Trả về User object nếu token hợp lệ và chưa hết hạn, ngược lại None.
        """
        from django.contrib.auth import get_user_model
        from django.db import connection
        from django.utils import timezone

        User = get_user_model()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, expires FROM oauth2_provider_accesstoken "
                    "WHERE token = %s LIMIT 1",
                    [token_str]
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                user_id, expires = row
                if expires < timezone.now():
                    return None

                return User.objects.get(id=user_id)

        except Exception:
            return None


class UserBlacklistMiddleware:
    """
    Middleware chặn mọi API request từ user bị blacklist (is_active = False).

    Kiểm tra Redis cache trên mỗi request (< 1ms).
    Nếu user nằm trong blacklist → trả 401 ngay lập tức.
    FE nhận 401 → interceptor tự động logout.

    Lưu ý quan trọng: FE-5173 dùng Bearer token (OAuth2). Với Bearer auth,
    request.user chỉ được set bởi DRF authentication classes (tầng View),
    KHÔNG phải bởi Django AuthenticationMiddleware. Do đó middleware này
    phải tự parse Bearer token để lấy user_id khi cần.

    Chỉ áp dụng cho các API path /api/ (không ảnh hưởng trang HTML).

    Đăng ký trong lms/envs/common.py → MIDDLEWARE (sau AuthenticationMiddleware):
        'lms.djangoapps.landa_library.middleware.UserBlacklistMiddleware',
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Chỉ kiểm tra trên API paths — không chặn trang HTML login/register
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        # Ưu tiên Bearer token để xác định user (không dùng session).
        # Lý do: FE-5173 và Frontend-Shell cùng proxy đến LMS qua 1 domain,
        # session cookie có thể bị lẫn giữa learner và admin.
        # Bearer token luôn chính xác vì mỗi app gửi token riêng.
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        user_id = None

        if auth_header.startswith('Bearer '):
            user_id = self._get_user_id_from_bearer(request)
        else:
            # Không có Bearer → fallback session (cho các request dùng cookie)
            user = getattr(request, 'user', None)
            if user is not None and user.is_authenticated:
                user_id = user.id

        if user_id is None:
            return self.get_response(request)

        # Kiểm tra blacklist (< 1ms qua Redis)
        from lms.djangoapps.landa_library.blacklist import is_user_blacklisted
        if is_user_blacklisted(user_id):
            from django.http import JsonResponse
            return JsonResponse(
                {
                    'error': 'account_disabled',
                    'message': 'Tài khoản của bạn đã bị vô hiệu hóa.',
                },
                status=401,
            )

        return self.get_response(request)

    @staticmethod
    def _get_user_id_from_bearer(request):
        """
        Parse Bearer token từ Authorization header và trả về user_id.
        Cache kết quả vào Redis (5 phút) để tránh DB query trên mỗi request.
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return None

        token_str = auth_header[7:]

        # Kiểm tra cache trước (tránh DB query)
        from django.core.cache import cache
        cache_key = f"landa:token_uid:{token_str[:16]}"
        cached_uid = cache.get(cache_key)
        if cached_uid is not None:
            return cached_uid if cached_uid != -1 else None

        try:
            from django.db import connection
            from django.utils import timezone

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, expires FROM oauth2_provider_accesstoken "
                    "WHERE token = %s LIMIT 1",
                    [token_str]
                )
                row = cursor.fetchone()
                if row is None:
                    cache.set(cache_key, -1, 60)
                    return None

                user_id, expires = row
                now = timezone.now()
                # DB trả naive datetime → cần make_aware để so sánh
                if timezone.is_naive(expires):
                    import datetime as _dt
                    expires = timezone.make_aware(expires, _dt.timezone.utc)
                if expires < now:
                    cache.set(cache_key, -1, 60)
                    return None

                cache.set(cache_key, user_id, 300)
                return user_id
        except Exception:
            return None

