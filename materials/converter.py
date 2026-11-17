import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

WD_FORMAT_PDF = 17
PP_FORMAT_PDF = 32


def _materialize(field, directory):
    """Copy a FieldFile's bytes to a local temp path for COM automation."""
    suffix = Path(field.name).suffix or ""
    path = os.path.join(directory, f"source{suffix}")
    with field.open("rb") as src, open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return path


def _store_converted(material, pdf_path):
    """Save a converted PDF through the configured storage backend."""
    with open(pdf_path, "rb") as handle:
        name = f"converted/{uuid.uuid4().hex}.pdf"
        material.converted_pdf.save(name, ContentFile(handle.read()), save=False)
    material.save(update_fields=["converted_pdf"])
    return material.converted_pdf


def convert_doc_to_pdf(material):
    """Convert a .doc/.docx material to PDF using MS Word.

    Returns the saved converted_pdf FileField path, or None on failure.
    Conversion is best-effort: MS Word is Windows-only, so it is simply
    skipped on Linux/Vercel and in CI.
    """
    if material.converted_pdf:
        return material.converted_pdf

    try:
        import win32com.client

        pythoncom = __import__("pythoncom")
    except Exception:
        logger.info("DOC->PDF conversion unavailable on this platform")
        return None

    word = None
    doc = None
    with tempfile.TemporaryDirectory() as workdir:
        src_abs = _materialize(material.file, workdir)
        out_abs = os.path.join(workdir, f"{uuid.uuid4().hex}.pdf")
        try:
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(src_abs, ReadOnly=True)
            doc.SaveAs2(out_abs, FileFormat=WD_FORMAT_PDF)
            doc.Close(False)
            doc = None
            return _store_converted(material, out_abs)
        except Exception:
            logger.exception("DOC->PDF conversion failed for material %s", material.pk)
            return None
        finally:
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            try:
                if word is not None:
                    word.Quit()
            except Exception:
                pass


def convert_ppt_to_pdf(material):
    """Convert a .ppt/.pptx/.odp material to PDF using MS PowerPoint.

    Returns the saved converted_pdf FileField path, or None on failure.
    """
    if material.converted_pdf:
        return material.converted_pdf

    try:
        import win32com.client

        pythoncom = __import__("pythoncom")
    except Exception:
        logger.info("PPT->PDF conversion unavailable on this platform")
        return None

    ppt = None
    pres = None
    with tempfile.TemporaryDirectory() as workdir:
        src_abs = _materialize(material.file, workdir)
        out_abs = os.path.join(workdir, f"{uuid.uuid4().hex}.pdf")
        try:
            pythoncom.CoInitialize()
            ppt = win32com.client.DispatchEx("PowerPoint.Application")
            pres = ppt.Presentations.Open(
                src_abs, ReadOnly=True, Untitled=False, WithWindow=False
            )
            pres.SaveAs(out_abs, PP_FORMAT_PDF)
            pres.Close()
            pres = None
            return _store_converted(material, out_abs)
        except Exception:
            logger.exception("PPT->PDF conversion failed for material %s", material.pk)
            return None
        finally:
            try:
                if pres is not None:
                    pres.Close()
            except Exception:
                pass
            try:
                if ppt is not None:
                    ppt.Quit()
            except Exception:
                pass
