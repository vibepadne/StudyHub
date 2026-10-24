import json
import os
import re
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.base import File
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import ai
from .converter import convert_doc_to_pdf, convert_ppt_to_pdf
from .models import (
    EXTENSION_MAP,
    FILE_TYPE_CHOICES,
    Material,
    MaterialTextIndex,
    SharedAccess,
    Subject,
    Topic,
)
from .serializers import MaterialSerializer, SubjectSerializer, TopicSerializer
from .signals import index_material

AI_NOT_CONFIGURED_DEFAULT = (
    "AI assistant isn't configured yet. Add GEMINI_API_KEY to the .env file "
    "and restart the server."
)


class SubjectViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectSerializer

    def get_queryset(self):
        return (
            Subject.objects.filter(owner=self.request.user)
            .annotate(
                topic_count=Count("topics", distinct=True),
                material_count=Count("topics__materials", distinct=True),
            )
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get"])
    def access(self, request, pk=None):
        subject = get_object_or_404(Subject, pk=pk, owner=request.user)
        shares = (
            SharedAccess.objects.filter(
                Q(subject=subject) | Q(topic__subject=subject) | Q(material__topic__subject=subject)
            )
            .select_related("shared_with", "shared_with__profile")
            .order_by("-created_at")
        )
        data = []
        for share in shares:
            try:
                profile = share.shared_with.profile
            except Exception:
                profile = None
            data.append(
                {
                    "share_id": share.pk,
                    "user_id": share.shared_with_id,
                    "username": share.shared_with.username,
                    "full_name": profile.full_name if profile else "",
                    "avatar": profile.avatar.url if profile and profile.avatar else "",
                    "kind": "subject" if share.subject_id else "topic",
                    "topic_name": "" if share.subject_id else share.topic.name,
                    "has_password": bool(share.password),
                    "shared_at": share.created_at.strftime("%b %d, %Y"),
                }
            )
        return Response(data)


class TopicViewSet(viewsets.ModelViewSet):
    serializer_class = TopicSerializer

    def get_queryset(self):
        return Topic.objects.filter(subject__owner=self.request.user).annotate(
            material_count=Count("materials")
        )

    def perform_create(self, serializer):
        subject = serializer.validated_data["subject"]
        if subject.owner != self.request.user:
            raise PermissionError("Not your subject.")
        order = Topic.objects.filter(subject=subject).count()
        serializer.save(order=order)


class MaterialViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Material.objects.filter(owner=self.request.user).select_related(
            "topic", "topic__subject"
        )
        topic_id = self.request.query_params.get("topic")
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        return qs

    def perform_create(self, serializer):
        topic = serializer.validated_data["topic"]
        if topic.subject.owner != self.request.user:
            raise PermissionDenied("Not your topic.")
        file = serializer.validated_data["file"]
        ext = os.path.splitext(file.name)[1].lower()
        file_type = EXTENSION_MAP.get(ext, "other")
        title = serializer.validated_data.get("title") or os.path.splitext(file.name)[0]
        instance = serializer.save(owner=self.request.user, file_type=file_type, title=title)
        if file_type == "doc":
            convert_doc_to_pdf(instance)
        elif file_type == "slide":
            convert_ppt_to_pdf(instance)

    @action(detail=False, methods=["get"])
    def types(self, request):
        return Response([{"value": v, "label": l} for v, l in FILE_TYPE_CHOICES])


def _convert_pending(topics):
    for topic in topics:
        for material in topic.materials.all():
            if material.converted_pdf:
                continue
            if material.file_type == "doc":
                convert_doc_to_pdf(material)
            elif material.file_type == "slide":
                convert_ppt_to_pdf(material)


def _unlocked_share_queryset(user):
    """Shares granted to `user` that are readable (no password or unlocked)."""
    return SharedAccess.objects.filter(shared_with=user).filter(
        Q(password="") | Q(unlocked_at__isnull=False)
    )


def _topics_for_shared_subject(user, subject):
    """Topics of `subject` visible to a non-owner: only unlocked shares.

    Returns (full_access, topics). Subject-level grants see everything;
    topic/material-level grants see just their unlocked documents.
    """
    shares = _unlocked_share_queryset(user)
    if shares.filter(subject_id=subject.pk).exists():
        return True, list(
            subject.topics.prefetch_related(
                Prefetch(
                    "materials",
                    queryset=Material.objects.order_by("-uploaded_at", "-pk"),
                )
            )
        )
    topic_ids = set(
        shares.filter(topic__subject_id=subject.pk).values_list("topic_id", flat=True)
    )
    material_ids = set(
        shares.filter(material__topic__subject_id=subject.pk).values_list(
            "material_id", flat=True
        )
    )
    if topic_ids:
        material_ids |= set(
            Material.objects.filter(topic_id__in=topic_ids).values_list("pk", flat=True)
        )
    topics = list(
        subject.topics.filter(
            Q(pk__in=topic_ids) | Q(materials__pk__in=material_ids)
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "materials",
                queryset=Material.objects.filter(pk__in=material_ids).order_by(
                    "-uploaded_at", "-pk"
                ),
            )
        )
    )
    return False, topics


@login_required
def subject_viewer(request, subject_id):
    # Owner view – or shared view if unlocked (so /viewer/subject/<id>/ works for recipients too)
    try:
        subject = Subject.objects.get(pk=subject_id, owner=request.user)
    except Subject.DoesNotExist:
        # Check if shared and unlocked (covers subject / topic / material shares for this subject)
        has_unlocked_share = (
            SharedAccess.objects.filter(shared_with=request.user)
            .filter(Q(password="") | Q(unlocked_at__isnull=False))
            .filter(
                Q(subject_id=subject_id)
                | Q(topic__subject_id=subject_id)
                | Q(material__topic__subject_id=subject_id)
            )
            .exists()
        )
        if has_unlocked_share:
            subject = get_object_or_404(Subject.objects.select_related("owner"), pk=subject_id)
            # A recipient sees only unlocked documents — never locked ones,
            # even when another share covering this subject is unlocked.
            _, topics = _topics_for_shared_subject(request.user, subject)
        else:
            # If locked, redirect to password entry for the first covering share
            locked = (
                SharedAccess.objects.filter(shared_with=request.user, unlocked_at__isnull=True)
                .exclude(password="")
                .filter(
                    Q(subject_id=subject_id)
                    | Q(topic__subject_id=subject_id)
                    | Q(material__topic__subject_id=subject_id)
                )
                .first()
            )
            if locked:
                return redirect("shared-open", pk=locked.pk)
            raise Http404
    else:
        topics = subject.topics.prefetch_related("materials")
    _convert_pending(topics)
    return render(
        request,
        "viewer.html",
        {
            "subject": subject,
            "topics": topics,
            "mode": "subject",
            "ai_subject_id": subject.id,
            "ai_title": subject.name,
        },
    )


