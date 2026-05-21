"""
Keycloak OIDC Token Exchange — POST /api/landa/auth/keycloak/exchange/

Flow:
  1. FE popup → Keycloak login → callback với authorization code
  2. FE gửi code đến endpoint này
  3. Backend exchange code → Keycloak tokens (dùng client_secret, an toàn)
  4. Backend gọi Keycloak userinfo → lấy email, name
  5. Tìm hoặc tạo user trong edX (role: learner)
  6. Tạo edX OAuth2 tokens → trả về FE

Không cần authentication — endpoint này thay thế login flow.
"""

import logging
import secrets
import string

import requests
from django.conf import settings
from django.contrib.auth.models import User
from oauth2_provider.models import Application
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from openedx.core.djangoapps.oauth_dispatch.api import create_dot_access_token

logger = logging.getLogger(__name__)

# Keycloak config — đọc từ Django settings (lms.yml)
# Fallback về staging defaults cho local dev
def _get_kc_config():
    """Lấy Keycloak config từ settings, fallback staging defaults."""
    kc = getattr(settings, 'KEYCLOAK_OIDC', {})
    return {
        'token_url': kc.get(
            'TOKEN_URL',
            'https://idp.l-a.vn/realms/la-staging/protocol/openid-connect/token',
        ),
        'userinfo_url': kc.get(
            'USERINFO_URL',
            'https://idp.l-a.vn/realms/la-staging/protocol/openid-connect/userinfo',
        ),
        'client_id': kc.get('CLIENT_ID', 'lms-dev'),
        # Staging secret — production PHẢI override qua settings.KEYCLOAK_OIDC
        'client_secret': kc.get('CLIENT_SECRET', 'vX0BzfxQ6F2gvAUlsoJZ0dbJq7Ds1XZ3'),
    }


def _generate_username(email):
    """Sinh username an toàn từ email — prefix + random suffix."""
    prefix = email.split('@')[0]
    # Chỉ giữ ký tự hợp lệ
    prefix = ''.join(c for c in prefix if c.isalnum() or c == '_')[:20]
    if not prefix:
        prefix = 'user'
    suffix = ''.join(secrets.choice(string.digits) for _ in range(4))
    return f"{prefix}_{suffix}"


def _generate_random_password(length=24):
    """Sinh password random an toàn — user SSO không cần biết password này."""
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class KeycloakTokenExchangeView(APIView):
    """
    POST /api/landa/auth/keycloak/exchange/

    Body (form-urlencoded hoặc JSON):
        code         — Keycloak authorization code
        redirect_uri — Redirect URI đã dùng khi authorize (phải khớp)
        client_id    — edX OAuth2 Application client_id

    Response 200:
        { access_token, refresh_token, token_type, expires_in, scope }
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get('code', '').strip()
        redirect_uri = request.data.get('redirect_uri', '').strip()
        edx_client_id = request.data.get('client_id', '').strip()
        code_verifier = request.data.get('code_verifier', '').strip()

        if not code or not redirect_uri or not edx_client_id:
            return Response(
                {'error': 'invalid_request', 'error_description': 'code, redirect_uri, client_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate edX OAuth2 application
        try:
            edx_app = Application.objects.get(client_id=edx_client_id)
        except Application.DoesNotExist:
            return Response(
                {'error': 'invalid_client', 'error_description': f'{edx_client_id} is not a valid client_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kc = _get_kc_config()
        if not kc['client_secret']:
            logger.error('[KeycloakExchange] KEYCLOAK_OIDC.CLIENT_SECRET not configured')
            return Response(
                {'error': 'server_error', 'error_description': 'Keycloak not configured'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ── Step 1: Exchange code → Keycloak tokens ──
        try:
            kc_token_data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': kc['client_id'],
                'client_secret': kc['client_secret'],
            }
            # PKCE: forward code_verifier nếu FE gửi
            if code_verifier:
                kc_token_data['code_verifier'] = code_verifier

            kc_token_resp = requests.post(
                kc['token_url'],
                data=kc_token_data,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error('[KeycloakExchange] Token request failed: %s', exc)
            return Response(
                {'error': 'keycloak_error', 'error_description': 'Cannot reach Keycloak'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if kc_token_resp.status_code != 200:
            logger.warning(
                '[KeycloakExchange] Keycloak token exchange failed: %s %s',
                kc_token_resp.status_code,
                kc_token_resp.text[:500],
            )
            return Response(
                {'error': 'invalid_grant', 'error_description': 'Keycloak rejected the authorization code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kc_tokens = kc_token_resp.json()
        kc_access_token = kc_tokens.get('access_token')
        if not kc_access_token:
            return Response(
                {'error': 'keycloak_error', 'error_description': 'No access_token in Keycloak response'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ── Step 2: Get user info from Keycloak ──
        try:
            userinfo_resp = requests.get(
                kc['userinfo_url'],
                headers={'Authorization': f'Bearer {kc_access_token}'},
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.error('[KeycloakExchange] Userinfo request failed: %s', exc)
            return Response(
                {'error': 'keycloak_error', 'error_description': 'Cannot fetch user info from Keycloak'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if userinfo_resp.status_code != 200:
            return Response(
                {'error': 'invalid_grant', 'error_description': 'Keycloak access_token is invalid'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        userinfo = userinfo_resp.json()
        email = userinfo.get('email', '').strip().lower()
        if not email:
            return Response(
                {'error': 'invalid_grant', 'error_description': 'Keycloak user has no email'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = userinfo.get('name', '') or userinfo.get('preferred_username', '') or email.split('@')[0]

        # ── Step 3: Find or create edX user ──
        user = User.objects.filter(email=email).first()

        if user:
            # User tồn tại — kiểm tra account bị disable
            if not user.has_usable_password():
                return Response(
                    {'error': 'account_disabled', 'error_description': 'User account is disabled'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            logger.info('[KeycloakExchange] Existing user found: %s', user.username)
        else:
            # Tạo user mới — role learner (không staff, không superuser)
            username = _generate_username(email)
            # Đảm bảo username unique
            while User.objects.filter(username=username).exists():
                username = _generate_username(email)

            user = User.objects.create_user(
                username=username,
                email=email,
                password=_generate_random_password(),
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )

            # Set profile name nếu có UserProfile model
            try:
                from common.djangoapps.student.models import UserProfile
                UserProfile.objects.update_or_create(
                    user=user,
                    defaults={'name': name},
                )
            except Exception as exc:
                logger.warning('[KeycloakExchange] Could not set UserProfile: %s', exc)

            logger.info('[KeycloakExchange] New user created: %s (%s)', username, email)

        # ── Step 4: Create edX OAuth2 tokens ──
        try:
            edx_tokens = create_dot_access_token(request, user, edx_app)
        except Exception as exc:
            logger.error('[KeycloakExchange] Failed to create edX tokens: %s', exc)
            return Response(
                {'error': 'server_error', 'error_description': 'Failed to create access token'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(edx_tokens, status=status.HTTP_200_OK)
