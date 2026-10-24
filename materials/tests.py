import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import ai
from .models import Material, SharedAccess, Subject, Topic
from .views import _collection_key, _group_anchor

TEMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SharedCombineTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user("alice", password="test12345")
        self.recipient = User.objects.create_user("bob", password="test12345")
        self.stranger = User.objects.create_user("carol", password="test12345")
        self.subject = Subject.objects.create(
            owner=self.owner, name="Physics", class_level="Grade 10"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="Waves")
        self.material_a = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Wave notes",
            file=SimpleUploadedFile("notes.txt", b"wave notes"),
            file_type="doc",
        )
        self.material_b = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Wave slides",
            file=SimpleUploadedFile("slides.txt", b"wave slides"),
            file_type="doc",
        )
        self.client.force_login(self.recipient)

    def _share(self, *, with_topic=None, with_subject=None, password=""):
        share = SharedAccess(shared_by=self.owner, shared_with=self.recipient)
        if with_subject is not None:
            share.subject = with_subject
        else:
            share.topic = with_topic
        share.set_password(password)
        share.save()
        return share

    def _post_combine(self, **data):
        return self.client.post(reverse("shared-combine"), data)

    def _messages(self, response):
        return [m.message for m in response.wsgi_request._messages]

    def test_combine_single_document_only(self):
        share = self._share(with_topic=self.topic)
        response = self._post_combine(
            material_ids=str(self.material_a.pk),
            destination="new",
            subject_name="Exam prep",
            class_level="Grade 10",
            topic_name="From friends",
        )
        # After combine, user is taken directly to the viewer for the new subject
        self.assertEqual(response.status_code, 302)
        self.assertIn("/viewer/", response.url)
        new_subject = Subject.objects.get(owner=self.recipient, name="Exam prep")
        topic = new_subject.topics.get(name="From friends")
        titles = set(topic.materials.values_list("title", flat=True))
        self.assertEqual(titles, {"Wave notes"})
        copied = topic.materials.get()
        self.assertTrue(copied.file.read())
        self.assertNotEqual(copied.file.name, self.material_a.file.name)

    def test_combine_default_topic_name(self):
        share = self._share(with_topic=self.topic)
        self._post_combine(
            material_ids=str(self.material_a.pk),
            destination="new",
            subject_name="Mixed",
            class_level="Grade 11",
            topic_name="",
        )
        subject = Subject.objects.get(owner=self.recipient, name="Mixed")
        self.assertTrue(subject.topics.filter(name="Shared material").exists())

    def test_combine_documents_from_different_people(self):
        other_owner = User.objects.create_user("dave", password="test12345")
        other_subject = Subject.objects.create(
            owner=other_owner, name="Chemistry", class_level="Grade 10"
        )
        other_topic = Topic.objects.create(subject=other_subject, name="Acids")
        acid_doc = Material.objects.create(
            topic=other_topic,
            owner=other_owner,
            title="Acid notes",
            file=SimpleUploadedFile("acids.txt", b"acids"),
            file_type="doc",
        )
        self._share(with_topic=self.topic)
        SharedAccess.objects.create(
            shared_by=other_owner, shared_with=self.recipient, subject=other_subject
        )
        self._post_combine(
            material_ids=f"{self.material_b.pk},{acid_doc.pk}",
            destination="new",
            subject_name="Combined",
            class_level="Grade 10",
        )
        subject = Subject.objects.get(owner=self.recipient, name="Combined")
        titles = set(
            Material.objects.filter(topic__subject=subject).values_list("title", flat=True)
        )
        self.assertEqual(titles, {"Wave slides", "Acid notes"})

    def test_combine_into_existing_topic(self):
        my_subject = Subject.objects.create(
            owner=self.recipient, name="My folder", class_level="Grade 10"
        )
        my_topic = Topic.objects.create(subject=my_subject, name="Inbox")
        self._share(with_topic=self.topic)
        self._post_combine(
            material_ids=f"{self.material_a.pk},{self.material_b.pk}",
            destination="existing",
            topic_id=str(my_topic.pk),
        )
        self.assertEqual(my_topic.materials.count(), 2)

    def test_locked_share_hides_documents_until_unlocked_then_stays_unlocked(self):
        share = self._share(with_topic=self.topic, password="pass1234")

        page = self.client.get(reverse("shared-lists"))
        self.assertNotContains(page, "doc-check")
        self.assertContains(page, "locked")
        # The locked collection's topic and documents are not visible either.
        self.assertNotContains(page, "Waves")
        self.assertNotContains(page, "Wave notes")
        self.assertNotContains(page, "Wave slides")

        response = self._post_combine(
            material_ids=str(self.material_a.pk),
            destination="new",
            subject_name="Locked test",
            class_level="Grade 10",
        )
        self.assertRedirects(response, reverse("shared-lists"))
        self.assertFalse(
            Subject.objects.filter(owner=self.recipient, name="Locked test").exists()
        )

        wrong = self.client.post(
            reverse("shared-unlock", args=[share.pk]), {"password": "nope"}
        )
        self.assertEqual(wrong.status_code, 302)
        share.refresh_from_db()
        self.assertIsNone(share.unlocked_at)

        ok = self.client.post(
            reverse("shared-unlock", args=[share.pk]), {"password": "pass1234"}
        )
        # Unlocking goes back to the shared page, anchored to the collection
        # that was just unlocked — it does not pop open a viewer.
        self.assertEqual(
            ok.url,
            f"{reverse('shared-lists')}#{_group_anchor(_collection_key(share))}",
        )
        share.refresh_from_db()
        self.assertIsNotNone(share.unlocked_at)

        browser = Client()
        browser.force_login(self.recipient)
        opened = browser.get(reverse("shared-open", args=[share.pk]))
        self.assertEqual(opened.status_code, 200)
        self.assertTemplateUsed(opened, "sharing/shared_viewer.html")

        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "share-topic-check")
        self.assertContains(page, "doc-check")

        response = self._post_combine(
            material_ids=str(self.material_a.pk),
            destination="new",
            subject_name="Locked test",
            class_level="Grade 10",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/viewer/", response.url)
        subject = Subject.objects.get(owner=self.recipient, name="Locked test")
        self.assertEqual(
            Material.objects.filter(topic__subject=subject).count(), 1
        )

    def test_cannot_combine_documents_without_access(self):
        stranger_subject = Subject.objects.create(
            owner=self.stranger, name="Secret", class_level="Grade 12"
        )
        stranger_topic = Topic.objects.create(subject=stranger_subject, name="Hidden")
        secret_doc = Material.objects.create(
            topic=stranger_topic,
            owner=self.stranger,
            title="Secret doc",
            file=SimpleUploadedFile("secret.txt", b"secret"),
            file_type="doc",
        )
        self._share(with_topic=self.topic)
        response = self._post_combine(
            material_ids=f"{self.material_a.pk},{secret_doc.pk}",
            destination="new",
            subject_name="Sneaky",
            class_level="Grade 10",
        )
        msgs = self._messages(response)
        self.assertTrue(any("skipped" in m for m in msgs))
        subject = Subject.objects.get(owner=self.recipient, name="Sneaky")
        titles = set(
            Material.objects.filter(topic__subject=subject).values_list("title", flat=True)
        )
        self.assertEqual(titles, {"Wave notes"})

    def test_all_denied_documents_combine_nothing(self):
        stranger_subject = Subject.objects.create(
            owner=self.stranger, name="Secret", class_level="Grade 12"
        )
        stranger_topic = Topic.objects.create(subject=stranger_subject, name="Hidden")
        secret_doc = Material.objects.create(
            topic=stranger_topic,
            owner=self.stranger,
            title="Secret doc",
            file=SimpleUploadedFile("secret.txt", b"secret"),
            file_type="doc",
        )
        response = self._post_combine(
            material_ids=str(secret_doc.pk),
            destination="new",
            subject_name="Nope",
            class_level="Grade 10",
        )
        self.assertRedirects(response, reverse("shared-lists"))
        self.assertFalse(Subject.objects.filter(owner=self.recipient).exists())

    def test_requires_selection(self):
        response = self._post_combine(
            material_ids="",
            destination="new",
            subject_name="X",
            class_level="Y",
        )
        msgs = self._messages(response)
        self.assertTrue(any("Tick at least one document" in m for m in msgs))

    def test_bubble_share_clears_dashboard_selection_after_sharing(self):
        # The dashboard remembers ticked documents in localStorage; the
        # bubble-share form is flagged so share_form.js drops that remembered
        # selection once the documents are shared, and the dashboard re-syncs
        # when the browser restores it from the back/forward cache.
        response = self.client.get(reverse("bubble-share"))
        self.assertContains(response, 'data-clear-bubble-selection="1"')
        from django.contrib.staticfiles import finders

        js_path = finders.find("js/share_form.js")
        with open(js_path, encoding="utf-8") as handle:
            js = handle.read()
        self.assertIn('localStorage.removeItem("studyhub:bubble-selection")', js)

    def test_new_subject_fields_required(self):
        self._share(with_topic=self.topic)
        response = self._post_combine(
            material_ids=str(self.material_a.pk),
            destination="new",
            subject_name="   ",
            class_level="",
        )
        msgs = self._messages(response)
        self.assertTrue(any("name and class" in m for m in msgs))
        self.assertFalse(Subject.objects.exclude(owner=self.owner).exists())

    def test_shared_lists_page_shows_combine_ui(self):
        self._share(with_topic=self.topic)
        response = self.client.get(reverse("shared-lists"))
        self.assertContains(response, 'id="combine-form"')
        self.assertContains(response, "doc-check")
        self.assertContains(response, "share-topic-check")
        self.assertContains(response, "Wave notes")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SharedListLockAndOrderTests(TestCase):
    """Locked collections are listed recent-first but reveal nothing until unlocked."""

    def setUp(self):
        self.owner = User.objects.create_user("lockowner", password="test12345")
        self.recipient = User.objects.create_user("lockrecv", password="test12345")
        self.subject = Subject.objects.create(
            owner=self.owner, name="Physics", class_level="Grade 10"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="Optics")
        self.old_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Old locked notes",
            file=SimpleUploadedFile("old.txt", b"old"),
            file_type="doc",
        )
        self.new_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="New open notes",
            file=SimpleUploadedFile("new.txt", b"new"),
            file_type="doc",
        )
        self.locked_share = SharedAccess(
            shared_by=self.owner, shared_with=self.recipient, material=self.old_doc
        )
        self.locked_share.set_password("secret123")
        self.locked_share.group_title = "Old batch"
        self.locked_share.save()
        self.open_share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=self.new_doc,
            group_title="New batch",
        )
        # Make the lock strictly older so order is deterministic.
        from django.utils import timezone

        self.locked_share.created_at = timezone.now() - timezone.timedelta(days=3)
        self.locked_share.save(update_fields=["created_at"])
        self.client.force_login(self.recipient)

    def test_locked_contents_hidden_but_collection_listed(self):
        page = self.client.get(reverse("shared-lists"))
        # Both collections are listed recent-first...
        self.assertContains(page, "Old batch")
        self.assertContains(page, "New batch")
        self.assertContains(page, "New open notes")
        content = page.content.decode()
        self.assertLess(content.find("New batch"), content.find("Old batch"))
        # ...the locked collection shows its password prompt...
        self.assertContains(page, "Enter password")
        self.assertContains(page, "is-locked")
        # ...but none of its documents are visible or selectable.
        self.assertNotContains(page, "Old locked notes")
        self.assertNotContains(page, f'data-material-id="{self.old_doc.pk}"')
        self.assertContains(page, f'data-material-id="{self.new_doc.pk}"')
        # ...locked-only combined viewer bounces to the password page...
        response = self.client.get(
            reverse("shared-combined") + f"?materials={self.old_doc.pk}"
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.locked_share.pk), response.url)
        # ...and the subject viewer shows only the unlocked document.
        viewer = self.client.get(reverse("subject-viewer", args=[self.subject.pk]))
        self.assertEqual(viewer.status_code, 200)
        self.assertContains(viewer, "New open notes")
        self.assertNotContains(viewer, "Old locked notes")

    def test_unlock_reveals_locked_documents(self):
        self.client.post(
            reverse("shared-unlock", args=[self.locked_share.pk]),
            {"password": "secret123"},
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "share-child-check doc-check")
        self.assertContains(page, "Old locked notes")
        viewer = self.client.get(reverse("subject-viewer", args=[self.subject.pk]))
        self.assertContains(viewer, "Old locked notes")
        self.assertContains(viewer, "New open notes")

    def test_unlock_redirects_to_collection_on_shared_page(self):
        response = self.client.post(
            reverse("shared-unlock", args=[self.locked_share.pk]),
            {"password": "secret123"},
        )
        anchor = _group_anchor(_collection_key(self.locked_share))
        # Entering the password goes back to /shared/, anchored to the
        # unlocked collection — it never opens a viewer.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('shared-lists')}#{anchor}")
        # The shared page carries that anchor so the browser can scroll to it.
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, f'id="{anchor}"')
        # ...and the collection is unlocked in place, ready to be viewed there.
        self.assertContains(page, "Old locked notes")
        self.assertContains(page, f'data-material-id="{self.old_doc.pk}"')

    def test_locked_collection_can_be_selected_and_deleted(self):
        page = self.client.get(reverse("shared-lists"))
        # The locked collection exposes a collection-level checkbox that
        # carries its share ids so it can be removed without unlocking it...
        self.assertContains(page, f'data-share-ids="{self.locked_share.pk}"')
        # ...while its documents stay hidden and are not individually
        # selectable.
        self.assertNotContains(page, f'data-material-id="{self.old_doc.pk}"')
        response = self.client.post(
            reverse("shared-delete-selected"),
            {"share_ids": str(self.locked_share.pk)},
        )
        self.assertRedirects(response, reverse("shared-lists"))
        self.assertFalse(
            SharedAccess.objects.filter(pk=self.locked_share.pk).exists()
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertNotContains(page, "Old batch")
        # The unlocked collection is untouched.
        self.assertContains(page, "New batch")

    def test_locked_batch_deleted_as_one_collection(self):
        import uuid

        second_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Second locked doc",
            file=SimpleUploadedFile("second-locked.txt", b"x"),
            file_type="doc",
        )
        # One collection: both rows share the password group and title.
        self.locked_share.password_group = uuid.uuid4()
        self.locked_share.save(update_fields=["password_group"])
        sibling = SharedAccess(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=second_doc,
            group_title="Old batch",
            password_group=self.locked_share.password_group,
        )
        sibling.set_password("secret123")
        sibling.save()
        page = self.client.get(reverse("shared-lists"))
        expected_ids = ",".join(
            str(pk) for pk in sorted([self.locked_share.pk, sibling.pk])
        )
        self.assertContains(page, f'data-share-ids="{expected_ids}"')
        # Removing the selected collection removes every share row in it.
        response = self.client.post(
            reverse("shared-delete-selected"), {"share_ids": expected_ids}
        )
        self.assertRedirects(response, reverse("shared-lists"))
        self.assertFalse(
            SharedAccess.objects.filter(
                pk__in=[self.locked_share.pk, sibling.pk]
            ).exists()
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertNotContains(page, "Old batch")

    def test_enter_password_link_opens_password_page(self):
        import re

        page = self.client.get(reverse("shared-lists"))
        match = re.search(r'href="(/shared/(\d+)/\?unlock=1)"[^>]*>Enter password', page.content.decode())
        self.assertIsNotNone(match)
        # The button targets the still-locked share...
        self.assertEqual(int(match.group(2)), self.locked_share.pk)
        # ...and opens the password form, not the viewer.
        form_page = self.client.get(match.group(1))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "lock-form")
        self.assertContains(form_page, 'name="password"')

    def test_unlock_param_forwards_past_unlocked_share(self):
        import uuid

        from django.utils import timezone

        extra_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Extra locked notes",
            file=SimpleUploadedFile("extra.txt", b"extra"),
            file_type="doc",
        )
        open_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Extra open notes",
            file=SimpleUploadedFile("extra-open.txt", b"extra open"),
            file_type="doc",
        )
        sibling = SharedAccess(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=extra_doc,
            group_title="Old batch",
            password_group=uuid.uuid4(),
        )
        sibling.set_password("sibling123")
        sibling.save()
        # Simulate a partially-unlocked batch: same group, one row open.
        batch_pg = sibling.password_group
        opened = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=open_doc,
            group_title="Old batch",
            password_group=batch_pg,
            unlocked_at=timezone.now(),
        )
        response = self.client.get(f"/shared/{opened.pk}/?unlock=1")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/shared/{sibling.pk}/", response.url)
        form_page = self.client.get(response.url)
        self.assertContains(form_page, "lock-form")

    def test_same_title_batches_unlock_independently(self):
        import uuid

        second_doc = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Second locked notes",
            file=SimpleUploadedFile("second.txt", b"second"),
            file_type="doc",
        )
        # Same visible title, but a different share batch (own password).
        batch2 = SharedAccess(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=second_doc,
            group_title="Old batch",
            password_group=uuid.uuid4(),
        )
        batch2.set_password("other1234")
        batch2.save()
        # Unlock only the first batch.
        self.client.post(
            reverse("shared-unlock", args=[self.locked_share.pk]),
            {"password": "secret123"},
        )
        page = self.client.get(reverse("shared-lists"))
        # The two batches remain separate collections...
        self.assertContains(page, "Old batch")
        self.assertContains(page, "Enter password")
        # ...the unlocked batch reveals and offers its document...
        self.assertContains(page, "Old locked notes")
        self.assertContains(page, f'data-material-id="{self.old_doc.pk}"')
        # ...while the still-locked batch hides its documents entirely.
        self.assertNotContains(page, "Second locked notes")
        self.assertNotContains(page, f'data-material-id="{second_doc.pk}"')
        # Unlocking the second batch reveals it too.
        self.client.post(
            reverse("shared-unlock", args=[batch2.pk]),
            {"password": "other1234"},
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "Second locked notes")
        self.assertContains(page, f'data-material-id="{second_doc.pk}"')
        self.assertNotContains(page, "Enter password")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SharedListPaginationTests(TestCase):
    """Five collections ("bubbles") per section, See more adds five more,
    newest first."""

    def setUp(self):
        import uuid

        from django.utils import timezone

        self.owner = User.objects.create_user("pageowner", password="test12345")
        self.recipient = User.objects.create_user("pagerecv", password="test12345")
        self.subject = Subject.objects.create(
            owner=self.owner, name="Paged", class_level="G1"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="T")
        base = timezone.now() - timezone.timedelta(days=10)
        self.batch_docs = []
        batch_pg = uuid.uuid4()
        for i in range(3):
            doc = Material.objects.create(
                topic=self.topic,
                owner=self.owner,
                title=f"Paged batch doc {i + 1}",
                file=SimpleUploadedFile(f"b{i}.txt", b"x"),
                file_type="doc",
            )
            share = SharedAccess.objects.create(
                shared_by=self.owner,
                shared_with=self.recipient,
                material=doc,
                group_title="Batch",
                password_group=batch_pg,
            )
            share.created_at = base + timezone.timedelta(days=5 + i)
            share.save(update_fields=["created_at"])
            self.batch_docs.append(doc)
        self.single_docs = []
        for i in range(5):
            doc = Material.objects.create(
                topic=self.topic,
                owner=self.owner,
                title=f"Paged single {i + 1}",
                file=SimpleUploadedFile(f"s{i}.txt", b"x"),
                file_type="doc",
            )
            share = SharedAccess.objects.create(
                shared_by=self.owner, shared_with=self.recipient, material=doc
            )
            share.created_at = base + timezone.timedelta(days=i)
            share.save(update_fields=["created_at"])
            self.single_docs.append(doc)
        self.client.force_login(self.recipient)

    def _section(self, page, marker):
        content = page.content.decode()
        return content.split(marker, 1)[1].split("</section>", 1)[0]

    def test_first_five_collections_visible_rest_behind_see_more(self):
        page = self.client.get(reverse("shared-lists"))
        chunk = self._section(page, 'id="section-received"')
        # Newest first: five collections (bubbles) stay visible — the
        # three-file batch plus singles 5..2 — and the oldest single waits
        # behind a "See more" button that reports how many collections
        # remain.
        self.assertEqual(chunk.count('<div class="share-group" id='), 5)
        self.assertEqual(chunk.count("share-group share-extra hidden"), 1)
        self.assertIn("See more (1 more collections)", chunk)
        self.assertIn(">5</span> of 6 collections", chunk)
        # Every document is still in the markup (JS reveals the rest), and
        # the newest bubble appears before the oldest.
        content = page.content.decode()
        for doc in self.batch_docs:
            self.assertContains(page, doc.title)
        oldest_pos = content.find("Paged single 1")
        newest_pos = content.find("Paged batch doc 3")
        self.assertTrue(0 <= newest_pos < oldest_pos)

    def test_see_more_button_absent_when_five_or_fewer_files(self):
        reader = User.objects.create_user("pagereader", password="test12345")
        for i in range(3):
            doc = Material.objects.create(
                topic=self.topic,
                owner=self.owner,
                title=f"Few doc {i + 1}",
                file=SimpleUploadedFile(f"f{i}.txt", b"x"),
                file_type="doc",
            )
            SharedAccess.objects.create(
                shared_by=self.owner, shared_with=reader, material=doc
            )
        self.client.force_login(reader)
        page = self.client.get(reverse("shared-lists"))
        chunk = self._section(page, 'id="section-received"')
        self.assertNotIn("See more", chunk)
        self.assertNotIn("share-extra", chunk)
        self.assertIn(">3</span> of 3 collections", chunk)

    def test_given_section_paginates_too(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("shared-lists"))
        received = self._section(page, 'id="section-received"')
        given = self._section(page, 'id="section-given"')
        self.assertNotIn("See more", received)
        self.assertEqual(given.count('<div class="share-group" id='), 5)
        self.assertEqual(given.count("share-group share-extra hidden"), 1)
        self.assertIn("See more (1 more collections)", given)
        self.assertIn(">5</span> of 6 collections", given)

    def test_many_files_within_first_five_collections_all_visible(self):
        """Paging counts collections, not files: seven files spread over
        four collections all stay visible, with no See more."""
        import uuid

        from django.utils import timezone

        reader = User.objects.create_user("pagestraddle", password="test12345")
        for name, count in [("Straddle A", 3), ("Straddle B", 2), ("Straddle C", 1), ("Straddle D", 1)]:
            pg = uuid.uuid4()
            for i in range(count):
                doc = Material.objects.create(
                    topic=self.topic,
                    owner=self.owner,
                    title=f"Straddle {name} doc {i + 1}",
                    file=SimpleUploadedFile(f"st{name}{i}.txt", b"x"),
                    file_type="doc",
                )
                SharedAccess.objects.create(
                    shared_by=self.owner,
                    shared_with=reader,
                    material=doc,
                    group_title=name,
                    password_group=pg,
                )
        self.client.force_login(reader)
        page = self.client.get(reverse("shared-lists"))
        chunk = self._section(page, 'id="section-received"')
        # Four collections holding seven files never get cut off — only
        # the fifth collection onward would hide behind "See more".
        self.assertEqual(chunk.count('<div class="share-group" id='), 4)
        self.assertNotIn("share-extra", chunk)
        self.assertNotIn("See more", chunk)
        self.assertIn(">4</span> of 4 collections", chunk)

    def test_single_collection_larger_than_page_stays_whole(self):
        import uuid

        reader = User.objects.create_user("pagebig", password="test12345")
        pg = uuid.uuid4()
        for i in range(7):
            doc = Material.objects.create(
                topic=self.topic,
                owner=self.owner,
                title=f"Big doc {i + 1}",
                file=SimpleUploadedFile(f"big{i}.txt", b"x"),
                file_type="doc",
            )
            SharedAccess.objects.create(
                shared_by=self.owner,
                shared_with=reader,
                material=doc,
                group_title="Big",
                password_group=pg,
            )
        self.client.force_login(reader)
        page = self.client.get(reverse("shared-lists"))
        chunk = self._section(page, 'id="section-received"')
        # A single collection with seven files cannot be split across pages.
        self.assertEqual(chunk.count('<div class="share-group" id='), 1)
        self.assertNotIn("share-extra", chunk)
        self.assertNotIn("See more", chunk)
        self.assertIn(">1</span> of 1 collections", chunk)

    def test_separate_actions_with_same_title_stay_separate(self):
        import uuid

        reader = User.objects.create_user("pagegrouping", password="test12345")
        first_pg = uuid.uuid4()
        rows = [
            ("Same title doc 1", first_pg),
            ("Same title doc 2", uuid.uuid4()),  # separate action, same title
            ("Same title doc 3", first_pg),  # same action as doc 1
        ]
        for i, (title, pg) in enumerate(rows):
            doc = Material.objects.create(
                topic=self.topic,
                owner=self.owner,
                title=title,
                file=SimpleUploadedFile(f"grp{i}.txt", b"x"),
                file_type="doc",
            )
            SharedAccess.objects.create(
                shared_by=self.owner,
                shared_with=reader,
                material=doc,
                group_title="Same name",
                password_group=pg,
            )
        self.client.force_login(reader)
        page = self.client.get(reverse("shared-lists"))
        chunk = self._section(page, 'id="section-received"')
        # Two sharing actions (two password groups) = two collections even
        # though they reuse the title, and no See more is needed.
        self.assertEqual(chunk.count('<div class="share-group" id='), 2)
        self.assertNotIn("See more", chunk)
        # Documents of one action stay together in a single collection.
        self.assertIn("Same title doc 1", chunk)
        self.assertIn("Same title doc 3", chunk)

    def test_locked_newest_listed_without_contents(self):
        for doc in self.batch_docs:
            share = SharedAccess.objects.get(
                shared_by=self.owner, shared_with=self.recipient, material=doc
            )
            share.set_password("locked123")
            share.save(update_fields=["password"])
        page = self.client.get(reverse("shared-lists"))
        # The locked bubble stays listed (newest first) with its prompt, but
        # none of its documents are visible or selectable until unlocked.
        self.assertContains(page, "Batch")
        self.assertContains(page, "is-locked")
        self.assertContains(page, "Enter password")
        for doc in self.batch_docs:
            self.assertNotContains(page, doc.title)
            self.assertNotContains(page, f'data-material-id="{doc.pk}"')
        self.assertContains(page, f'data-material-id="{self.single_docs[-1].pk}"')


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SharedRecencyOrderTests(TestCase):
    """Shared collections and their documents are listed newest-first."""

    def setUp(self):
        self.owner = User.objects.create_user("recowner", password="test12345")
        self.recipient = User.objects.create_user("recrecv", password="test12345")
        self.subject = Subject.objects.create(
            owner=self.owner, name="History", class_level="G7"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="Modern")
        self.client.force_login(self.recipient)

    def _doc(self, title, name):
        return Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title=title,
            file=SimpleUploadedFile(name, b"x"),
            file_type="doc",
        )

    def _shift_share_time(self, share, **delta):
        from django.utils import timezone

        share.created_at = timezone.now() + timezone.timedelta(**delta)
        share.save(update_fields=["created_at"])

    def test_received_collections_newest_first(self):
        older = self._doc("Older doc", "older.txt")
        newer = self._doc("Newer doc", "newer.txt")
        older_share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=older,
            group_title="Older collection",
        )
        newer_share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=newer,
            group_title="Newer collection",
        )
        self._shift_share_time(older_share, days=-2)
        self._shift_share_time(newer_share, minutes=-5)
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "Newer collection")
        self.assertContains(page, "Older collection")
        content = page.content.decode()
        self.assertLess(
            content.find("Newer collection"), content.find("Older collection")
        )

    def test_given_collections_newest_first(self):
        self.client.force_login(self.owner)
        older = self._doc("Given older", "golder.txt")
        newer = self._doc("Given newer", "gnewer.txt")
        older_share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=older,
            group_title="Given old",
        )
        newer_share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            material=newer,
            group_title="Given new",
        )
        self._shift_share_time(older_share, days=-3)
        self._shift_share_time(newer_share, hours=-1)
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "Given old")
        self.assertContains(page, "Given new")
        content = page.content.decode()
        self.assertLess(content.find("Given new"), content.find("Given old"))

    def test_documents_inside_collection_newest_first(self):
        first = self._doc("Uploaded first", "first.txt")
        second = self._doc("Uploaded second", "second.txt")
        # Recency (uploaded_at) decides the display order, not pk order.
        from django.utils import timezone

        Material.objects.filter(pk=first.pk).update(uploaded_at=timezone.now())
        Material.objects.filter(pk=second.pk).update(
            uploaded_at=timezone.now() - timezone.timedelta(days=1)
        )
        SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            subject=self.subject,
            group_title="History docs",
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "Uploaded first")
        self.assertContains(page, "Uploaded second")
        content = page.content.decode()
        self.assertLess(
            content.find("Uploaded first"), content.find("Uploaded second")
        )

    def test_shared_viewer_documents_newest_first(self):
        self._doc("Early notes", "early.txt")
        self._doc("Late notes", "late.txt")
        share = SharedAccess.objects.create(
            shared_by=self.owner, shared_with=self.recipient, subject=self.subject
        )
        page = self.client.get(reverse("shared-open", args=[share.pk]))
        self.assertEqual(page.status_code, 200)
        content = page.content.decode()
        self.assertLess(content.find("Late notes"), content.find("Early notes"))

    def test_combined_viewer_documents_newest_first(self):
        older = self._doc("Combined older", "co.txt")
        newer = self._doc("Combined newer", "cn.txt")
        SharedAccess.objects.create(
            shared_by=self.owner, shared_with=self.recipient, subject=self.subject
        )
        page = self.client.get(
            reverse("shared-combined") + f"?materials={older.pk},{newer.pk}"
        )
        self.assertEqual(page.status_code, 200)
        content = page.content.decode()
        self.assertLess(
            content.find("Combined newer"), content.find("Combined older")
        )

    def test_combined_viewer_back_link_defaults_to_shared_list(self):
        doc = self._doc("Shared back link", "shared-back.txt")
        SharedAccess.objects.create(
            shared_by=self.owner, shared_with=self.recipient, material=doc
        )
        page = self.client.get(
            reverse("shared-combined") + f"?materials={doc.pk}"
        )
        self.assertContains(page, "Back to shared list")
        self.assertContains(page, f'href="{reverse("shared-lists")}"')
        self.assertNotContains(page, "Back to topics")

    def test_combined_viewer_back_link_returns_to_topics_page(self):
        own_subject = Subject.objects.create(
            owner=self.recipient, name="My subject", class_level="G8"
        )
        own_topic = Topic.objects.create(subject=own_subject, name="My topic")
        own_doc = Material.objects.create(
            topic=own_topic,
            owner=self.recipient,
            title="My document",
            file=SimpleUploadedFile("mine.txt", b"mine"),
            file_type="doc",
        )
        page = self.client.get(
            reverse("shared-combined")
            + f"?materials={own_doc.pk}&from=topics&subject={own_subject.pk}"
        )
        self.assertContains(page, "Back to topics")
        self.assertContains(
            page, f'href="{reverse("dashboard-subject", args=[own_subject.pk])}"'
        )
        self.assertNotContains(page, "Back to shared list")

    def test_combined_viewer_topics_back_link_rejects_foreign_subject(self):
        own_subject = Subject.objects.create(
            owner=self.recipient, name="Mine", class_level="G8"
        )
        own_topic = Topic.objects.create(subject=own_subject, name="Mine")
        own_doc = Material.objects.create(
            topic=own_topic,
            owner=self.recipient,
            title="Mine",
            file=SimpleUploadedFile("mine2.txt", b"mine"),
            file_type="doc",
        )
        page = self.client.get(
            reverse("shared-combined")
            + f"?materials={own_doc.pk}&from=topics&subject={self.subject.pk}"
        )
        self.assertContains(page, "Back to topics")
        self.assertContains(page, f'href="{reverse("dashboard")}"')

    def test_shared_viewer_back_link_returns_to_shared_list(self):
        doc = self._doc("Single shared doc", "single.txt")
        share = SharedAccess.objects.create(
            shared_by=self.owner, shared_with=self.recipient, material=doc
        )
        page = self.client.get(reverse("shared-open", args=[share.pk]))
        self.assertContains(page, "Back to shared list")
        self.assertContains(page, f'href="{reverse("shared-lists")}"')

    def test_locked_collection_hides_topic_and_documents(self):
        topic = Topic.objects.create(subject=self.subject, name="Hidden topic")
        Material.objects.create(
            topic=topic,
            owner=self.owner,
            title="Hidden document",
            file=SimpleUploadedFile("hidden.txt", b"x"),
            file_type="doc",
        )
        share = SharedAccess.objects.create(
            shared_by=self.owner,
            shared_with=self.recipient,
            topic=topic,
            group_title="Vault",
        )
        share.set_password("lock1234")
        share.save()
        page = self.client.get(reverse("shared-lists"))
        # The locked collection is listed with its prompt...
        self.assertContains(page, "Vault")
        self.assertContains(page, "Enter password")
        # ...but its topic, subject and documents stay hidden.
        self.assertNotContains(page, "Hidden topic")
        self.assertNotContains(page, "History")
        self.assertNotContains(page, "Hidden document")
        # Unlocking reveals the contents.
        self.client.post(
            reverse("shared-unlock", args=[share.pk]), {"password": "lock1234"}
        )
        page = self.client.get(reverse("shared-lists"))
        self.assertContains(page, "Hidden topic")
        self.assertContains(page, "Hidden document")


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


