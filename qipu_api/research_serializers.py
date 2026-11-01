from django.db import transaction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rest_framework import serializers

from .models import (
    User, ResearchProject, ProjectMembership, ResearchType, HistoricalEntity,
    ResearchMedia, EpistemicStatus, ResearchItem, ItemEntityParticipation,
    ItemItemParticipation, ItemMediaReference,
)


def require_same_project(project, objects):
    for obj in objects:
        if obj.project_id != project.pk:
            raise serializers.ValidationError('All references must belong to the same project.')


class ProjectMembershipSerializer(serializers.ModelSerializer):
    username = serializers.SlugRelatedField(source='user', slug_field='username', queryset=User.objects.all())

    class Meta:
        model = ProjectMembership
        fields = ['id', 'project', 'username', 'role']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move a membership.'})
        if self.instance and 'user' in attrs and attrs['user'] != self.instance.user:
            raise serializers.ValidationError({'username': 'Cannot change the member.'})
        if self.instance and self.instance.user_id == project.owner_id:
            if attrs.get('role', self.instance.role) != 'owner':
                raise serializers.ValidationError({'role': 'The project owner must remain an owner.'})
        if not self.instance and attrs.get('role') == 'owner':
            raise serializers.ValidationError({'role': 'An owner is created with the project.'})
        return attrs


class ResearchProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchProject
        fields = ['id', 'name', 'description', 'timezone', 'owner', 'created_at']
        read_only_fields = ['owner', 'created_at']

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError('Use a valid IANA time zone, e.g. Europe/Paris.')
        if self.instance and value != self.instance.timezone:
            from .models import QipInformation, SourceDating
            from .research_v2_serializers import BOUNDS, historical_instant
            for record in list(QipInformation.objects.filter(project=self.instance)) + list(
                    SourceDating.objects.filter(source__project=self.instance)):
                try:
                    for key in BOUNDS:
                        historical_instant(getattr(record, key), getattr(record, f'{key}_time'), value)
                except serializers.ValidationError:
                    raise serializers.ValidationError('An existing historical hour is ambiguous or nonexistent in this time zone.')
        return value


class ResearchTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchType
        fields = ['id', 'project', 'created_by', 'name', 'definition', 'semantic_uri', 'parent']
        read_only_fields = ['created_by']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move a type.'})
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        if parent:
            require_same_project(project, [parent])
            ancestor = parent
            while ancestor:
                if self.instance and ancestor.pk == self.instance.pk:
                    raise serializers.ValidationError({'parent': 'Circular type hierarchy.'})
                ancestor = ancestor.parent
        return attrs


class HistoricalEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricalEntity
        fields = ['id', 'project', 'created_by', 'label', 'description', 'type', 'created_at']
        read_only_fields = ['created_by', 'created_at']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move an entity.'})
        if attrs.get('type'):
            require_same_project(project, [attrs['type']])
        return attrs


class ResearchMediaSerializer(serializers.ModelSerializer):
    has_file = serializers.SerializerMethodField()

    class Meta:
        model = ResearchMedia
        fields = ['id', 'project', 'created_by', 'title', 'description', 'reference', 'author_label',
                  'date_text', 'parent',
                  'locator', 'storage_key', 'content_type', 'has_file', 'created_at']
        read_only_fields = ['created_by', 'created_at']
        extra_kwargs = {'storage_key': {'write_only': True}}

    def get_has_file(self, obj):
        media = obj
        while media:
            if media.storage_key:
                return True
            media = media.parent
        return False

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move a media record.'})
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        if parent:
            require_same_project(project, [parent])
            ancestor = parent
            while ancestor:
                if self.instance and ancestor.pk == self.instance.pk:
                    raise serializers.ValidationError({'parent': 'Circular media hierarchy.'})
                ancestor = ancestor.parent
        key = attrs.get('storage_key')
        if key and not key.startswith(f'research/{self.context["request"].user.pk}/'):
            raise serializers.ValidationError({'storage_key': 'Upload a file with your own signed URL.'})
        return attrs


class EpistemicStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = EpistemicStatus
        fields = ['id', 'code', 'label', 'definition']


class EntityParticipationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemEntityParticipation
        fields = ['entity', 'type', 'as_written']


class ItemParticipationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemItemParticipation
        fields = ['participant', 'type']


class MediaReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemMediaReference
        fields = ['media', 'locator', 'note']


class ResearchItemSerializer(serializers.ModelSerializer):
    entity_participations = EntityParticipationSerializer(many=True, required=False)
    item_participations = ItemParticipationSerializer(many=True, required=False)
    media_references = MediaReferenceSerializer(many=True, required=False)
    exact_begin = serializers.DateField(write_only=True, required=False)
    exact_end = serializers.DateField(write_only=True, required=False)

    class Meta:
        model = ResearchItem
        fields = ['id', 'project', 'created_by', 'type', 'epistemic_status', 'label',
                  'description', 'date_text', 'begin_of_begin', 'end_of_begin',
                  'begin_of_end', 'end_of_end', 'exact_begin', 'exact_end',
                  'entity_participations', 'item_participations', 'media_references', 'created_at']
        read_only_fields = ['created_by', 'created_at']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move an item.'})
        if project is None:
            return attrs
        kind = attrs.get('type', self.instance.type if self.instance else None)
        if kind:
            require_same_project(project, [kind])
        for simple, fields in (('exact_begin', ('begin_of_begin', 'end_of_begin')),
                               ('exact_end', ('begin_of_end', 'end_of_end'))):
            if simple in attrs:
                value = attrs.pop(simple)
                for field in fields:
                    if field in attrs and attrs[field] != value:
                        raise serializers.ValidationError({field: 'Conflicts with the exact date.'})
                    attrs[field] = value
        bounds = [attrs.get(field, getattr(self.instance, field) if self.instance else None)
                  for field in ('begin_of_begin', 'end_of_begin', 'begin_of_end', 'end_of_end')]
        known = [bound for bound in bounds if bound is not None]
        if known != sorted(known):
            raise serializers.ValidationError({'temporal_bounds': 'Known bounds must be in chronological order.'})
        for row in attrs.get('entity_participations', []):
            require_same_project(project, [row['entity'], row['type']])
        for row in attrs.get('item_participations', []):
            require_same_project(project, [row['participant'], row['type']])
            if self.instance and row['participant'].pk == self.instance.pk:
                raise serializers.ValidationError({'item_participations': 'An item cannot participate in itself.'})
        for row in attrs.get('media_references', []):
            require_same_project(project, [row['media']])
        return attrs

    def _replace_relations(self, item, data):
        for field, model in (('entity_participations', ItemEntityParticipation),
                             ('item_participations', ItemItemParticipation),
                             ('media_references', ItemMediaReference)):
            if field in data:
                rows = data.pop(field)
                getattr(item, field).all().delete()
                model.objects.bulk_create([model(item=item, **row) for row in rows])

    @transaction.atomic
    def create(self, validated_data):
        relations = {key: validated_data.pop(key) for key in
                     ('entity_participations', 'item_participations', 'media_references') if key in validated_data}
        item = ResearchItem.objects.create(**validated_data)
        self._replace_relations(item, relations)
        return item

    @transaction.atomic
    def update(self, instance, validated_data):
        relations = {key: validated_data.pop(key) for key in
                     ('entity_participations', 'item_participations', 'media_references') if key in validated_data}
        instance = super().update(instance, validated_data)
        self._replace_relations(instance, relations)
        return instance
