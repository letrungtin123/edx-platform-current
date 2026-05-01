"""
cms_views.py — CMS Studio views cho LANDA Library Admin
Trang quản lý tại: http://studio.local.openedx.io/library-admin/
"""
import json
import logging
import os

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.template.defaultfilters import filesizeformat
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument
from lms.djangoapps.landa_library.validators import ALLOWED_EXTENSIONS, get_file_extension

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════
# API Endpoints (AJAX) — dùng cho CMS admin page
# ══════════════════════════════════════════════

@staff_member_required
@require_http_methods(["GET", "POST"])
def documents_api(request):
    if request.method == "GET":
        qs = LibraryDocument.objects.select_related('category', 'uploaded_by').order_by('-created_at')
        # Search
        search = request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(title__icontains=search)
        # Filter category
        cat_id = request.GET.get('category_id')
        if cat_id:
            qs = qs.filter(category_id=int(cat_id))
        # Filter extension
        ext = request.GET.get('extension')
        if ext:
            qs = qs.filter(extension=ext.lower())
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 50)), 100)
        total = qs.count()
        offset = (page - 1) * page_size
        docs = qs[offset:offset + page_size]
        data = []
        for doc in docs:
            data.append({
                'id': doc.id, 'title': doc.title, 'extension': doc.extension,
                'file_size': doc.file_size,
                'file_size_display': filesizeformat(doc.file_size) if doc.file_size else '-',
                'category_id': doc.category_id or '',
                'category_name': doc.category.name if doc.category else '',
                'is_visible': doc.is_visible,
                'uploaded_by_name': (doc.uploaded_by.get_full_name() or doc.uploaded_by.username) if doc.uploaded_by else 'Admin',
                'created_at': doc.created_at.strftime('%d/%m/%Y %H:%M') if doc.created_at else '',
            })
        return JsonResponse({'documents': data, 'total': total, 'page': page, 'page_size': page_size})

    # POST — upload (hỗ trợ multi-file)
    title = request.POST.get('title', '').strip()
    category_id = request.POST.get('category_id')
    files = request.FILES.getlist('file')
    if not files:
        return JsonResponse({'error': 'Chưa chọn file'}, status=400)
    created = []
    errors = []
    for f in files:
        ext = get_file_extension(f.name)
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"'{f.name}': đuôi .{ext} không hỗ trợ")
            continue
        # Luôn fallback về tên file gốc nếu không nhập title
        doc_title = title or os.path.splitext(f.name)[0]
        # Nếu có nhiều file và user nhập title, ghép title với tên file
        if len(files) > 1 and title:
            doc_title = f"{title} - {os.path.splitext(f.name)[0]}"
            
        doc = LibraryDocument(title=doc_title, file=f, uploaded_by=request.user)
        if category_id:
            try:
                doc.category = DocumentCategory.objects.get(id=int(category_id))
            except (DocumentCategory.DoesNotExist, ValueError):
                pass
        doc.save()
        created.append(doc.id)
    result = {'success': True, 'created': len(created)}
    if errors:
        result['errors'] = errors
    return JsonResponse(result)


@staff_member_required
@require_http_methods(["PATCH", "DELETE"])
def document_detail_api(request, doc_id):
    try:
        doc = LibraryDocument.objects.get(id=doc_id)
    except LibraryDocument.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy'}, status=404)
    if request.method == "DELETE":
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        return JsonResponse({'success': True})
    data = json.loads(request.body)
    if 'is_visible' in data:
        doc.is_visible = bool(data['is_visible'])
    if 'title' in data and data['title'].strip():
        doc.title = data['title'].strip()
    if 'category_id' in data:
        cat_id = data['category_id']
        if cat_id:
            try:
                doc.category = DocumentCategory.objects.get(id=int(cat_id))
            except (DocumentCategory.DoesNotExist, ValueError):
                pass
        else:
            doc.category = None
    doc.save()
    return JsonResponse({'success': True})


@staff_member_required
@require_http_methods(["POST"])
def document_bulk_api(request):
    data = json.loads(request.body)
    ids = data.get('ids', [])
    action = data.get('action')
    if not ids or action not in ('show', 'hide'):
        return JsonResponse({'error': 'Invalid'}, status=400)
    updated = LibraryDocument.objects.filter(id__in=ids).update(is_visible=(action == 'show'))
    return JsonResponse({'success': True, 'updated': updated})


@staff_member_required
@require_http_methods(["GET", "POST"])
def categories_api(request):
    if request.method == "GET":
        cats = DocumentCategory.objects.annotate(doc_count=Count('documents')).order_by('sort_order', 'name')
        data = [{'id': c.id, 'name': c.name, 'slug': c.slug, 'sort_order': c.sort_order,
                 'doc_count': c.doc_count} for c in cats]
        return JsonResponse({'categories': data})
    data = json.loads(request.body)
    name = data.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'Tên trống'}, status=400)
    if DocumentCategory.objects.filter(name=name).exists():
        return JsonResponse({'error': f'"{name}" đã tồn tại'}, status=400)
    cat = DocumentCategory.objects.create(name=name, slug=slugify(name, allow_unicode=True))
    return JsonResponse({'success': True, 'id': cat.id, 'slug': cat.slug})


@staff_member_required
@require_http_methods(["DELETE"])
def category_detail_api(request, cat_id):
    try:
        cat = DocumentCategory.objects.get(id=cat_id)
    except DocumentCategory.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy'}, status=404)
    cat.delete()
    return JsonResponse({'success': True})


# ══════════════════════════════════════════════
# Main Page — load HTML từ file template
# ══════════════════════════════════════════════

@staff_member_required
@ensure_csrf_cookie
def library_admin_page(request):
    csrf_token = get_token(request)
    allowed_ext = ', '.join(sorted(ALLOWED_EXTENSIONS))
    accept_attr = ','.join(f'.{e}' for e in sorted(ALLOWED_EXTENSIONS))
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'library_admin.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    html = html.replace('{{CSRF_TOKEN}}', csrf_token)
    html = html.replace('{{ALLOWED_EXT}}', allowed_ext)
    html = html.replace('{{ACCEPT_ATTR}}', accept_attr)
    return HttpResponse(html)
