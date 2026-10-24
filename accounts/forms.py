from django import forms
from django.contrib.auth.models import User

from .models import Profile


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["full_name", "avatar"]
        widgets = {
            "full_name": forms.TextInput(
                attrs={"placeholder": "Your full name", "maxlength": 120}
            ),
        }


class UsernameChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "New username", "maxlength": 150}),
        }

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        taken = User.objects.exclude(pk=self.instance.pk).filter(
            username__iexact=username
        )
        if taken.exists():
            raise forms.ValidationError("That username is already taken.")
        return username
