from .models import Profile


def user_profile(request):
    if not request.user.is_authenticated:
        return {"user_profile": None}
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return {"user_profile": profile}
