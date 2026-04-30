"""
admin.py — Django Admin UI cho LANDA Library

Admin workflow (không cần kỹ thuật):
  1. Vào /admin/landa_library/documentcategory/ → Tạo danh mục
  2. Vào /admin/landa_library/librarydocument/  → Upload file, gán danh mục
  3. Tick checkbox is_visible hoặc dùng bulk action để hiện/ẩn
"""

from django.contrib import admin
from django.template.defaultfilters import filesizeformat

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'document_count', 'sort_order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    list_editable = ('sort_order',)
    ordering = ('sort_order', 'name')

    def document_count(self, obj):
        """Số file visible thuộc category này"""
        return obj.documents.filter(is_visible=True).count()
    document_count.short_description = "Số file hiển thị"


@admin.register(LibraryDocument)
class LibraryDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'extension_badge', 'category',
        'formatted_size', 'is_visible', 'uploaded_by',
        'created_at',
    )
    list_filter = ('is_visible', 'extension', 'category')
    search_fields = ('title',)
    list_editable = ('is_visible',)
    list_per_page = 50
    readonly_fields = ('extension', 'file_size', 'uploaded_by', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('title', 'file', 'category', 'is_visible', 'sort_order')
        }),
        ('Thông tin tự động', {
            'classes': ('collapse',),
            'fields': ('extension', 'file_size', 'uploaded_by', 'created_at', 'updated_at'),
        }),
    )
    actions = ['make_visible', 'make_hidden']

    # ── Custom display columns ──

    def extension_badge(self, obj):
        """Hiển thị đuôi file dạng badge có màu"""
        colors = {
            'pdf': '#ea4335',
            'docx': '#2b579a',
            'xlsx': '#217346',
            'pptx': '#d24726',
            'mp4': '#9333ea',
            'jpeg': '#0891b2',
            'jpg': '#0891b2',
            'png': '#0d9488',
        }
        color = colors.get(obj.extension, '#666')
        return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold">{obj.extension.upper()}</span>'
    extension_badge.short_description = "Loại"
    extension_badge.allow_tags = True

    def formatted_size(self, obj):
        """Hiển thị dung lượng file dạng dễ đọc"""
        if obj.file_size:
            return filesizeformat(obj.file_size)
        return "-"
    formatted_size.short_description = "Dung lượng"

    # ── Bulk actions ──

    def make_visible(self, request, queryset):
        updated = queryset.update(is_visible=True)
        self.message_user(request, f"✅ Đã hiển thị {updated} file trên Thư viện.")
    make_visible.short_description = "🔓 Hiển thị các file đã chọn"

    def make_hidden(self, request, queryset):
        updated = queryset.update(is_visible=False)
        self.message_user(request, f"🔒 Đã ẩn {updated} file khỏi Thư viện.")
    make_hidden.short_description = "🔒 Ẩn các file đã chọn"

    # ── Auto-set uploaded_by ──

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
