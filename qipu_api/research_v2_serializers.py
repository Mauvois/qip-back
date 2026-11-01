from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from rest_framework import serializers

from .models import (ResearchProject, ResearchType, QipSource, SourceDating, QipEntity,
                     QipPerson, GeographicalPlace, QipInformation, InformationCitation,
                     InformationEvidence, InformationEntityRelation, PersonBirth, BibliographicRecord)
from .zotero_formats import normalize_csl


BOUNDS = ('begin_of_begin', 'end_of_begin', 'begin_of_end', 'end_of_end')
TIME_BOUNDS = tuple(f'{key}_time' for key in BOUNDS)


def same_project(project, *objects):
    if any(obj.project_id != project.id for obj in objects):
        raise serializers.ValidationError('All references must belong to the same project.')


def check_type(project, kind, value):
    if value:
        same_project(project, value)
        if value.kind != kind:
            raise serializers.ValidationError({'type': f'Expected a {kind} type.'})


def historical_instant(day, hour, zone):
    if not day or hour is None:
        return None
    local = datetime.combine(day, hour)
    tz = ZoneInfo(zone)
    instant = local.replace(tzinfo=tz)
    if (instant.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != local or
            instant.utcoffset() != local.replace(tzinfo=tz, fold=1).utcoffset()):
        raise serializers.ValidationError({'historical_time_span': 'Ambiguous or nonexistent local time in the project time zone.'})
    return instant.isoformat()


def check_bounds(data, instance=None, zone='UTC'):
    values = [(data.get(key, getattr(instance, key, None)),
               data.get(f'{key}_time', getattr(instance, f'{key}_time', None))) for key in BOUNDS]
    if any(day is None and hour is not None for day, hour in values):
        raise serializers.ValidationError({'historical_time_span': 'A time requires its date.'})
    for day, hour in values:
        historical_instant(day, hour, zone)
    # Date-only bounds span the entire calendar day; no hour is inferred.
    known = [(day, hour) for day, hour in values if day]
    if any(datetime.combine(first_day, first_hour or time.min) >
           datetime.combine(second_day, second_hour or time.max)
           for index, (first_day, first_hour) in enumerate(known)
           for second_day, second_hour in known[index + 1:]):
        raise serializers.ValidationError({'historical_time_span': 'Known bounds must be chronological.'})


class V2TypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchType
        fields = ['id', 'project', 'kind', 'name', 'definition', 'semantic_uri', 'parent']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move a type.'})
        kind = attrs.get('kind', self.instance.kind if self.instance else None)
        if kind == 'generic':
            raise serializers.ValidationError({'kind': 'Choose a Qip resource kind.'})
        if self.instance and kind != self.instance.kind:
            raise serializers.ValidationError({'kind': 'Cannot change the kind of a type.'})
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        seen = set()
        while parent:
            check_type(project, kind, parent)
            if parent.pk in seen or (self.instance and parent.pk == self.instance.pk):
                raise serializers.ValidationError({'parent': 'Circular type hierarchy.'})
            seen.add(parent.pk)
            parent = parent.parent
        return attrs


class SourceDatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceDating
        fields = ['id', 'date_kind', 'date_text', *BOUNDS, *TIME_BOUNDS, 'is_primary']
        read_only_fields = ['id']

    def validate(self, attrs):
        check_bounds(attrs, zone=self.context.get('project_timezone', 'UTC'))
        return attrs