@login_required
def topic_viewer(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id, subject__owner=request.user)
    topics = [topic]
    material_id = request.GET.get("material")
    single_material = None
    if material_id and material_id.isdigit():
        single_material = get_object_or_404(topic.materials, pk=int(material_id))
    _convert_pending(topics)
    return render(
        request,
        "viewer.html",
        {
            "subject": topic.subject,
            "topics": topics,
            "mode": "material" if single_material else "topic",
            "single_material": single_material,
            "ai_subject_id": topic.subject_id,
            "ai_title": topic.name,
        },
    )


@login_required
def material_viewer(request, material_id):
    material = get_object_or_404(
        Material.objects.select_related("topic__subject"),
        pk=material_id,
        topic__subject__owner=request.user,
    )
    topic = material.topic
    _convert_pending([topic])
    return render(
        request,
        "viewer.html",
        {
            "subject": topic.subject,
            "topics": [topic],
            "mode": "material",
            "single_material": material,
            "ai_subject_id": topic.subject_id,
            "ai_title": material.title,
        },
    )


SHARE_MIN_PASSWORD_LEN = 4


def _get_share_for(request, pk):
    return get_object_or_404(
        SharedAccess.objects.select_related(
            "shared_by", "shared_with", "subject", "topic", "material", "material__topic"
        ),
        pk=pk,
        shared_with=request.user,
    )


def _locked_batch_sibling(user, share):
    """A still-locked share from the same unlockable batch, if any."""
    if not share.password_group:
        return None
    return (
        SharedAccess.objects.filter(
            shared_with=user, password_group=share.password_group
        )
        .exclude(password="")
        .filter(unlocked_at__isnull=True)
        .order_by("-created_at", "-pk")
        .first()
    )


@login_required
def share_create(request, kind, subject_id=None, topic_id=None):
    if kind == "subject":
        target = get_object_or_404(Subject, pk=subject_id, owner=request.user)
    else:
        target = get_object_or_404(
            Topic.objects.select_related("subject"), pk=topic_id, subject__owner=request.user
        )

    errors = []
    if request.method == "POST":
        raw_ids = {
            s for s in request.POST.get("recipient_ids", "").split(",") if s.strip().isdigit()
        }
        password = request.POST.get("password", "").strip()
        confirm = request.POST.get("password_confirm", "").strip()
        title = request.POST.get("title", "").strip()
        if password and len(password) < SHARE_MIN_PASSWORD_LEN:
            errors.append(f"Password must be at least {SHARE_MIN_PASSWORD_LEN} characters.")
        elif password != confirm:
            errors.append("Passwords do not match.")
        recipients = list(
            User.objects.filter(pk__in=[int(i) for i in raw_ids], is_active=True).exclude(
                pk=request.user.pk
            )
        )
        if not recipients:
            errors.append("Pick at least one person to share with.")
        elif len(recipients) != len(raw_ids):
            errors.append("Some selected users could not be found. Re-add them.")
        # Only share documents, not subject/topic names: expand to materials
        if kind == "subject":
            materials_to_share = list(Material.objects.filter(topic__subject=target).select_related("topic"))
        else:
            materials_to_share = list(target.materials.all().select_related("topic"))
        if not materials_to_share and not errors:
            errors.append("This subject/topic has no documents to share.")
        if not errors:
            created = skipped = 0
            newly_shared_materials = set()
            # Use provided title or default to subject/topic name
            group_title = title or f"{target.name} documents" if hasattr(target, 'name') else f"{target.title} documents"
            # Generate password_group for title grouping even without password
            password_group = uuid.uuid4() if len(materials_to_share) > 1 or title else (uuid.uuid4() if password else None)
            # If no password_group but title exists, still need group for title
            if title and not password_group:
                password_group = uuid.uuid4()
            for material in materials_to_share:
                for user in recipients:
                    share, was_created = SharedAccess.objects.get_or_create(
                        shared_by=request.user, shared_with=user, material=material
                    )
                    if not was_created:
                        skipped += 1
                        # The document already lives in an earlier bubble.
                        # Never rip it out of that bubble: silently
                        # re-sharing must not make previously shared
                        # documents disappear from the shared lists.
                        continue
                    created += 1
                    newly_shared_materials.add(material.pk)
                    share.set_password(password)
                    share.password_group = password_group
                    share.group_title = group_title
                    share.save(update_fields=["password", "password_group", "group_title"])
            # For message, count documents shared per user
            total_docs = len(newly_shared_materials)
            msg = (
                f"Shared {total_docs} document{'s' if total_docs != 1 else ''} with {len(recipients)} people."
                if created
                else "Nothing new shared."
            )
            if skipped:
                msg += f" {skipped} already had access."
            # Instant UX: if background fetch (keepalive), return JSON immediately without waiting for redirect page
            if request.headers.get("X-Requested-With") == "fetch":
                return JsonResponse({"ok": True, "message": msg})
            messages.success(request, msg)
            return redirect("shared-lists")
        if request.headers.get("X-Requested-With") == "fetch" and errors:
            return JsonResponse({"ok": False, "errors": errors}, status=400)
    return render(
        request,
        "sharing/share_form.html",
        {"kind": kind, "target": target, "errors": errors},
    )


