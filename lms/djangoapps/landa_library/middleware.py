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
  onclick="window.location.href='/library-admin/'"
>
  <span style="font-size:18px">&#128218;</span>
  <span>Thu vien tai lieu</span>
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

        # Không inject vào chính trang library-admin (đã có header riêng)
        if request.path.startswith('/library-admin'):
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
