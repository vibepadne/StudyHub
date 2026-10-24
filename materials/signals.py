import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .ai import extract_file_text
from .models import Material, MaterialTextIndex

logger = logging.getLogger(__name__)


def index_material(material):
    """Extract and store the searchable text of a material (best effort)."""
    try:
        body = extract_file_text(material)
    except Exception:
        logger.exception("Failed to index text for material %s", material.pk)
        body = ""
    MaterialTextIndex.objects.update_or_create(
        material=material, defaults={"body": body}
    )


@receiver(post_save, sender=Material)
def index_material_on_save(sender, instance, **kwargs):
    index_material(instance)