class SourceSerializer(serializers.ModelSerializer):
    datings = SourceDatingSerializer(many=True, required=False)
    has_file = serializers.SerializerMethodField()
    bibliography = serializers.JSONField(required=False)

    class Meta:
        model = QipSource
        fields = ['id', 'project', 'created_by', 'type', 'title', 'description', 'reference',
                  'author_label', 'parent', 'locator', 'storage_key', 'content_type',
                   'has_file', 'bibliography', 'datings', 'created_at', 'updated_at']
        read_only_fields = ['created_by', 'created_at', 'updated_at']
        extra_kwargs = {'storage_key': {'write_only': True}}

    def get_has_file(self, obj):
        while obj:
            if obj.storage_key:
                return True
            obj = obj.parent
        return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        record = getattr(instance, 'bibliography', None)
        data['bibliography'] = record.csl if record else None
        return data

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move a source.'})
        check_type(project, 'source', attrs.get('type', self.instance.type if self.instance else None))
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        seen = set()
        while parent:
            same_project(project, parent)
            if parent.pk in seen or (self.instance and parent.pk == self.instance.pk):
                raise serializers.ValidationError({'parent': 'Circular source hierarchy.'})
            seen.add(parent.pk)
            parent = parent.parent
        key = attrs.get('storage_key')
        if key and not key.startswith(f'research/{self.context["request"].user.pk}/'):
            raise serializers.ValidationError({'storage_key': 'Upload a file with your own upload URL.'})
        datings = attrs.get('datings')
        if 'bibliography' in attrs:
            csl = attrs['bibliography']
            if not isinstance(csl, dict):
                raise serializers.ValidationError({'bibliography': 'Expected a bibliographic object.'})
            attrs['bibliography'] = normalize_csl({**csl, 'title': attrs.get('title',
                self.instance.title if self.instance else '')})
        for row in datings or []:
            check_bounds(row, zone=project.timezone)
        if datings is not None and sum(bool(row.get('is_primary')) for row in datings) > 1:
            raise serializers.ValidationError({'datings': 'Only one primary date is allowed.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        datings = validated_data.pop('datings', [])
        bibliography = validated_data.pop('bibliography', None)
        source = QipSource.objects.create(**validated_data)
        SourceDating.objects.bulk_create([SourceDating(source=source, **row) for row in datings])
        if bibliography is not None:
            BibliographicRecord.objects.create(source=source, csl=bibliography)
        return source

    @transaction.atomic
    def update(self, instance, validated_data):
        datings = validated_data.pop('datings', None)
        bibliography = validated_data.pop('bibliography', None)
        instance = super().update(instance, validated_data)
        if datings is not None:
            instance.datings.all().delete()
            SourceDating.objects.bulk_create([SourceDating(source=instance, **row) for row in datings])
        if bibliography is not None:
            BibliographicRecord.objects.update_or_create(source=instance, defaults={'csl': bibliography})
        return instance


class EntitySerializer(serializers.ModelSerializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    coordinate_note = serializers.CharField(required=False, allow_blank=True)
    birth = serializers.SerializerMethodField()

    class Meta:
        model = QipEntity
        fields = ['id', 'project', 'created_by', 'kind', 'type', 'label', 'description',
                  'latitude', 'longitude', 'coordinate_note', 'birth', 'created_at', 'updated_at']
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_birth(self, obj):
        if obj.kind != 'person' or not hasattr(obj.person, 'birth'):
            return None
        birth = obj.person.birth
        return {'id': birth.id, 'information': birth.information_id,
                'place': birth.place_id, 'note': birth.note}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.kind == 'geographical_place':
            data['latitude'] = instance.place.latitude
            data['longitude'] = instance.place.longitude
            data['coordinate_note'] = instance.place.coordinate_note
        return data

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move an entity.'})
        kind = attrs.get('kind', self.instance.kind if self.instance else None)
        if self.instance and kind != self.instance.kind:
            raise serializers.ValidationError({'kind': 'Cannot change an entity kind.'})
        check_type(project, 'entity', attrs.get('type', self.instance.type if self.instance else None))
        keys = ('latitude', 'longitude', 'coordinate_note')
        if kind != 'geographical_place' and any(key in attrs for key in keys):
            raise serializers.ValidationError({'coordinates': 'Only geographical places have coordinates.'})
        if kind == 'geographical_place':
            place = self.instance.place if self.instance else None
            lat = attrs.get('latitude', place.latitude if place else None)
            lon = attrs.get('longitude', place.longitude if place else None)
            if (lat is None) != (lon is None) or (lat is not None and not Decimal('-90') <= lat <= Decimal('90')) or (
                    lon is not None and not Decimal('-180') <= lon <= Decimal('180')):
                raise serializers.ValidationError({'coordinates': 'Provide a WGS84 latitude and longitude together.'})
        return attrs

    def _coordinates(self, data):
        return {key: data.pop(key) for key in ('latitude', 'longitude', 'coordinate_note') if key in data}

    @transaction.atomic
    def create(self, validated_data):
        coordinates = self._coordinates(validated_data)
        entity = QipEntity.objects.create(**validated_data)
        if entity.kind == 'person':
            QipPerson.objects.create(entity=entity)
        elif entity.kind == 'geographical_place':
            GeographicalPlace.objects.create(entity=entity, **coordinates)
        return entity

    @transaction.atomic
    def update(self, instance, validated_data):
        coordinates = self._coordinates(validated_data)
        instance = super().update(instance, validated_data)
        if coordinates:
            place = instance.place
            for key, value in coordinates.items():
                setattr(place, key, value)
            place.save()
        return instance


class CitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InformationCitation
        fields = ['source', 'locator', 'quotation', 'note']


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = InformationEvidence
        fields = ['factoid_information', 'relation', 'note']


class InformationEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = InformationEntityRelation
        fields = ['entity', 'type', 'as_written', 'note']


class InformationSerializer(serializers.ModelSerializer):
    citations = CitationSerializer(many=True, required=False)
    evidence = EvidenceSerializer(many=True, required=False)
    entities = InformationEntitySerializer(many=True, required=False)

    class Meta:
        model = QipInformation
        fields = ['id', 'project', 'created_by', 'level', 'type', 'label', 'description',
                   'date_text', *BOUNDS, *TIME_BOUNDS, 'citations', 'evidence', 'entities', 'created_at', 'updated_at']
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        project = attrs.get('project', self.instance.project if self.instance else None)
        if self.instance and project != self.instance.project:
            raise serializers.ValidationError({'project': 'Cannot move an information.'})
        level = attrs.get('level', self.instance.level if self.instance else None)
        if self.instance and level != self.instance.level:
            raise serializers.ValidationError({'level': 'Cannot change the epistemic level.'})
        check_type(project, 'information', attrs.get('type', self.instance.type if self.instance else None))
        check_bounds(attrs, self.instance, project.timezone)
        citations = attrs.get('citations')
        if level == 'factoid' and (citations is not None and not citations or
                                    citations is None and not self.instance):
            raise serializers.ValidationError({'citations': 'A factoid requires a source.'})
        for citation in citations or []:
            same_project(project, citation['source'])
        if level != 'qualified' and attrs.get('evidence'):
            raise serializers.ValidationError({'evidence': 'Only qualified information evaluates factoids.'})
        for row in attrs.get('evidence', []):
            same_project(project, row['factoid_information'])
            if row['factoid_information'].level != 'factoid':
                raise serializers.ValidationError({'evidence': 'Evidence must refer to a factoid.'})
        for row in attrs.get('entities', []):
            same_project(project, row['entity'])
            check_type(project, 'relation', row['type'])
        if self.instance and hasattr(self.instance, 'person_birth') and 'entities' in attrs:
            birth = self.instance.person_birth
            if not any(row['entity'].id == birth.person_id for row in attrs['entities']):
                raise serializers.ValidationError({'entities': 'A birth must remain linked to its person.'})
            if birth.place_id and not any(row['entity'].id == birth.place_id for row in attrs['entities']):
                raise serializers.ValidationError({'entities': 'A birth must remain linked to its place.'})
        return attrs

    def _relations(self, instance, data):
        for name, model in (('citations', InformationCitation), ('entities', InformationEntityRelation),
                            ('evidence', InformationEvidence)):
            if name in data:
                rows = data.pop(name)
                getattr(instance, name).all().delete()
                model.objects.bulk_create([model(information=instance, **row) if name != 'evidence'
                    else model(qualified_information=instance, created_by=self.context['request'].user, **row)
                    for row in rows])

    @transaction.atomic
    def create(self, validated_data):
        relations = {key: validated_data.pop(key) for key in ('citations', 'evidence', 'entities') if key in validated_data}
        instance = QipInformation.objects.create(**validated_data)
        self._relations(instance, relations)
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        relations = {key: validated_data.pop(key) for key in ('citations', 'evidence', 'entities') if key in validated_data}
        instance = super().update(instance, validated_data)
        self._relations(instance, relations)
        return instance


class PersonBirthSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonBirth
        fields = ['id', 'person', 'information', 'place', 'note']

    def validate(self, attrs):
        person = attrs.get('person', self.instance.person if self.instance else None)
        information = attrs.get('information', self.instance.information if self.instance else None)
        place = attrs.get('place', self.instance.place if self.instance else None)
        if self.instance and person != self.instance.person:
            raise serializers.ValidationError({'person': 'Cannot move a birth record.'})
        if information.level != 'qualified':
            raise serializers.ValidationError({'information': 'Birth summary requires qualified information.'})
        same_project(person.entity.project, information, *([place.entity] if place else []))
        return attrs

    def _link_birth(self, birth, old_place=None):
        project = birth.person.entity.project
        author = self.context['request'].user
        person_role, _ = ResearchType.objects.get_or_create(project=project, kind='relation',
            name='Naissance de', defaults={'created_by': author})
        InformationEntityRelation.objects.get_or_create(information=birth.information,
            entity=birth.person.entity, type=person_role)
        place_role, _ = ResearchType.objects.get_or_create(project=project, kind='relation',
            name='Lieu de naissance', defaults={'created_by': author})
        if old_place and old_place != birth.place:
            InformationEntityRelation.objects.filter(information=birth.information,
                entity=old_place.entity, type=place_role).delete()
        if birth.place:
            InformationEntityRelation.objects.get_or_create(information=birth.information,
                entity=birth.place.entity, type=place_role)

    @transaction.atomic
    def create(self, validated_data):
        birth = super().create(validated_data)
        self._link_birth(birth)
        return birth

    @transaction.atomic
    def update(self, instance, validated_data):
        old_place = instance.place
        birth = super().update(instance, validated_data)
        self._link_birth(birth, old_place)
        return birth
