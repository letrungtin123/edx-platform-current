"""
validators.py — Validate file upload cho Library

Chấp nhận: pdf, docx, xlsx, pptx, mp4, jpeg, jpg, png
Giới hạn kích thước: 20MB (giống MAX_ASSET_UPLOAD_FILE_SIZE_IN_MB của Open edX)
"""

from django.core.exceptions import ValidationError
from django.conf import settings


ALLOWED_EXTENSIONS = frozenset([
    'pdf', 'docx', 'xlsx', 'pptx',
    'mp4',
    'jpeg', 'jpg', 'png',
])

# Mapping content-type hợp lệ cho từng extension
ALLOWED_CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'mp4': 'video/mp4',
    'jpeg': 'image/jpeg',
    'jpg': 'image/jpeg',
    'png': 'image/png',
}

# Extension → tên hiển thị (dùng cho category tự động nếu cần)
EXTENSION_DISPLAY_NAMES = {
    'pdf': 'PDF Documents',
    'docx': 'Word Documents',
    'xlsx': 'Spreadsheets',
    'pptx': 'Presentations',
    'mp4': 'Videos',
    'jpeg': 'Images',
    'jpg': 'Images',
    'png': 'Images',
}


def get_file_extension(filename):
    """Trích xuất extension từ tên file"""
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


def validate_library_file(file):
    """
    Validate file upload:
    - Đuôi file phải nằm trong ALLOWED_EXTENSIONS
    - Kích thước không vượt quá MAX_ASSET_UPLOAD_FILE_SIZE_IN_MB
    """
    ext = get_file_extension(file.name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Loại file '.{ext}' không được hỗ trợ. "
            f"Chỉ chấp nhận: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    max_size_mb = getattr(settings, 'MAX_ASSET_UPLOAD_FILE_SIZE_IN_MB', 20)
    max_size_bytes = max_size_mb * 1024 * 1024
    if file.size > max_size_bytes:
        raise ValidationError(
            f"File '{file.name}' vượt quá giới hạn {max_size_mb}MB. "
            f"Kích thước hiện tại: {file.size / (1024 * 1024):.1f}MB"
        )