@login_required
def bubble_share(request):
    raw_ids = {value for value in request.GET.get("topics", "").split(",") if value.isdigit()}
    raw_material_ids = {value for value in request.GET.get("materials", "").split(",") if value.isdigit()}
    if request.method == "POST":
        posted_ids = {value for item in request.POST.getlist("topic_ids") for value in item.split(",") if value.isdigit()}
        raw_ids = posted_ids or raw_ids
        raw_material_ids = {value for item in request.POST.getlist("material_ids") for value in item.split(",") if value.isdigit()} or raw_material_ids
    topics = list(Topic.objects.filter(pk__in=[int(value) for value in raw_ids], subject__owner=request.user).select_related("subject").order_by("subject__name", "order", "name"))
    materials = list(Material.objects.filter(pk__in=[int(value) for value in raw_material_ids], owner=request.user).select_related("topic", "topic__subject").order_by("topic__subject__name", "topic__name", "title"))
    errors = []
    if request.method == "POST":
        password = request.POST.get("password", "").strip()
        confirm = request.POST.get("password_confirm", "").strip()
        title = request.POST.get("title", "").strip()
        recipient_ids = {value for value in request.POST.get("recipient_ids", "").split(",") if value.isdigit()}
        recipients = list(User.objects.filter(pk__in=[int(value) for value in recipient_ids], is_active=True).exclude(pk=request.user.pk))
        # Expand topics to their documents: only share documents
        expanded_materials = list(materials)
        for topic in topics:
            expanded_materials.extend(list(Material.objects.filter(topic=topic).select_related("topic")))
        # Deduplicate by pk
        deduped = {m.pk: m for m in expanded_materials}
        all_materials = list(deduped.values())
        if not topics and not materials: errors.append("Pick at least one topic or document to share.")
        elif not all_materials: errors.append("Selected topics have no documents to share. Add documents first.")
        if password and len(password) < SHARE_MIN_PASSWORD_LEN: errors.append(f"Password must be at least {SHARE_MIN_PASSWORD_LEN} characters.")
        elif password != confirm: errors.append("Passwords do not match.")
        if not recipients: errors.append("Pick at least one person to share with.")
        if not errors:
            # Group all documents shared at once, even without password, for title grouping
            password_group = uuid.uuid4() if (password or title or len(all_materials) > 1) else None
            group_title = title or f"Shared documents ({len(all_materials)} files)"
            created = skipped = 0
            newly_shared_materials = set()
            for material in all_materials:
                for user in recipients:
                    share, was_created = SharedAccess.objects.get_or_create(
                        shared_by=request.user, shared_with=user, material=material
                    )
                    if not was_created:
                        skipped += 1
                        # The document already lives in an earlier bubble.
                        # Never rip it out of that bubble: silently
                        # re-sharing must not make previously shared
                        # documents disappear from the shared lists.
                        continue
                    created += 1
                    newly_shared_materials.add(material.pk)
                    share.set_password(password)
                    share.password_group = password_group
                    share.group_title = group_title
                    share.save(update_fields=["password", "password_group", "group_title"])
            total_docs = len(newly_shared_materials)
            msg = (
                f"Shared {total_docs} document{'s' if total_docs != 1 else ''} with {len(recipients)} people."
                if created
                else "Nothing new shared."
            )
            if skipped:
                msg += f" {skipped} already had access."
            if request.headers.get("X-Requested-With") == "fetch":
                return JsonResponse({"ok": True, "message": msg})
            messages.success(request, msg)
            return redirect("shared-lists")
        if request.headers.get("X-Requested-With") == "fetch" and errors:
            return JsonResponse({"ok": False, "errors": errors}, status=400)
    # Preview: only documents that will actually be shared (topics expanded)
    preview_expanded = list(materials)
    for topic in topics:
        preview_expanded.extend(list(Material.objects.filter(topic=topic).select_related("topic", "topic__subject")))
    preview_deduped = {m.pk: m for m in preview_expanded}
    preview_materials = sorted(preview_deduped.values(), key=lambda m: (m.topic.subject.name, m.topic.name, m.title))
    selected_topic_ids = ",".join(str(topic.pk) for topic in topics)
    selected_material_ids = ",".join(str(material.pk) for material in materials)
    return render(request, "sharing/bubble_share.html", {"topics": topics, "materials": materials, "preview_materials": preview_materials, "errors": errors, "selected_topic_ids": selected_topic_ids, "selected_material_ids": selected_material_ids})


SHARED_COLLECTIONS_PAGE_SIZE = 5
"""Collections ("bubbles") shown per shared section before See more."""


def _share_documents(share):
    """Return every Material covered by a single SharedAccess row."""
    if share.subject_id:
        return list(Material.objects.filter(topic__subject_id=share.subject_id).select_related("topic", "topic__subject"))
    if share.topic_id:
        return list(share.topic.materials.all().select_related("topic", "topic__subject"))
    if share.material_id:
        m = share.material
        m.topic  # ensure prefetched via select_related in queryset
        return [m]
    return []


def _is_share_unlocked(share):
    """True when the share grants read access right now."""
    return not share.password or share.unlocked_at is not None


def _collection_key(share):
    """Stable grouping key so rows from one sharing action merge.

    The password_group is a per-action batch id: every row created by a
    single Share submit carries the same value, so it always identifies the
    collection — including unprotected batches.  Rows without one (legacy
    data) fall back to title + sharer so their contents still group.
    """
    title = (share.group_title or "").strip().lower()
    base = f"title:{title}|by:{share.shared_by_id}" if title else f"share-{share.pk}"
    if share.password_group:
        return f"{base}|pg:{share.password_group}"
    return base


def _given_collection_key(share):
    """Grouping key for the 'Shared by me' section.

    All recipients of the same sharing action merge into one row so the
    page lists collections, not individual shares.  Separate actions stay
    separate even when they reuse the same title.
    """
    title = (share.group_title or "").strip().lower()
    base = f"title:{title}|by:{share.shared_by_id}" if title else f"share-{share.pk}"
    if share.password_group:
        return f"{base}|pg:{share.password_group}"
    return base


def _group_anchor(key):
    """Stable, URL/HTML-safe anchor id for a collection group on /shared/."""
    return "collection-" + re.sub(r"[^0-9a-zA-Z]+", "-", key).strip("-")


