from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccountSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob", password="oldpass12345")
        self.client.force_login(self.user)

    def test_profile_page_shows_single_security_form(self):
        response = self.client.get(reverse("profile"))
        self.assertContains(response, 'name="full_name"')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="old_password"')
        self.assertContains(response, 'name="new_password1"')
        self.assertContains(response, 'name="new_password2"')
        self.assertContains(response, 'class="btn btn-primary security-save"')
        # New requirement: each field can be changed individually via its own form
        self.assertContains(response, 'action="%s"' % reverse("save-profile-settings"))
        self.assertContains(response, 'action="%s"' % reverse("change-username"))
        self.assertContains(response, 'action="%s"' % reverse("change-password"))
        # Password fields must be togglable via eye button (handled by JS globally)
        self.assertContains(response, 'password_toggle.js')

    def test_change_username_success(self):
        response = self.client.post(
            reverse("change-username"), {"username": "  robert  "}
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "robert")

    def test_change_username_rejects_taken_case_insensitive(self):
        User.objects.create_user("Alice", password="xypass12345")
        response = self.client.post(reverse("change-username"), {"username": "alice"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "bob")

    def test_change_username_rejects_invalid_characters(self):
        response = self.client.post(reverse("change-username"), {"username": "not ok!"})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "bob")
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_change_password_requires_current_password(self):
        response = self.client.post(
            reverse("change-password"),
            {
                "old_password": "wrongpass",
                "new_password1": "brandnew98765",
                "new_password2": "brandnew98765",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Password changed.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("oldpass12345"))
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_change_password_success_and_login_with_new(self):
        response = self.client.post(
            reverse("change-password"),
            {
                "old_password": "oldpass12345",
                "new_password1": "brandnew98765",
                "new_password2": "brandnew98765",
            },
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("oldpass12345"))
        self.assertTrue(self.user.check_password("brandnew98765"))
        self.assertTrue(self.client.session.get("_auth_user_id"))

        logout_client = type(self.client)()
        self.assertTrue(
            logout_client.login(username="bob", password="brandnew98765")
        )

    def test_change_password_rejects_weak_and_mismatched(self):
        response = self.client.post(
            reverse("change-password"),
            {
                "old_password": "oldpass12345",
                "new_password1": "12345678",
                "new_password2": "99999999",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("oldpass12345"))

    def test_change_password_get_redirects_to_profile(self):
        response = self.client.get(reverse("change-password"))
        self.assertRedirects(response, reverse("profile"))
