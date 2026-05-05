"""
Custom Azure AD OAuth2 backend — fix cho implicit flow (id_token v2.0).

social_core.backends.azuread.AzureADOAuth2 yêu cầu claim "upn" trong JWT,
nhưng id_token v2.0 dùng "preferred_username" thay thế.

Backend này override get_user_id() để fallback sang preferred_username/email
khi upn không có trong token.
"""

from social_core.backends.azuread import AzureADOAuth2


class AzureADOAuth2Custom(AzureADOAuth2):
    """
    Azure AD OAuth2 backend tương thích với id_token v2.0.
    Override get_user_id() để hỗ trợ preferred_username khi thiếu upn.
    """

    def get_user_id(self, details, response):
        """
        Lấy unique ID từ JWT claims.
        Ưu tiên: oid > sub > upn > preferred_username > email
        """
        # oid (Object ID) — unique nhất, không thay đổi khi đổi email
        oid = response.get("oid")
        if oid:
            return oid

        # sub — unique per-application
        sub = response.get("sub")
        if sub:
            return sub

        # upn — v1.0 tokens
        upn = response.get("upn")
        if upn:
            return upn

        # preferred_username — v2.0 tokens
        preferred = response.get("preferred_username")
        if preferred:
            return preferred

        # email — fallback cuối cùng
        email = response.get("email")
        if email:
            return email

        from social_core.exceptions import AuthMissingParameter
        raise AuthMissingParameter(self, "oid/sub/upn/preferred_username")
