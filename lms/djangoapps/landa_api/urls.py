"""
urls.py — LANDA API URL patterns

Include bằng cách thêm vào lms/urls.py:
    path('api/landa/', include('lms.djangoapps.landa_api.urls')),
"""

from django.urls import re_path
from lms.djangoapps.landa_api.views import CourseFilesView

urlpatterns = [
    # GET /api/landa/v0/course_files/{course_id}/
    re_path(
        r"^v0/course_files/(?P<course_id>[^/]+)/$",
        CourseFilesView.as_view(),
        name="landa_course_files",
    ),
]
