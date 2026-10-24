"""
StudyHub URL Configuration – rewritten from scratch, same design, clean routing
==============================================================================
Base URL "/" is homepage (dashboard preview for authenticated, hero for guests).
All other pages keep their original names for reverse() compatibility.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts import views as account_views
from materials import views as material_views

# ---------------------------------------------------------------------------
# API – REST (subjects / topics / materials)
# ---------------------------------------------------------------------------
router = DefaultRouter()
router.register(r"subjects", material_views.SubjectViewSet, basename="subject")
router.register(r"topics", material_views.TopicViewSet, basename="topic")
router.register(r"materials", material_views.MaterialViewSet, basename="material")

# ---------------------------------------------------------------------------
# Page & App URLs
# ---------------------------------------------------------------------------
urlpatterns = [
    # ── Admin ───────────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── Core pages ──────────────────────────────────────────────────────────
    path("", account_views.home, name="home"),  # "/" – hero for guests, redirect to dashboard for auth
    path("dashboard/", account_views.dashboard, name="dashboard"),
    path("dashboard/subject/<int:subject_id>/", account_views.dashboard, name="dashboard-subject"),

    # ── Viewer (combined) ───────────────────────────────────────────────────
    path("viewer/subject/<int:subject_id>/", material_views.subject_viewer, name="subject-viewer"),
    path("viewer/topic/<int:topic_id>/", material_views.topic_viewer, name="topic-viewer"),
    path("viewer/material/<int:material_id>/", material_views.material_viewer, name="material-viewer"),

    # ── Sharing ─────────────────────────────────────────────────────────────
    path("share/subject/<int:subject_id>/", material_views.share_create, kwargs={"kind": "subject"}, name="share-subject"),
    path("share/topic/<int:topic_id>/", material_views.share_create, kwargs={"kind": "topic"}, name="share-topic"),
    path("share/bubble/", material_views.bubble_share, name="bubble-share"),

    path("shared/", material_views.shared_lists, name="shared-lists"),
    path("shared/combined/", material_views.shared_combined, name="shared-combined"),
    path("shared/combine/", material_views.shared_combine, name="shared-combine"),
    path("shared/delete-selected/", material_views.shared_delete_selected, name="shared-delete-selected"),
    path("shared/revoke-selected/", material_views.shared_revoke_selected, name="shared-revoke-selected"),
    path("shared/<int:pk>/", material_views.shared_open, name="shared-open"),
    path("shared/<int:pk>/unlock/", material_views.shared_unlock, name="shared-unlock"),
    path("shared/<int:pk>/revoke/", material_views.shared_revoke, name="shared-revoke"),

    # ── Search & AI ─────────────────────────────────────────────────────────
    path("users/search/", account_views.user_search, name="user-search"),
    path("search/", material_views.global_search, name="global-search"),
    path("ai/ask/", material_views.ai_ask, name="ai-ask"),
    path("ai/quick-ask/", material_views.ai_quick_ask, name="ai-quick-ask"),

    # ── Auth & Profile ──────────────────────────────────────────────────────
    # Custom auth views must come BEFORE the included auth.urls so they take
    # precedence (otherwise the default LoginView/LogoutView from auth.urls
    # would shadow the custom ones with redirect_authenticated_user etc).
    path("accounts/register/", account_views.register, name="register"),
    path("accounts/login/", account_views.LoginViewCustom.as_view(), name="login"),
    path("accounts/logout/", account_views.LogoutViewCustom.as_view(), name="logout"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("profile/", account_views.profile, name="profile"),
    path("profile/save/", account_views.save_profile_settings, name="save-profile-settings"),
    path("profile/avatar/", account_views.upload_avatar, name="profile-avatar"),
    path("profile/username/", account_views.change_username, name="change-username"),
    path("profile/password/", account_views.change_password, name="change-password"),

    # ── API ─────────────────────────────────────────────────────────────────
    path("api/", include(router.urls)),
]

# Serve media in DEBUG with permission checks for sensitive files
if settings.DEBUG:
    # Protected media: materials/ and converted/ require owner or unlocked share
    urlpatterns += [
        path("media/<path:path>", material_views.protected_media, name="protected-media"),
    ]