def _aggregate_group(group):
    """Populate topics/docs inside a collection group, newest-first."""
    doc_time = {}
    share_ids_per_doc = {}
    all_share_ids = []
    for item in group["items"]:
        share_pk = item["share"].pk
        all_share_ids.append(share_pk)
        for doc in item["docs"]:
            ts = item["share"].created_at
            prev = doc_time.get(doc.pk)
            if prev is None or ts > prev[1]:
                doc_time[doc.pk] = (doc, ts)
            # Track every share row covering this doc (needed so
            # "Shared by me" revoke removes all recipients, not just one).
            share_ids_per_doc.setdefault(doc.pk, set()).add(share_pk)
    docs = sorted(
        doc_time.values(),
        key=lambda x: (x[1], x[0].uploaded_at, x[0].pk),
        reverse=True,
    )

    topic_map = {}
    topic_latest = {}
    for doc, ts in docs:
        t = doc.topic
        if t.pk not in topic_map:
            topic_map[t.pk] = {"topic": t, "docs": []}
            topic_latest[t.pk] = ts
        topic_map[t.pk]["docs"].append(doc)
        if ts > topic_latest[t.pk]:
            topic_latest[t.pk] = ts

    group["topics"] = sorted(
        topic_map.values(),
        key=lambda x: (topic_latest[x["topic"].pk], x["topic"].pk),
        reverse=True,
    )
    group["doc_count"] = len(docs)
    # Attach every covering share pk to each doc so bulk revoke/delete
    # removes all rows for that document, not just one recipient's row.
    for doc, _ts in docs:
        ids = sorted(share_ids_per_doc.get(doc.pk, set()))
        doc.all_share_ids = ",".join(str(i) for i in ids)
        # Keep single-doc share_pk for backwards compat (received side).
        if not getattr(doc, "share_pk", None):
            doc.share_pk = ids[0] if ids else None
        elif len(ids) > 1 and str(doc.share_pk) not in doc.all_share_ids.split(","):
            doc.all_share_ids = ",".join(
                sorted(set(doc.all_share_ids.split(",") + [str(doc.share_pk)]), key=int)
            )
    group["all_share_ids"] = sorted(set(all_share_ids))
    # Sorting metadata — newest share time first; tiebreak on the share row
    # pk itself so recency order follows the actions, not the documents.
    group["_sort_ts"] = max(
        (item["share"].created_at for item in group["items"]),
        default=group["password_share"].created_at,
    )
    group["_sort_pk"] = max(
        (item["share"].pk for item in group["items"]),
        default=group["password_share"].pk,
    )


def _mark_collection_pages(groups, step=None):
    """Mark which collections fall beyond the first ``step`` collections.

    Both shared sections page through whole collections ("bubbles"): the
    newest five collections stay visible (in recency order) and everything
    else hides behind "See more", which reveals five more collections at a
    time.  Returns the totals used by the counter and the See more button.
    """
    if step is None:
        step = SHARED_COLLECTIONS_PAGE_SIZE
    total = len(groups)
    visible = 0
    for index, group in enumerate(groups):
        group["is_extra"] = index >= step
        if not group["is_extra"]:
            visible += 1
    return {"total": total, "visible": visible, "remaining": total - visible}


@login_required
def shared_lists(request):
    user = request.user

    # ── Fetch raw share rows ──────────────────────────────────────────
    received_qs = (
        SharedAccess.objects.filter(shared_with=user)
        .select_related("shared_by", "subject", "topic", "material")
        .order_by("-created_at", "-pk")
    )
    given_qs = (
        SharedAccess.objects.filter(shared_by=user)
        .select_related("shared_with", "subject", "topic", "material")
        .order_by("-created_at", "-pk")
    )

    # ── Build received groups ─────────────────────────────────────────
    received_groups = []
    received_map = {}
    for share in received_qs:
        docs = _share_documents(share)
        for doc in docs:
            doc.share_pk = share.pk
        unlocked = _is_share_unlocked(share)
        key = _collection_key(share)

        if key not in received_map:
            grp = {
                "key": key,
                "items": [],
                "title": share.group_title or "",
                "has_password": bool(share.password),
                "all_unlocked": unlocked,
                "password_share": share,  # may be replaced below
            }
            received_map[key] = grp
            received_groups.append(grp)
        else:
            grp = received_map[key]

        if share.group_title and not grp["title"]:
            grp["title"] = share.group_title
        grp["items"].append({"share": share, "docs": docs, "unlocked": unlocked})
        grp["all_unlocked"] = grp["all_unlocked"] and unlocked
        # Any password in the batch means the collection is protected.
        grp["has_password"] = grp["has_password"] or bool(share.password)

    # Finalize received groups: aggregate topics/docs, pick lock share
    for grp in received_groups:
        _aggregate_group(grp)
        grp["locked"] = grp["has_password"] and not grp["all_unlocked"]
        if grp["locked"]:
            # Point at a still-locked share so the "Enter password" link
            # opens the correct lock page (never an already-unlocked row).
            for item in grp["items"]:
                if not item["unlocked"]:
                    grp["password_share"] = item["share"]
                    break
            # A locked collection reveals nothing — not even topic names or
            # document titles — until its password is entered.
            grp["topics"] = []
            grp["items"] = []

    # Sort newest first
    received_groups.sort(key=lambda g: (g["_sort_ts"], g["_sort_pk"]), reverse=True)
    # Stable anchor ids so /shared/#collection-… can scroll to a group.
    for grp in received_groups:
        grp["anchor"] = _group_anchor(grp["key"])
    # Five collections per page — whole bubbles, newest first.
    received_paging = _mark_collection_pages(received_groups)

    # ── Build given groups ────────────────────────────────────────────
    given_groups = []
    given_map = {}
    for share in given_qs:
        docs = _share_documents(share)
        for doc in docs:
            doc.share_pk = share.pk
        key = _given_collection_key(share)

        if key not in given_map:
            grp = {
                "key": key,
                "items": [],
                "title": share.group_title or "",
                "password_share": share,
                "has_password": bool(share.password),
                "shared_with_users": [],
                "_seen": set(),
            }
            given_map[key] = grp
            given_groups.append(grp)
        else:
            grp = given_map[key]

        if share.group_title and not grp["title"]:
            grp["title"] = share.group_title
        grp["items"].append({"share": share, "docs": docs})
        grp["has_password"] = grp.get("has_password", False) or bool(share.password)
        if share.shared_with_id not in grp["_seen"]:
            grp["_seen"].add(share.shared_with_id)
            grp["shared_with_users"].append(share.shared_with)

    for grp in given_groups:
        _aggregate_group(grp)
        grp.pop("_seen", None)

    given_groups.sort(key=lambda g: (g["_sort_ts"], g["_sort_pk"]), reverse=True)
    for grp in given_groups:
        grp["anchor"] = _group_anchor(grp["key"])
    given_paging = _mark_collection_pages(given_groups)

    my_topics = (
        Topic.objects.filter(subject__owner=user)
        .select_related("subject")
        .order_by("subject__class_level", "subject__name", "order", "name")
    )
    my_class_levels = list(
        Subject.objects.filter(owner=user).values_list("class_level", flat=True).distinct()
    )

    return render(
        request,
        "sharing/shared_lists.html",
        {
            "received_groups": received_groups,
            "given_groups": given_groups,
            "given": given_groups,
            "received_paging": received_paging,
            "given_paging": given_paging,
            "my_topics": my_topics,
            "my_class_levels": my_class_levels,
            "received_total": len(received_groups),
            "given_total": len(given_groups),
        },
    )


