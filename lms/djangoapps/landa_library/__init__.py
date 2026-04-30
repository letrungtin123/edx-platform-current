"""
LANDA Library — Kho tài liệu nội bộ
=====================================
Django mini-app quản lý file tài liệu (PDF, DOCX, XLSX, PPTX)
độc lập với course system của Open edX.

Admin workflow:
  CMS Django Admin → /admin/landa_library/
  1. Tạo category (Nhân sự, Chiến lược, Đào tạo...)
  2. Upload file → gán category
  3. Toggle is_visible để hiện/ẩn file trên FE

API:
  GET /api/landa/v1/library/documents/  — danh sách file (phân trang + filter)
  GET /api/landa/v1/library/categories/ — danh sách category + count
"""

default_app_config = 'lms.djangoapps.landa_library.apps.LandaLibraryConfig'
