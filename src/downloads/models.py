from django.conf import settings
from django.db import models


class DownloadTask(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="download_tasks")
    media_id = models.CharField(max_length=50, db_index=True)
    media_type = models.CharField(max_length=20)
    title = models.CharField(max_length=500)
    info_hash = models.CharField(max_length=40, db_index=True)
    transmission_id = models.IntegerField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-added_at"]

    def __str__(self):
        return f"{self.title[:50]} ({self.info_hash[:8]})"
