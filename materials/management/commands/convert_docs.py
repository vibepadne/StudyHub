from django.core.management.base import BaseCommand

from materials.converter import convert_doc_to_pdf, convert_ppt_to_pdf
from materials.models import Material


class Command(BaseCommand):
    help = "Convert all uploaded .doc/.docx/.ppt/.pptx/.odp materials to PDF for in-browser viewing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-convert even if a converted PDF already exists.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        qs = Material.objects.filter(file_type__in=("doc", "slide"))
        if not force:
            qs = qs.filter(converted_pdf__isnull=True) | qs.filter(converted_pdf="")
        total = qs.count()
        done = 0
        failed = 0
        for material in qs:
            self.stdout.write(f"Converting: {material.title} (id={material.pk})…")
            if material.file_type == "slide":
                result = convert_ppt_to_pdf(material)
            else:
                result = convert_doc_to_pdf(material)
            if result:
                done += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Converted: {done}/{total}, failed: {failed}"))
