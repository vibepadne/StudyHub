from django.contrib import admin

from .models import Material, Subject, Topic


class MaterialInline(admin.TabularInline):
    model = Material
    extra = 0


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 0


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "class_level", "owner")
    list_filter = ("class_level",)
    search_fields = ("name",)
    inlines = [TopicInline]


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "topic", "file_type", "owner", "uploaded_at")
    list_filter = ("file_type",)
    search_fields = ("title",)
