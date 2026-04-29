"""
LANDA Course Files API — Django mini-app
=========================================
Endpoint: GET /api/landa/v0/course_files/{course_id}/

Trả về danh sách file UNLOCKED (locked=False) của course.
User phải đã enrolled (hoặc is_staff).

Admin workflow (không cần HTML):
  Studio → Files & Uploads → Upload file → Click icon ổ khóa → Unlock → Xong!
"""
