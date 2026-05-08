"""
views_register.py — Public Registration API

POST /api/landa/v1/public/register/

Tạo account learner mới qua Open edX registration nội bộ,
sau đó set is_active=False (chờ admin duyệt).

Endpoint public — không yêu cầu authentication.
"""

import logging
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

log = logging.getLogger(__name__)
User = get_user_model()


class RegisterRateThrottle(AnonRateThrottle):
    """Giới hạn 5 request/phút cho register để chống spam."""
    rate = '5/min'


class PublicRegisterView(APIView):
    """
    POST /api/landa/v1/public/register/

    Body JSON:
    {
        "first_name": "Nhut",
        "last_name": "Tran",
        "email": "nhut.tran@example.com",
        "password": "securePassword123"
    }

    Response 201:
    { "success": true, "message": "..." }

    Luồng:
    1. Validate input
    2. Kiểm tra email/username trùng
    3. Tạo user trực tiếp qua Django ORM (không qua registration API nội bộ)
    4. Set is_active=False ngay lập tức
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        # ── Validate ──
        errors = {}
        if not first_name:
            errors['first_name'] = 'Họ không được để trống.'
        if not last_name:
            errors['last_name'] = 'Tên không được để trống.'
        if not email:
            errors['email'] = 'Email không được để trống.'
        elif not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            errors['email'] = 'Email không hợp lệ.'
        if not password:
            errors['password'] = 'Mật khẩu không được để trống.'
        elif len(password) < 8:
            errors['password'] = 'Mật khẩu phải có ít nhất 8 ký tự.'

        if errors:
            return Response(
                {'success': False, 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Kiểm tra email đã tồn tại ──
        if User.objects.filter(email=email).exists():
            return Response(
                {'success': False, 'errors': {'email': 'Email này đã được sử dụng.'}},
                status=status.HTTP_409_CONFLICT,
            )

        # ── Sinh username từ email ──
        base_username = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0])[:20]
        username = base_username or 'user'
        if User.objects.filter(username=username).exists():
            # Thêm suffix số để tránh trùng
            import random
            username = f"{username}_{random.randint(1000, 9999)}"
            # Nếu vẫn trùng (rất hiếm), thêm suffix khác
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{random.randint(10000, 99999)}"

        # ── Tạo user inactive ──
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_active=False,
                )
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=['first_name', 'last_name'])

                # Tạo UserProfile nếu cần (Open edX yêu cầu)
                try:
                    from common.djangoapps.student.models import UserProfile
                    name = f"{last_name} {first_name}"
                    UserProfile.objects.get_or_create(
                        user=user,
                        defaults={'name': name},
                    )
                except Exception:
                    log.warning("Could not create UserProfile for %s", username)

        except Exception:
            log.exception("landa_api: registration failed for email=%s", email)
            return Response(
                {'success': False, 'errors': {'__all__': 'Không thể tạo tài khoản. Vui lòng thử lại.'}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        log.info("landa_api: registered inactive user %s (email=%s)", username, email)

        return Response(
            {
                'success': True,
                'message': 'Đăng ký thành công. Vui lòng chờ quản trị viên duyệt tài khoản của bạn.',
            },
            status=status.HTTP_201_CREATED,
        )