@login_required
def shared_combined(request):
    """Open multiple shared docs in the combined viewer.

    Every requested material is checked: the user must own it OR hold an
    unlocked (no-password, or already-unlocked) share for it.  If ANY
    requested material is locked the user is bounced to the lock page.
    """
    raw_ids = [int(v) for v in request.GET.get("materials", "").split(",") if v.strip().isdigit()]
    if not raw_ids:
        messages.error(request, "No documents selected.")
        return redirect("shared-lists")

    materials = list(
        Material.objects.select_related("topic", "topic__subject")
        .filter(pk__in=raw_ids)
        .order_by("topic__subject__name", "topic__name", "title")
    )

    # Quick look-ups for share matching
    wanted_topic_ids = {m.topic_id for m in materials}
    wanted_subject_ids = {m.topic.subject_id for m in materials}

    # Build unlocked-share coverage for this user (supports legacy
    # topic/subject rows as well as current material-level rows).
    unlocked_shares = list(
        SharedAccess.objects.filter(shared_with=request.user)
        .filter(Q(password="") | Q(unlocked_at__isnull=False))
        .filter(
            Q(material_id__in=raw_ids)
            | Q(topic_id__in=wanted_topic_ids)
            | Q(subject_id__in=wanted_subject_ids)
        )
    )
    unlocked_material_ids = {s.material_id for s in unlocked_shares if s.material_id}
    unlocked_topic_ids = {s.topic_id for s in unlocked_shares if s.topic_id}
    unlocked_subject_ids = {s.subject_id for s in unlocked_shares if s.subject_id}

    accessible = []
    for mat in materials:
        if mat.owner_id == request.user.id:
            accessible.append(mat)
        elif mat.pk in unlocked_material_ids:
            accessible.append(mat)
        elif mat.topic_id in unlocked_topic_ids:
            accessible.append(mat)
        elif mat.topic.subject_id in unlocked_subject_ids:
            accessible.append(mat)

    if not accessible:
        # All locked — send to the password page for the first locked share
        locked_share = (
            SharedAccess.objects.filter(shared_with=request.user)
            .exclude(password="")
            .filter(unlocked_at__isnull=True)
            .filter(
                Q(material_id__in=raw_ids)
                | Q(topic_id__in=wanted_topic_ids)
                | Q(subject_id__in=wanted_subject_ids)
            )
            .select_related("shared_by")
            .first()
        )
        if locked_share:
            return redirect("shared-open", pk=locked_share.pk)
        messages.error(request, "Choose at least one unlocked shared document.")
        return redirect("shared-lists")

    selected_ids = {m.pk for m in accessible}
    topic_ids = list(dict.fromkeys(m.topic_id for m in accessible))
    selected_materials = (
        Material.objects.filter(pk__in=selected_ids)
        .order_by("-uploaded_at", "-pk")
    )
    topics = list(
        Topic.objects.filter(pk__in=topic_ids)
        .prefetch_related(Prefetch("materials", queryset=selected_materials))
    )
    # Display newest-first: topics (and the documents inside them) are
    # ordered by the recency of the documents being shown.
    topics.sort(
        key=lambda t: max(m.uploaded_at for m in t.materials.all()),
        reverse=True,
    )
    _convert_pending(topics)
    # The multi-document viewer is reused by the dashboard and the shared
    # page. Keep its back link in context instead of always pointing at the
    # shared list.
    back_label = "Back to shared list"
    back_url = reverse("shared-lists")
    if request.GET.get("from") == "topics":
        back_label = "Back to topics"
        subject_id = request.GET.get("subject", "")
        subject = None
        if subject_id.isdigit():
            subject = (
                Subject.objects.filter(pk=int(subject_id), owner=request.user)
                .only("pk")
                .first()
            )
        back_url = (
            reverse("dashboard-subject", args=[subject.pk])
            if subject
            else reverse("dashboard")
        )
    return render(
        request,
        "sharing/shared_viewer.html",
        {
            "share": None,
            "topics": topics,
            "combined": True,
            "back_url": back_url,
            "back_label": back_label,
            "ai_subject_id": accessible[0].topic.subject_id,
            "ai_title": "Selected shared documents",
        },
    )


COMBINE_DEFAULT_TOPIC_NAME = "Shared material"


def _copy_material(material, dest_topic, user):
    clone = Material(
        topic=dest_topic,
        owner=user,
        title=material.title,
        file_type=material.file_type,
    )
    if material.file:
        with material.file.open("rb") as src:
            clone.file.save(os.path.basename(material.file.name), File(src), save=False)
    if material.converted_pdf:
        with material.converted_pdf.open("rb") as src:
            clone.converted_pdf.save(
                os.path.basename(material.converted_pdf.name), File(src), save=False
            )
    clone.save()


