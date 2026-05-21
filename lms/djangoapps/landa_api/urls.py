"""
urls.py — LANDA API URL patterns

Include bằng cách thêm vào lms/urls.py:
    path('api/landa/', include('lms.djangoapps.landa_api.urls')),
"""

from django.urls import path, re_path
from lms.djangoapps.landa_api.views import CourseFilesView
from lms.djangoapps.landa_api.views_register import PublicRegisterView
from lms.djangoapps.landa_api.views_keycloak import KeycloakTokenExchangeView

urlpatterns = [
    # GET /api/landa/v0/course_files/{course_id}/
    re_path(
        r"^v0/course_files/(?P<course_id>[^/]+)/$",
        CourseFilesView.as_view(),
        name="landa_course_files",
    ),
    # POST /api/landa/v1/public/register/
    re_path(
        r"^v1/public/register/$",
        PublicRegisterView.as_view(),
        name="landa_public_register",
    ),
    # POST /api/landa/auth/keycloak/exchange/
    path(
        "auth/keycloak/exchange/",
        KeycloakTokenExchangeView.as_view(),
        name="keycloak_exchange",
    ),
]

