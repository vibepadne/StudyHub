"""Database-backed file storage for read-only hosting (Vercel).

The default Django storage writes uploads to MEDIA_ROOT. Vercel's deployment
filesystem is read-only, so uploads fail there. This backend stores each
uploaded file as a BLOB row in the configured database instead.
"""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

from .models import StoredBlob


@deconstructible
class DatabaseStorage(Storage):
    """A Storage implementation that keeps file bytes in the database."""

    def _save(self, name, content):
        data = b"".join(content.chunks())
        StoredBlob.objects.update_or_create(
            name=name,
            defaults={"content": data, "size": len(data)},
        )
        return name

    def _open(self, name, mode="rb"):
        blob = StoredBlob.objects.filter(name=name).first()
        if blob is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(blob.content), name=name)

    def delete(self, name):
        StoredBlob.objects.filter(name=name).delete()

    def exists(self, name):
        return StoredBlob.objects.filter(name=name).exists()

    def size(self, name):
        blob = StoredBlob.objects.filter(name=name).first()
        return len(blob.content) if blob else 0

    def url(self, name):
        # Kept on the app's own /media/ route so the existing permission
        # checks in protected_media() still apply (important for shares).
        return f"{settings.MEDIA_URL}{name}"

    def path(self, name):
        raise NotImplementedError(
            "DatabaseStorage does not expose filesystem paths; use open()."
        )

    def listdir(self, path):
        prefix = path.rstrip("/")
        queryset = (
            StoredBlob.objects.filter(name__startswith=f"{prefix}/")
            if prefix
            else StoredBlob.objects.all()
        )
        dirs, files = set(), []
        for (name,) in queryset.values_list("name"):
            rest = name[len(prefix) + 1 :] if prefix else name
            if "/" in rest:
                dirs.add(rest.split("/", 1)[0])
            else:
                files.append(rest)
        return sorted(dirs), files