@login_required
@require_POST
def shared_combine(request):
    raw_ids = {
        i for i in request.POST.get("material_ids", "").split(",") if i.strip().isdigit()
    }
    if not raw_ids:
        messages.error(request, "Tick at least one document to combine.")
        return redirect("shared-lists")

    wanted = [int(i) for i in raw_ids]
    allowed_topic_ids = set()
    allowed_subject_ids = set()
    for share in SharedAccess.objects.filter(shared_with=request.user):
        if share.password and share.unlocked_at is None:
            continue
        if share.subject_id:
            allowed_subject_ids.add(share.subject_id)
        elif share.topic_id:
            allowed_topic_ids.add(share.topic_id)

    allowed_material_ids = {
        share.material_id
        for share in SharedAccess.objects.filter(shared_with=request.user)
        .filter(Q(password="") | Q(unlocked_at__isnull=False))
        if share.material_id
    }

    materials = list(
        Material.objects.select_related("topic", "topic__subject")
        .filter(pk__in=wanted)
        .filter(
            Q(topic_id__in=allowed_topic_ids)
            | Q(topic__subject_id__in=allowed_subject_ids)
            | Q(pk__in=allowed_material_ids)
        )
    )
    denied = len(wanted) - len(materials)

    errors = []
    dest_spec = None
    if request.POST.get("destination") == "existing":
        topic_id = request.POST.get("topic_id", "")
        dest_topic = None
        if topic_id.isdigit():
            dest_topic = (
                Topic.objects.select_related("subject")
                .filter(pk=int(topic_id), subject__owner=request.user)
                .first()
            )
        if dest_topic is None:
            errors.append("Choose one of your own topics to combine into.")
        else:
            dest_spec = {"topic": dest_topic}
    else:
        name = request.POST.get("subject_name", "").strip()
        class_level = request.POST.get("class_level", "").strip()
        color = request.POST.get("color", "").strip()
        topic_name = (
            request.POST.get("topic_name", "").strip() or COMBINE_DEFAULT_TOPIC_NAME
        )
        if not name or not class_level:
            errors.append("Give the new subject a name and class.")
        else:
            dest_spec = {"name": name, "class_level": class_level, "color": color, "topic_name": topic_name}

    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect("shared-lists")

    if not materials:
        messages.error(
            request,
            "Nothing combined \u2014 open and unlock the protected shares first, "
            "then pick their documents.",
        )
        return redirect("shared-lists")

    if "topic" in dest_spec:
        dest_topic = dest_spec["topic"]
    else:
        spec = dest_spec
        subject, _ = Subject.objects.get_or_create(
            owner=request.user,
            name=spec["name"],
            class_level=spec["class_level"],
            defaults={"color": spec["color"] if spec["color"].startswith("#") else "#6366f1"},
        )
        dest_topic, _ = Topic.objects.get_or_create(
            subject=subject,
            name=spec["topic_name"],
            defaults={"order": subject.topics.count()},
        )

    for material in materials:
        _copy_material(material, dest_topic, request.user)

    msg = (
        f"Copied {len(materials)} document{'s' if len(materials) != 1 else ''} into "
        f"\u201c{dest_topic.subject.name} \u2192 {dest_topic.name}\u201d. "
        "Find it under My Subjects."
    )
    if denied:
        msg += (
            f" {denied} selected document{'s' if denied != 1 else ''} skipped "
            "\u2014 protected or unavailable."
        )
    messages.success(request, msg)
    # Redirect directly to the viewer for the destination so user sees the copied docs immediately
    if "topic" in dest_spec:
        return redirect("topic-viewer", topic_id=dest_topic.pk)
    return redirect("subject-viewer", subject_id=dest_topic.subject_id)


@login_required
def shared_open(request, pk):
    share = _get_share_for(request, pk)
    if request.GET.get("unlock") == "1" and not (
        share.password and share.unlocked_at is None
    ):
        # "Enter password" must land on a password form, never a viewer:
        # forward to a still-locked share from the same unlockable batch.
        sibling = _locked_batch_sibling(request.user, share)
        if sibling is not None and sibling.pk != share.pk:
            return redirect(f"{reverse('shared-open', args=[sibling.pk])}?unlock=1")
    if share.password and share.unlocked_at is None:
        return render(request, "sharing/shared_lock.html", {"share": share})
    # Read-only view of the shared documents, newest uploaded first.
    ordered_materials = Material.objects.order_by("-uploaded_at", "-pk")
    if share.subject:
        topics = list(
            share.subject.topics.prefetch_related(
                Prefetch("materials", queryset=ordered_materials)
            )
        )
    else:
        topic_obj = share.topic or share.material.topic
        topics = list(
            Topic.objects.filter(pk=topic_obj.pk).prefetch_related(
                Prefetch("materials", queryset=ordered_materials)
            )
        )
    ai_subject_id = share.subject_id
    if not ai_subject_id:
        ai_subject_id = share.topic.subject_id if share.topic_id else share.material.topic.subject_id
    _convert_pending(topics)
    return render(
        request,
        "sharing/shared_viewer.html",
        {
            "share": share,
            "topics": topics,
            "back_url": reverse("shared-lists"),
            "back_label": "Back to shared list",
            "ai_subject_id": ai_subject_id,
            "ai_title": share.target_title,
        },
    )


@login_required
@require_POST
def shared_unlock(request, pk):
    share = _get_share_for(request, pk)
    if share.check_password(request.POST.get("password", "")):
        unlocked_at = timezone.now()
        if share.password_group:
            SharedAccess.objects.filter(
                shared_with=request.user,
                password_group=share.password_group,
            ).update(unlocked_at=unlocked_at)
        elif share.unlocked_at is None:
            share.unlocked_at = unlocked_at
            share.save(update_fields=["unlocked_at"])
        # Back to the shared page, anchored to the collection just unlocked —
        # entering the password must not open a viewer.
        return redirect(
            f"{reverse('shared-lists')}#{_group_anchor(_collection_key(share))}"
        )
    messages.error(request, "Incorrect password. Try again.")
    return redirect("shared-open", pk=share.pk)


@login_required
@require_POST
def shared_revoke(request, pk):
    share = get_object_or_404(SharedAccess, pk=pk)
    is_owner = share.shared_by_id == request.user.id
    is_recipient = share.shared_with_id == request.user.id
    if not (is_owner or is_recipient):
        raise Http404
    title = share.target_title
    revoked_username = share.shared_with.username
    share.delete()
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "username": revoked_username})
    if is_owner:
        messages.success(request, f"Revoked access to \u201c{title}\u201d.")
    else:
        messages.success(request, f"Removed \u201c{title}\u201d from your shared list.")
    return redirect("shared-lists")


