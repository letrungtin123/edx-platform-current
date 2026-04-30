"""
serializers.py — DRF Serializers cho LANDA Library API
"""

from django.urls import reverse
from rest_framework import serializers

from lms.djangoapps.landa_library.models import DocumentCategory, LibraryDocument


class DocumentCategorySerializer(serializers.ModelSerializer):
    """Serializer cho DocumentCategory — bao gồm count file visible"""
    count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DocumentCategory
        fields = ['id', 'name', 'slug', 'count']


class LibraryDocumentSerializer(serializers.ModelSerializer):
    """Serializer cho LibraryDocument — trả thông tin file + download URL"""
    download_url = serializers.SerializerMethodField()
    category_name = serializers.CharField(
        source='category.name',
        default='',
        read_only=True
    )
    category_slug = serializers.CharField(
        source='category.slug',
        default='',
        read_only=True
    )
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LibraryDocument
        fields = [
            'id', 'title', 'extension', 'file_size',
            'category_name', 'category_slug',
            'download_url', 'uploaded_by_name', 'created_at',
        ]

    def get_download_url(self, obj):
        """
        Trả protected download URL (qua Django view, kiểm tra auth).
        Không trả raw /media/ path — tránh bypass auth.
        """
        if not obj.file:
            return ''
        request = self.context.get('request')
        relative_url = reverse('landa_library_download', kwargs={'doc_id': obj.id})
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url

    def get_uploaded_by_name(self, obj):
        """Tên người upload, fallback 'Admin'"""
        if obj.uploaded_by:
            full_name = obj.uploaded_by.get_full_name()
            return full_name if full_name else obj.uploaded_by.username
        return 'Admin'
