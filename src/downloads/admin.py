from django.contrib import admin

from downloads.models import DownloadTask


@admin.register(DownloadTask)
class DownloadTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "info_hash", "transmission_id", "is_active", "added_at")
    list_filter = ("is_active", "media_type")
    search_fields = ("title", "info_hash")
    readonly_fields = ("added_at", "completed_at")
