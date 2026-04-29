"""
views.py — LANDA Course Files API view

GET /api/landa/v0/course_files/{course_id}/

Dùng DRF APIView + JwtAuthentication + SessionAuthentication
(cùng pattern với enrollment API của Open edX)
"""

import logging

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.djangoapps.student.models import CourseEnrollment
from xmodule.contentstore.django import contentstore as get_contentstore

log = logging.getLogger(__name__)

# File types được coi là "tài liệu tham khảo"
DOCUMENT_EXTENSIONS = frozenset([
    "pdf", "doc", "docx",
    "ppt", "pptx",
    "xls", "xlsx", "csv",
    "txt", "zip"
])

CONTENT_TYPE_MAP = {
    "pdf":  "application/pdf",
    "doc":  "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt":  "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xls":  "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv":  "text/csv",
    "txt":  "text/plain",
    "zip":  "application/zip",
}


def _get_extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _is_document(filename):
    return _get_extension(filename) in DOCUMENT_EXTENSIONS


class CourseFilesView(APIView):
    """
    GET /api/landa/v0/course_files/{course_id}/

    Trả về danh sách file UNLOCKED (locked=False) của course.
    Chỉ document types: pdf, docx, pptx, xlsx, csv, txt, zip.

    Auth: JWT hoặc Session (cùng pattern với enrollment API)
    Permission: IsAuthenticated + enrolled (hoặc is_staff)

    Asset dict keys từ MongoContentStore:
        displayname  -> str (không có underscore)
        locked       -> bool
        uploadDate   -> datetime
        length       -> int (bytes)
        asset_key    -> AssetKey object
    """

    authentication_classes = [
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    ]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, course_id):
        # 1. Parse course key
        try:
            course_key = CourseKey.from_string(course_id)
        except (InvalidKeyError, ValueError) as exc:
            return Response(
                {"error": f"Invalid course_id: {exc}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Enrollment / staff check
        user = request.user
        if not user.is_staff:
            if not CourseEnrollment.is_enrolled(user, course_key):
                return Response(
                    {"error": "You must be enrolled in this course to view its files"},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 3. Fetch all assets từ contentstore
        try:
            cs = get_contentstore()
            assets, _total = cs.get_all_content_for_course(
                course_key,
                start=0,
                maxresults=-1,
            )
        except Exception:
            log.exception("landa_api: error fetching assets for %s", course_id)
            return Response(
                {"error": "Failed to fetch course assets"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 4. Filter: unlocked document files only
        result = []
        for asset in assets:
            if asset.get("locked", False):
                continue

            name = asset.get("displayname", "")  # key đúng: displayname (không underscore)
            if not _is_document(name):
                continue

            ext = _get_extension(name)
            asset_key = asset.get("asset_key")
            url = ("/" + str(asset_key)) if asset_key else ""

            upload_date = asset.get("uploadDate")
            date_str = upload_date.isoformat() if hasattr(upload_date, "isoformat") else str(upload_date or "")

            result.append({
                "id": str(asset_key) if asset_key else name,
                "display_name": name,
                "url": url,
                "extension": ext,
                "content_type": CONTENT_TYPE_MAP.get(ext, "application/octet-stream"),
                "size": asset.get("length", 0),  # key đúng: length (bytes)
                "date_added": date_str,
            })

        result.sort(key=lambda x: x["date_added"], reverse=True)

        return Response({"files": result, "total": len(result)})