def _posted_id_set(request, name):
    return {
        int(value)
        for item in request.POST.getlist(name)
        for value in item.split(",")
        if value.strip().isdigit()
    }


@login_required
@require_POST
def shared_delete_selected(request):
    share_ids = _posted_id_set(request, "share_ids")
    shares = SharedAccess.objects.filter(
        pk__in=share_ids,
        shared_with=request.user,
    )
    removed = shares.count()
    shares.delete()
    messages.success(
        request,
        f"Removed {removed} shared document access item{'s' if removed != 1 else ''}.",
    )
    return redirect("shared-lists")


@login_required
@require_POST
def shared_revoke_selected(request):
    share_ids = _posted_id_set(request, "share_ids")
    shares = SharedAccess.objects.filter(
        pk__in=share_ids,
        shared_by=request.user,
    )
    revoked = shares.count()
    shares.delete()
    messages.success(
        request,
        f"Revoked {revoked} shared document access item{'s' if revoked != 1 else ''}.",
    )
    return redirect("shared-lists")


def _ai_accessible_subject(request, subject_id):
    """Subject must be owned by the user or shared (unlocked if password-protected)."""
    subject = get_object_or_404(Subject.objects.select_related("owner"), pk=subject_id)
    if subject.owner_id == request.user.id:
        return subject
    is_shared = (
        SharedAccess.objects.filter(shared_with=request.user)
        .filter(Q(password="") | Q(unlocked_at__isnull=False))
        .filter(
            Q(subject=subject)
            | Q(topic__subject=subject)
            | Q(material__topic__subject=subject)
        )
        .exists()
    )
    if not is_shared:
        raise Http404
    return subject


