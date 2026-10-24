from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from materials.models import Subject

from .forms import ProfileForm, UsernameChangeForm
from .models import Profile


USER_SEARCH_MIN_CHARS = 2
USER_SEARCH_LIMIT = 10


@login_required
@require_GET
def user_search(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < USER_SEARCH_MIN_CHARS:
        return JsonResponse({"results": []})
    users = (
        User.objects.filter(is_active=True)
        .exclude(pk=request.user.pk)
        .filter(Q(username__icontains=q) | Q(profile__full_name__icontains=q))
        .select_related("profile")
        .order_by("username")[:USER_SEARCH_LIMIT]
    )
    results = []
    for u in users:
        try:
            profile = u.profile
        except Profile.DoesNotExist:
            profile = None
        results.append(
            {
                "id": u.pk,
                "username": u.username,
                "full_name": profile.full_name if profile else "",
                "avatar": profile.avatar.url if profile and profile.avatar else "",
            }
        )
    return JsonResponse({"results": results})


def home(request):
    # "/" – hero for guests, subjects grid (dashboard preview) for authenticated users
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "home.html")


def dashboard(request, subject_id=None):
    if not request.user.is_authenticated:
        return redirect("login")
    subjects = Subject.objects.filter(owner=request.user).order_by("class_level", "name")
    # Annotate counts for server-side fallback rendering
    from django.db.models import Count
    subjects = subjects.annotate(topic_count=Count("topics", distinct=True), material_count=Count("topics__materials", distinct=True))
    class_levels = (
        Subject.objects.filter(owner=request.user)
        .values_list("class_level", flat=True)
        .distinct()
    )
    initial_subject_id = None
    if subject_id is not None and Subject.objects.filter(pk=subject_id, owner=request.user).exists():
        initial_subject_id = subject_id
    return render(
        request,
        "dashboard.html",
        {"class_levels": list(class_levels), "initial_subject_id": initial_subject_id, "subjects": subjects},
    )


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "registration/register.html", {"form": form})


class LoginViewCustom(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class LogoutViewCustom(LogoutView):
    next_page = "home"


def _profile_context(request, profile_form=None, username_form=None, password_form=None):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    # Remove autofocus from password form to prevent auto-scroll to "current password" on page load
    if password_form is None:
        password_form = PasswordChangeForm(request.user)
        for fname in ("old_password", "new_password1", "new_password2"):
            if fname in password_form.fields:
                password_form.fields[fname].widget.attrs.pop("autofocus", None)
    else:
        for fname in ("old_password", "new_password1", "new_password2"):
            if fname in password_form.fields:
                password_form.fields[fname].widget.attrs.pop("autofocus", None)
    return {
        "profile": profile_obj,
        "form": profile_form or ProfileForm(instance=profile_obj),
        "username_form": username_form or UsernameChangeForm(instance=request.user),
        "password_form": password_form,
    }


@login_required
def profile(request):
    if request.method == "POST":
        return save_profile_settings(request)
    return render(request, "registration/profile.html", _profile_context(request))


@login_required
@require_POST
def save_profile_settings(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    has_full_name = "full_name" in request.POST
    has_username = "username" in request.POST
    has_password = any(
        request.POST.get(k, "").strip()
        for k in ("old_password", "new_password1", "new_password2")
    )

    # Support combined legacy form (contains all) and separate full_name-only form
    if not has_full_name and not has_username and not has_password:
        messages.error(request, "Nothing to update.")
        return redirect("profile")

    profile_form = (
        ProfileForm(request.POST, instance=profile_obj)
        if has_full_name
        else ProfileForm(instance=profile_obj)
    )
    username_form = (
        UsernameChangeForm(request.POST, instance=request.user)
        if has_username
        else UsernameChangeForm(instance=request.user)
    )
    password_form = (
        PasswordChangeForm(request.user, request.POST)
        if has_password
        else PasswordChangeForm(request.user)
    )

    # Validate only the sections that were submitted
    valid = True
    if has_full_name:
        valid = profile_form.is_valid() and valid
    if has_username:
        valid = username_form.is_valid() and valid
    if has_password:
        valid = password_form.is_valid() and valid

    if valid:
        if has_full_name:
            profile_form.save()
        if has_username:
            username_form.save()
        if has_password:
            user = password_form.save()
            update_session_auth_hash(request, user)
        messages.success(request, "Profile settings updated.")
        return redirect("profile")

    context = _profile_context(
        request,
        profile_form=profile_form,
        username_form=username_form,
        password_form=password_form,
    )
    return render(request, "registration/profile.html", context)


@login_required
@require_POST
def change_username(request):
    form = UsernameChangeForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(
            request, f"Username changed to @{form.cleaned_data['username']}."
        )
        return redirect("profile")
    return render(
        request, "registration/profile.html", _profile_context(request, username_form=form)
    )


@login_required
def change_password(request):
    if request.method != "POST":
        return redirect("profile")
    form = PasswordChangeForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Password changed.")
        return redirect("profile")
    return render(
        request, "registration/profile.html", _profile_context(request, password_form=form)
    )


MAX_AVATAR_BYTES = 5 * 1024 * 1024


@login_required
@require_POST
def upload_avatar(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    file = request.FILES.get("avatar")
    if not file:
        return JsonResponse({"error": "No file provided."}, status=400)
    if file.size > MAX_AVATAR_BYTES:
        return JsonResponse({"error": "Image must be under 5 MB."}, status=400)

    from PIL import Image as PILImage

    try:
        PILImage.open(file).verify()
    except Exception:
        return JsonResponse(
            {"error": "That file is not a valid image."}, status=400
        )

    profile_obj.avatar = file
    profile_obj.save(update_fields=["avatar"])
    return JsonResponse({"url": profile_obj.avatar.url})
