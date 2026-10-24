import os

from django.conf import settings
import uuid
from django.db import models


def material_upload_path(instance, filename):
    return (
        f"materials/user_{instance.owner_id}/"
        f"subject_{instance.topic.subject_id}/{filename}"
    )


FILE_TYPE_CHOICES = [
    ("pdf", "PDF"),
    ("image", "Image"),
    ("doc", "Document"),
    ("slide", "Presentation"),
    ("other", "Other"),
]

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".svg": "image",
    ".doc": "doc",
    ".docx": "doc",
    ".txt": "doc",
    ".rtf": "doc",
    ".odt": "doc",
    ".ppt": "slide",
    ".pptx": "slide",
    ".odp": "slide",
}


class Subject(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subjects"
    )
    name = models.CharField(max_length=120)
    class_level = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#6366f1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("owner", "name", "class_level")
        ordering = ["class_level", "name"]

    def __str__(self):
        return f"{self.name} ({self.class_level})"


class Topic(models.Model):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="topics"
    )
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("subject", "name")
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.name


class Material(models.Model):
    topic = models.ForeignKey(
        Topic, on_delete=models.CASCADE, related_name="materials"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="materials"
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=material_upload_path)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    converted_pdf = models.FileField(
        upload_to="converted/", blank=True, null=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.file_type:
            ext = os.path.splitext(self.file.name)[1].lower()
            self.file_type = EXTENSION_MAP.get(ext, "other")
        super().save(*args, **kwargs)

    @property
    def icon(self):
        return {
            "pdf": "📕",
            "image": "🖼️",
            "doc": "📄",
            "slide": "📊",
            "other": "📎",
        }.get(self.file_type, "📎")


class MaterialTextIndex(models.Model):
    material = models.OneToOneField(
        Material, on_delete=models.CASCADE, related_name="text_index"
    )
    body = models.TextField(default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["material__uploaded_at"]

    def __str__(self):
        return f"Text index for {self.material}"


class SharedAccess(models.Model):
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="shares",
        null=True,
        blank=True,
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="shares",
        null=True,
        blank=True,
    )
    material = models.ForeignKey(
        "Material", on_delete=models.CASCADE, related_name="shares", null=True, blank=True
    )
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shares_given"
    )
    shared_with = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shares_received",
    )
    password = models.CharField(max_length=128, blank=True)
    password_group = models.UUIDField(
        default=uuid.uuid4, null=True, blank=True, editable=False
    )
    group_title = models.CharField(max_length=200, blank=True, default="")
    unlocked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(subject__isnull=False, topic__isnull=True, material__isnull=True)
                    | models.Q(subject__isnull=True, topic__isnull=False, material__isnull=True)
                    | models.Q(subject__isnull=True, topic__isnull=True, material__isnull=False)
                ),
                name="sharedaccess_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["shared_with", "subject"],
                condition=models.Q(subject__isnull=False),
                name="unique_subject_share_per_user",
            ),
            models.UniqueConstraint(
                fields=["shared_with", "topic"],
                condition=models.Q(topic__isnull=False),
                name="unique_topic_share_per_user",
            ),
            models.UniqueConstraint(
                fields=["shared_with", "material"],
                condition=models.Q(material__isnull=False),
                name="unique_material_share_per_user",
            ),
        ]
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.shared_by} -> {self.shared_with}: {self.target_title}"

    @property
    def target(self):
        return self.subject or self.topic or self.material

    @property
    def target_kind(self):
        if self.subject_id: return "Subject"
        if self.topic_id: return "Topic"
        return "Document"

    @property
    def target_title(self):
        if self.subject:
            return f"{self.subject.name} ({self.subject.class_level})"
        if self.topic:
            return self.topic.name
        return self.material.title

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password

        self.password = make_password(raw_password) if raw_password else ""

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password

        return bool(raw_password) and check_password(raw_password, self.password)
