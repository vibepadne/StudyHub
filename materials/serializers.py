from rest_framework import serializers

from .models import Material, Subject, Topic


class MaterialSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)
    subject_id = serializers.IntegerField(source="topic.subject_id", read_only=True)
    subject_name = serializers.CharField(source="topic.subject.name", read_only=True)
    icon = serializers.CharField(read_only=True)

    class Meta:
        model = Material
        fields = [
            "id", "topic", "topic_name", "subject_id", "subject_name",
            "title", "file", "file_type", "icon", "uploaded_at",
        ]
        read_only_fields = ["id", "uploaded_at", "file_type"]
        extra_kwargs = {"title": {"required": False}}


class TopicSerializer(serializers.ModelSerializer):
    material_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Topic
        fields = ["id", "subject", "name", "order", "material_count"]


class SubjectSerializer(serializers.ModelSerializer):
    topic_count = serializers.IntegerField(read_only=True, default=0)
    material_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Subject
        fields = ["id", "name", "class_level", "color", "topic_count", "material_count"]