@override_settings(GEMINI_API_KEY="AQ.Ab8RN6RealTestKey", GEMINI_MODEL="")
class AiAskTests(TestCase):
    def setUp(self):
        cache.clear()
        ai._preferred_model = None
        self.user = User.objects.create_user("student", password="test12345")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(
            owner=self.user, name="Biology", class_level="Grade 11"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="Cells")
        Material.objects.create(
            topic=self.topic,
            owner=self.user,
            title="Cell notes",
            file=SimpleUploadedFile("cells.txt", b"Cells have mitochondria."),
            file_type="doc",
        )

    def tearDown(self):
        ai._preferred_model = None

    def _ask(self, **payload):
        body = {"question": "What is in these notes?", "subject_id": self.subject.pk}
        body.update(payload)
        return self.client.post(
            reverse("ai-ask"),
            data=json_dumps(body),
            content_type="application/json",
        )

    def test_requires_login(self):
        client = Client()
        response = client.post(reverse("ai-ask"), data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 302)

    def test_missing_subject_returns_400_json(self):
        response = self.client.post(
            reverse("ai-ask"),
            data=json_dumps({"question": "hi"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_inaccessible_subject_returns_404_json(self):
        stranger = User.objects.create_user("strangerx", password="test12345")
        foreign = Subject.objects.create(
            owner=stranger, name="Secrets", class_level="Grade 12"
        )
        response = self._ask(subject_id=foreign.pk)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "That subject isn't available to you.")

    @patch("materials.ai.requests.post")
    def test_ask_success(self, mock_post):
        mock_post.return_value = FakeResponse(
            json_data={
                "candidates": [{"content": {"parts": [{"text": "Mitochondria!"}]}}]
            }
        )
        response = self._ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Mitochondria!")
        self.assertTrue(mock_post.called)

    @patch("materials.ai.time.sleep", lambda *_: None)
    @patch("materials.ai.requests.post")
    def test_all_models_busy_returns_502(self, mock_post):
        mock_post.return_value = FakeResponse(status_code=503, text="overloaded")
        response = self._ask()
        self.assertEqual(response.status_code, 502)
        self.assertIn("busy", response.json()["error"])

    @patch("materials.ai.requests.post")
    def test_oauth_style_key_is_accepted(self, mock_post):
        mock_post.return_value = FakeResponse(
            json_data={"candidates": [{"content": {"parts": [{"text": "hi!"}]}}]}
        )
        response = self._ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "hi!")

    @patch("materials.ai.time.sleep", lambda *_: None)
    @patch("materials.ai.requests.post")
    def test_working_model_is_remembered_and_tried_first(self, mock_post):
        fallback_models = ai.FALLBACK_MODELS

        def side_effect(url, **kwargs):
            requested = url.split("/models/")[1].split(":")[0]
            if requested == settings_model():
                return FakeResponse(status_code=503, text="overloaded")
            if requested == fallback_models[0]:
                return FakeResponse(status_code=503, text="overloaded")
            return FakeResponse(
                json_data={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            )

        def settings_model():
            from django.conf import settings as dj_settings

            return dj_settings.GEMINI_MODEL or ""

        mock_post.side_effect = side_effect
        first = self._ask()
        self.assertEqual(first.status_code, 200)
        working = ai._preferred_model
        self.assertIsNotNone(working)
        self.assertNotIn(working, ("", None))

        mock_post.reset_mock()
        second = self._ask()
        self.assertEqual(second.status_code, 200)
        first_url = mock_post.call_args_list[0][0][0]
        self.assertIn(f"/models/{working}:", first_url)

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_reports_not_configured(self):
        response = self._ask()
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.json()["error"])

    @patch("materials.ai.requests.post")
    def test_rejected_key_reports_configuration_problem(self, mock_post):
        mock_post.return_value = FakeResponse(status_code=401, text="unauthorized")
        response = self._ask()
        self.assertEqual(response.status_code, 503)
        self.assertIn("rejected the API key", response.json()["error"])

    def test_empty_question_rejected(self):
        response = self.client.post(
            reverse("ai-ask"),
            data=json_dumps({"question": "   ", "subject_id": self.subject.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class GlobalSearchTests(TestCase):
    def setUp(self):
        from django.utils import timezone

        self.owner = User.objects.create_user("alice", password="test12345")
        self.recipient = User.objects.create_user("bob", password="test12345")
        self.stranger = User.objects.create_user("carol", password="test12345")
        self.subject = Subject.objects.create(
            owner=self.owner, name="Physics", class_level="Grade 10"
        )
        self.topic = Topic.objects.create(subject=self.subject, name="Waves")
        self.notes = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Wave notes",
            file=SimpleUploadedFile(
                "notes.txt", b"Amplitude decides the energy of the wave. ZeppelinX."
            ),
            file_type="doc",
        )
        self.slides = Material.objects.create(
            topic=self.topic,
            owner=self.owner,
            title="Quantum slides",
            file=SimpleUploadedFile("slides.txt", b"unrelated content here"),
            file_type="doc",
        )

        # bob's own material
        own_subject = Subject.objects.create(
            owner=self.recipient, name="Botany", class_level="Grade 10"
        )
        own_topic = Topic.objects.create(subject=own_subject, name="Ferns")
        Material.objects.create(
            topic=own_topic,
            owner=self.recipient,
            title="Fern care guide",
            file=SimpleUploadedFile("fern.txt", b"Keep ferns humid"),
            file_type="doc",
        )

        self.locked_topic_share = SharedAccess(
            shared_by=self.owner, shared_with=self.recipient, topic=self.topic
        )
        self.locked_topic_share.set_password("secret1")
        self.locked_topic_share.save()

        self.unlocked_subject_share = SharedAccess(
            shared_by=self.owner, shared_with=self.stranger, subject=self.subject
        )
        self.unlocked_subject_share.set_password("")
        self.unlocked_subject_share.unlocked_at = timezone.now()
        self.unlocked_subject_share.save()
        self._tz = timezone
        self.client.force_login(self.recipient)

    def _search(self, q, client=None):
        return (client or self.client).get(reverse("global-search"), {"q": q})

    def _owner_search(self, q):
        owner_client = Client()
        owner_client.force_login(self.owner)
        return self._search(q, owner_client)

    def _groups(self, data):
        return {g["label"]: g["items"] for g in data["groups"]}

    def _flat(self, data):
        return [item for group in data["groups"] for item in group["items"]]

    def test_requires_login(self):
        response = Client().get(reverse("global-search"), {"q": "waves"})
        self.assertEqual(response.status_code, 302)

    def test_short_query_returns_empty(self):
        response = self._search("w")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["groups"], [])

    def test_subject_match_for_owner(self):
        data = self._owner_search("phys").json()
        groups = self._groups(data)
        self.assertIn("Subjects", groups)
        item = groups["Subjects"][0]
        self.assertIn("Physics", item["title"])
        self.assertTrue(item["url"].startswith("/viewer/subject/"))

    def test_class_level_match_found(self):
        data = self._owner_search("grade 10").json()
        self.assertIn("Subjects", self._groups(data))

    def test_topic_match_links_to_anchor(self):
        data = self._owner_search("wav").json()
        topics = self._groups(data).get("Topics")
        self.assertTrue(topics)
        self.assertEqual(topics[0]["title"], "Waves")
        self.assertTrue(topics[0]["url"].endswith(f"#topic-{self.topic.pk}"))

    def test_document_title_match(self):
        data = self._owner_search("quantum").json()
        docs = self._groups(data).get("Documents")
        self.assertTrue(docs)
        titles = {i["title"] for i in docs}
        self.assertEqual(titles, {"Quantum slides"})

    def test_passage_match_with_snippet(self):
        data = self._owner_search("amplitude").json()
        passages = self._groups(data).get("Inside documents")
        self.assertTrue(passages)
        item = passages[0]
        self.assertIn("Amplitude", item["snippet"])
        self.assertEqual(item["title"], "Wave notes")
        self.assertTrue(item["url"].endswith(f"#topic-{self.topic.pk}"))

    def test_snippet_finds_unique_word_case_insensitive(self):
        data = self._owner_search("zeppelinx").json()
        passages = self._groups(data).get("Inside documents")
        self.assertTrue(passages)
        self.assertEqual(passages[0]["title"], "Wave notes")

    def test_locked_share_hidden_until_unlocked(self):
        data = self._search("wav").json()  # bob searching
        self.assertFalse(self._flat(data))

        share = SharedAccess.objects.get(pk=self.locked_topic_share.pk)
        share.unlocked_at = self._tz.now()
        share.save(update_fields=["unlocked_at"])
        data = self._search("wav").json()
        flat = self._flat(data)
        self.assertTrue(flat)
        self.assertTrue(any("/shared/" in i["url"] for i in flat))

    def test_unlocked_shared_subject_searchable_by_recipient(self):
        client = Client()
        client.force_login(self.stranger)
        data = self._search("quantum", client).json()
        flat = self._flat(data)
        doc_item = next(i for i in flat if i["title"] == "Quantum slides")
        self.assertIn("/shared/", doc_item["url"])

    def test_stranger_cannot_see_private_material(self):
        client = Client()
        client.force_login(User.objects.create_user("mallory", password="test12345"))
        data = self._search("botany", client).json()
        self.assertFalse(self._flat(data))

    def test_lazy_indexing_backfills_missing_rows(self):
        from materials.models import MaterialTextIndex

        MaterialTextIndex.objects.all().delete()
        data = self._owner_search("zeppelinx").json()
        passages = self._groups(data).get("Inside documents")
        self.assertTrue(passages)
        self.assertEqual(
            MaterialTextIndex.objects.filter(material=self.notes).count(), 1
        )

    def test_navbar_search_bar_rendered_on_pages(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-search-trigger"')
        self.assertContains(response, 'id="cmdk-backdrop"')
        self.assertContains(response, "command_palette.js")


@override_settings(GEMINI_API_KEY="AIzaFakeTestKey", GEMINI_MODEL="")
class AiQuickAskTests(TestCase):
    def setUp(self):
        cache.clear()
        ai._preferred_model = None
        self.user = User.objects.create_user("student", password="test12345")
        self.client.force_login(self.user)

    def tearDown(self):
        ai._preferred_model = None

    def _post(self, payload):
        return self.client.post(
            reverse("ai-quick-ask"),
            data=json_dumps(payload),
            content_type="application/json",
        )

    def test_requires_login(self):
        response = Client().post(reverse("ai-quick-ask"), data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 302)

    @patch("materials.ai.requests.post")
    def test_quick_ask_success_without_context(self, mock_post):
        mock_post.return_value = FakeResponse(
            json_data={"candidates": [{"content": {"parts": [{"text": "42"}]}}]}
        )
        response = self._post({"question": "Meaning of life?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "42")

        sent_payload = mock_post.call_args.kwargs["json"]
        system_text = sent_payload["system_instruction"]["parts"][0]["text"]
        # No study material block may be appended for the context-free ask.
        self.assertEqual(system_text.strip(), ai.SYSTEM_PROMPT.strip())

    def test_empty_question_rejected(self):
        response = self._post({"question": ""})
        self.assertEqual(response.status_code, 400)

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_reports_not_configured(self):
        response = self._post({"question": "hi"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.json()["error"])


def json_dumps(payload):
    import json

    return json.dumps(payload)