def _extract_question_history(request):
    """Returns ((question, history, data), None) or (None, JsonResponse)."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "Invalid request body."}, status=400)

    question = str(data.get("question") or "").strip()
    if not question:
        return None, JsonResponse({"error": "Type a question first."}, status=400)
    if len(question) > ai.MAX_QUESTION_CHARS:
        return None, JsonResponse({"error": "Question is too long."}, status=400)
    history = data.get("history")
    if not isinstance(history, list):
        history = []
    return (question, history, data), None


@login_required
@require_POST
def ai_ask(request):
    payload, error = _extract_question_history(request)
    if error:
        return error
    question, history, data = payload

    try:
        subject_id = int(data.get("subject_id"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Open a subject first, then ask the assistant."}, status=400
        )
    try:
        subject = _ai_accessible_subject(request, subject_id)
    except Http404:
        return JsonResponse(
            {"error": "That subject isn't available to you."}, status=404
        )
    if subject.owner_id == request.user.id:
        topics = list(subject.topics.prefetch_related("materials"))
    else:
        # Recipients' AI context is limited to unlocked documents only.
        _, topics = _topics_for_shared_subject(request.user, subject)

    if ai.throttled(request.user.pk):
        return JsonResponse(
            {"error": "You're sending questions too fast. Wait a minute and try again."},
            status=429,
        )

    context = ai.build_context(topics)
    try:
        answer = ai.ask_gemini(question, history=history, context=context)
    except ai.AiNotConfigured as exc:
        return JsonResponse(
            {"error": str(exc) or AI_NOT_CONFIGURED_DEFAULT}, status=503
        )
    except ai.AiUpstreamError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"answer": answer})


@login_required
@require_POST
def ai_quick_ask(request):
    """Ask the assistant WITHOUT any study-material context."""
    payload, error = _extract_question_history(request)
    if error:
        return error
    question, history, _data = payload

    if ai.throttled(request.user.pk):
        return JsonResponse(
            {"error": "You're sending questions too fast. Wait a minute and try again."},
            status=429,
        )

    try:
        answer = ai.ask_gemini(question, history=history)
    except ai.AiNotConfigured as exc:
        return JsonResponse(
            {"error": str(exc) or AI_NOT_CONFIGURED_DEFAULT}, status=503
        )
    except ai.AiUpstreamError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"answer": answer})


SEARCH_MIN_CHARS = 2
SEARCH_SNIPPET_RADIUS = 70
SEARCH_LAZY_INDEX_LIMIT = 20


def _unlocked_share_scope(user):
    """Maps of subject_id / topic_id / material_id -> share pk for shares the user can read."""
    shares = SharedAccess.objects.filter(shared_with=user).filter(
        Q(password="") | Q(unlocked_at__isnull=False)
    )
    subject_shares = {s.subject_id: s.pk for s in shares.exclude(subject=None)}
    topic_shares = {t.topic_id: t.pk for t in shares.exclude(topic=None)}
    material_shares = {m.material_id: m.pk for m in shares.exclude(material=None)}
    return subject_shares, topic_shares, material_shares


def _snippet_around(body, q, radius=SEARCH_SNIPPET_RADIUS):
    idx = body.lower().find(q.lower())
    if idx < 0:
        text = body[: radius * 2].strip()
    else:
        start = max(0, idx - radius)
        end = min(len(body), idx + len(q) + radius)
        text = body[start:end].strip()
    prefix = "\u2026 " if idx > 0 else ""
    suffix = " \u2026" if (idx < 0 and len(body) > radius * 2) or (
        idx >= 0 and idx + len(q) + radius < len(body)
    ) else ""
    return f"{prefix}{text}{suffix}"


@login_required
@require_GET
def global_search(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < SEARCH_MIN_CHARS:
        return JsonResponse({"q": q, "groups": []})

    subject_shares, topic_shares, material_shares = _unlocked_share_scope(request.user)
    own_subject_ids = set(
        Subject.objects.filter(owner=request.user).values_list("pk", flat=True)
    )
    all_subject_ids = own_subject_ids | set(subject_shares)

    def topic_url(topic_id, subject_id, material_id=None):
        if subject_id in own_subject_ids:
            return f"{reverse('subject-viewer', args=[subject_id])}#topic-{topic_id}"
        if material_id is not None and material_id in material_shares:
            return f"{reverse('shared-open', args=[material_shares[material_id]])}#topic-{topic_id}"
        if subject_id in subject_shares:
            share_pk = subject_shares[subject_id]
        elif topic_id in topic_shares:
            share_pk = topic_shares[topic_id]
        else:
            return ""
        return f"{reverse('shared-open', args=[share_pk])}#topic-{topic_id}"

    def doc_url(material):
        # Material-level share takes precedence
        if material.pk in material_shares:
            return f"{reverse('shared-open', args=[material_shares[material.pk]])}#topic-{material.topic_id}"
        return topic_url(material.topic_id, material.topic.subject_id)

    material_scope = Q(topic__subject_id__in=all_subject_ids) | Q(topic_id__in=topic_shares) | Q(pk__in=material_shares)

    # Lazy backfill: index a few not-yet-indexed documents per request.
    indexed_ids = MaterialTextIndex.objects.values_list("material_id", flat=True)
    missing = Material.objects.filter(material_scope).exclude(pk__in=indexed_ids)[
        :SEARCH_LAZY_INDEX_LIMIT
    ]
    for material in missing:
        index_material(material)

    groups = []

    subjects = Subject.objects.select_related("owner").filter(
        pk__in=all_subject_ids,
        name__icontains=q,
    )[:6]
    class_matches = Subject.objects.filter(
        pk__in=all_subject_ids, class_level__icontains=q
    ).exclude(name__icontains=q)[:6]
    subject_items = [
        {
            "title": str(s),
            "subtitle": (
                f"shared by @{s.owner.username}"
                if s.owner_id != request.user.id
                else "your subject"
            ),
            "icon": "\U0001f4da",
            "url": (
                reverse("subject-viewer", args=[s.pk])
                if s.pk in own_subject_ids
                else reverse("shared-open", args=[subject_shares[s.pk]])
            ),
        }
        for s in list(subjects) + list(class_matches)
    ]
    if subject_items:
        groups.append({"label": "Subjects", "items": subject_items[:6]})

    topics = Topic.objects.select_related("subject", "subject__owner").filter(
        Q(subject_id__in=own_subject_ids)
        | Q(subject_id__in=subject_shares)
        | Q(pk__in=topic_shares),
        name__icontains=q,
    )[:8]
    topic_items = [
        {
            "title": t.name,
            "subtitle": str(t.subject),
            "icon": "\U0001f5c2\ufe0f",
            "url": topic_url(t.pk, t.subject_id),
        }
        for t in topics
    ]
    if topic_items:
        groups.append({"label": "Topics", "items": topic_items})

    documents = (
        Material.objects.select_related("topic", "topic__subject")
        .filter(material_scope & Q(title__icontains=q))[:8]
    )
    doc_items = [
        {
            "title": d.title,
            "subtitle": f"{d.topic.name} \u00b7 {d.get_file_type_display()}",
            "icon": d.icon,
            "url": doc_url(d),
        }
        for d in documents
    ]
    if doc_items:
        groups.append({"label": "Documents", "items": doc_items})

    passage_rows = (
        MaterialTextIndex.objects.select_related(
            "material", "material__topic", "material__topic__subject"
        )
        .filter(
            Q(material__topic__subject_id__in=all_subject_ids)
            | Q(material__topic_id__in=topic_shares)
            | Q(material_id__in=material_shares)
        )
        .exclude(body="")
        .filter(body__icontains=q)[:30]
    )
    passage_items = []
    for row in passage_rows:
        material = row.material
        passage_items.append(
            {
                "title": material.title,
                "subtitle": f"{material.topic.name} \u00b7 inside the document",
                "icon": material.icon,
                "url": doc_url(material),
                "snippet": _snippet_around(row.body, q),
            }
        )
        if len(passage_items) >= 6:
            break
    if passage_items:
        groups.append({"label": "Inside documents", "items": passage_items})

    return JsonResponse({"q": q, "groups": groups})


def protected_media(request, path):
    """
    Serve MEDIA files with permission checks for sensitive material files.
    - avatars/ are public (profile pictures)
    - materials/ and converted/ require owner or unlocked share
    - other paths denied
    """
    import mimetypes
    from pathlib import Path

    from django.conf import settings

    # Normalize path
    # Prevent directory traversal
    if ".." in path or path.startswith("/"):
        raise Http404

    # Public avatars - allow any authenticated user; anon gets 404 to avoid enumeration
    # Actually avatars are shown in share lists (need to be visible to any logged-in user)
    if path.startswith("avatars/"):
        # Allow if user is authenticated or if fetching own avatar? For simplicity allow all
        full_path = Path(settings.MEDIA_ROOT) / path
        if not full_path.is_file():
            raise Http404
        ctype, _ = mimetypes.guess_type(str(full_path))
        return FileResponse(open(full_path, "rb"), content_type=ctype or "application/octet-stream")

    # For material files, enforce permission
    if path.startswith("materials/") or path.startswith("converted/"):
        # Find material by file field
        material = (
            Material.objects.filter(Q(file=path) | Q(converted_pdf=path))
            .select_related("topic__subject", "owner")
            .first()
        )
        if not material:
            # Fallback: try to find by basename? but strict
            raise Http404
        # Check permission
        user = request.user
        if not user.is_authenticated:
            raise Http404
        if material.owner_id == user.id:
            # Owner can always access
            pass
        else:
            has_access = (
                SharedAccess.objects.filter(shared_with=user)
                .filter(Q(password="") | Q(unlocked_at__isnull=False))
                .filter(
                    Q(subject_id=material.topic.subject_id)
                    | Q(topic_id=material.topic_id)
                    | Q(material_id=material.pk)
                )
                .exists()
            )
            if not has_access:
                raise Http404
        full_path = Path(settings.MEDIA_ROOT) / path
        if not full_path.is_file():
            raise Http404
        ctype, _ = mimetypes.guess_type(str(full_path))
        # Security: prevent XSS for SVG etc. but allow pdf/image
        return FileResponse(open(full_path, "rb"), content_type=ctype or "application/octet-stream")

    # For any other media path, deny (or serve only if authenticated and file exists - but be safe)
    raise Http404
