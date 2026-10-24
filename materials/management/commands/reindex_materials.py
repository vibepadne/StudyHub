from django.core.management.base import BaseCommand

from materials.models import Material, MaterialTextIndex
from materials.signals import index_material


class Command(BaseCommand):
    help = "Extract and store searchable text for every uploaded document."

    def handle(self, *args, **options):
        total = Material.objects.count()
        indexed = 0
        skipped = 0
        for material in Material.objects.iterator():
            has_row = MaterialTextIndex.objects.filter(material=material).exists()
            index_material(material)
            if has_row:
                skipped += 1
            else:
                indexed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Reindexed {total} material(s): {indexed} new, {skipped} refreshed."
            )
        )
