import logging
import os
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)

WD_FORMAT_PDF = 17
PP_FORMAT_PDF = 32


def convert_doc_to_pdf(material):
    """Convert a .doc/.docx material to PDF using MS Word.

    Returns the saved converted_pdf FileField path, or None on failure.
    """
    if material.converted_pdf:
        return material.converted_pdf

    src_abs = os.path.abspath(material.file.path)
    out_dir = os.path.join(settings.MEDIA_ROOT, "converted")
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}.pdf"
    out_abs = os.path.join(out_dir, out_name)

    word = None
    doc = None
    try:
        import win32com.client

        pythoncom = __import__("pythoncom")
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(src_abs, ReadOnly=True)
        doc.SaveAs2(out_abs, FileFormat=WD_FORMAT_PDF)
        doc.Close(False)
        doc = None

        rel_path = f"converted/{out_name}"
        material.converted_pdf.name = rel_path
        material.save(update_fields=["converted_pdf"])
        return material.converted_pdf
    except Exception:
        logger.exception("DOC->PDF conversion failed for material %s", material.pk)
        if os.path.exists(out_abs):
            try:
                os.remove(out_abs)
            except OSError:
                pass
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

    src_abs = os.path.abspath(material.file.path)
    out_dir = os.path.join(settings.MEDIA_ROOT, "converted")
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}.pdf"
    out_abs = os.path.join(out_dir, out_name)

    ppt = None
    pres = None
    try:
        import win32com.client

        pythoncom = __import__("pythoncom")
        pythoncom.CoInitialize()
        ppt = win32com.client.DispatchEx("PowerPoint.Application")
        pres = ppt.Presentations.Open(
            src_abs, ReadOnly=True, Untitled=False, WithWindow=False
        )
        pres.SaveAs(out_abs, PP_FORMAT_PDF)
        pres.Close()
        pres = None

        rel_path = f"converted/{out_name}"
        material.converted_pdf.name = rel_path
        material.save(update_fields=["converted_pdf"])
        return material.converted_pdf
    except Exception:
        logger.exception("PPT->PDF conversion failed for material %s", material.pk)
        if os.path.exists(out_abs):
            try:
                os.remove(out_abs)
            except OSError:
                pass
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
