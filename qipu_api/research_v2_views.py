import os
import shlex
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (ProjectMembership, ResearchProject, ResearchType, QipSource,
                     QipEntity, QipInformation, PersonBirth)
from .research_v2_serializers import (V2TypeSerializer, SourceSerializer, EntitySerializer,
                                       InformationSerializer, PersonBirthSerializer, BOUNDS, historical_instant)
from .utility import generate_signed_url


def require_role(user, project, roles):
    if not ProjectMembership.objects.filter(project=project, user=user, role__in=roles).exists():
        raise PermissionDenied('No permission in this project.')


class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset().filter(project__memberships__user=self.request.user)
        project = self.request.query_params.get('project')
        if project:
            if not project.isdecimal():
                raise ValidationError({'project': 'Expected a project id.'})
            queryset = queryset.filter(project_id=project)
        return queryset.distinct()

    def perform_create(self, serializer):
        require_role(self.request.user, serializer.validated_data['project'], ['owner', 'editor'])
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        require_role(self.request.user, serializer.instance.project, ['owner', 'editor'])
        serializer.save()

    def perform_destroy(self, instance):
        require_role(self.request.user, instance.project, ['owner', 'editor'])
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError({'detail': 'Referenced research data cannot be deleted.'})


class TypeViewSet(ProjectViewSet):
    queryset = ResearchType.objects.all()
    serializer_class = V2TypeSerializer


class SourceViewSet(ProjectViewSet):
    queryset = QipSource.objects.all().prefetch_related('datings')
    serializer_class = SourceSerializer

    @action(detail=False, methods=['post'], url_path='upload-file')
    def upload_file(self, request):
        if not settings.QIP_LOCAL_STORAGE:
            raise ValidationError({'detail': 'Local uploads disabled.'})
        project = ResearchProject.objects.filter(pk=request.data.get('project')).first()
        if not project:
            raise ValidationError({'project': 'Unknown project.'})
        require_role(request.user, project, ['owner', 'editor'])
        file = request.FILES.get('file')
        if not file:
            raise ValidationError({'file': 'A file is required.'})
        key = default_storage.save(f'research/{request.user.pk}/{uuid.uuid4().hex}/{os.path.basename(file.name)}', file)
        return Response({'storage_key': key}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='upload-url')
    def upload_url(self, request):
        if settings.QIP_LOCAL_STORAGE:
            raise ValidationError({'detail': 'Use upload-file locally.'})
        project = ResearchProject.objects.filter(pk=request.data.get('project')).first()
        if not project:
            raise ValidationError({'project': 'Unknown project.'})
        require_role(request.user, project, ['owner', 'editor'])
        filename = request.data.get('filename', '')
        content_type = request.data.get('content_type', '')
        if not filename or filename != os.path.basename(filename) or filename in ('.', '..') or not content_type:
            raise ValidationError({'filename': 'Filename and content type are required.'})
        key = f'research/{request.user.pk}/{uuid.uuid4().hex}/{filename}'
        return Response({'storage_key': key, 'signed_url': generate_signed_url(
            os.environ['GS_BUCKET_NAME'], key, content_type, method='PUT')})

    def _file_owner(self):
        source = self.get_object()
        while source and not source.storage_key:
            source = source.parent
        return source

    @action(detail=True, methods=['get'], url_path='file')
    def file(self, request, pk=None):
        source = self._file_owner()
        if not source:
            return Response(status=404)
        if settings.QIP_LOCAL_STORAGE:
            return Response({'signed_url': f'/api/v2/sources/{pk}/download/'})
        return Response({'signed_url': generate_signed_url(
            os.environ['GS_BUCKET_NAME'], source.storage_key, method='GET')})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        if not settings.QIP_LOCAL_STORAGE:
            return Response(status=404)
        source = self._file_owner()
        if not source or not default_storage.exists(source.storage_key):
            return Response(status=404)
        return FileResponse(default_storage.open(source.storage_key, 'rb'),
                            content_type=source.content_type or 'application/octet-stream')


class EntityViewSet(ProjectViewSet):
    queryset = QipEntity.objects.all()
    serializer_class = EntitySerializer


class InformationViewSet(ProjectViewSet):
    queryset = QipInformation.objects.all().prefetch_related('citations', 'entities', 'evidence')
    serializer_class = InformationSerializer


class BirthViewSet(viewsets.ModelViewSet):
    queryset = PersonBirth.objects.all()
    serializer_class = PersonBirthSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(person__entity__project__memberships__user=self.request.user).distinct()

    def perform_create(self, serializer):
        require_role(self.request.user, serializer.validated_data['person'].entity.project, ['owner', 'editor'])
        serializer.save()

    def perform_update(self, serializer):
        require_role(self.request.user, serializer.instance.person.entity.project, ['owner', 'editor'])
        serializer.save()

    def perform_destroy(self, instance):
        require_role(self.request.user, instance.person.entity.project, ['owner', 'editor'])
        instance.delete()


class TimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project', '')
        project = ResearchProject.objects.filter(pk=project_id).first() if project_id.isdecimal() else None
        if not project or not ProjectMembership.objects.filter(project=project, user=request.user).exists():
            raise PermissionDenied('No permission in this project.')
        include = set(request.query_params.get('include', 'source,factoid,qualified').split(','))
        axes = set(request.query_params.get('axes', 'historical,recorded').split(','))
        if not include <= {'source', 'factoid', 'qualified'} or not axes <= {'historical', 'recorded'}:
            raise ValidationError({'filters': 'Unknown content or time axis.'})
        result = []

        def append(resource, kind, date=None, date_kind=None):
            base = {'resource_kind': kind, 'resource_id': resource.id, 'label': resource.title if kind == 'source' else resource.label,
                    'recorded_at': resource.created_at.isoformat(), 'project': project.id}
            if 'recorded' in axes:
                result.append({**base, 'time_axis': 'recorded', 'timestamp': resource.created_at.isoformat()})
            if 'historical' in axes and date and any(getattr(date, key) for key in BOUNDS):
                result.append({**base, 'time_axis': 'historical', 'date_kind': date_kind,
                                'historical_time_span': {key: getattr(date, key).isoformat() if getattr(date, key) else None
                                                         for key in BOUNDS},
                               'historical_instants': {key: historical_instant(getattr(date, key),
                                   getattr(date, f'{key}_time'), project.timezone) for key in BOUNDS},
                               'historical_day_limits': {key: {
                                   'start': datetime.combine(getattr(date, key), time.min, ZoneInfo(project.timezone)).isoformat(),
                                   'end': datetime.combine(getattr(date, key) + timedelta(days=1), time.min,
                                                           ZoneInfo(project.timezone)).isoformat()}
                                   if getattr(date, key) else None for key in BOUNDS},
                               'date_text': date.date_text})

        if 'source' in include:
            for source in QipSource.objects.filter(project=project).prefetch_related('datings'):
                datings = list(source.datings.all())
                primary = next((row for row in datings if row.is_primary), datings[0] if len(datings) == 1 else None)
                append(source, 'source', primary, primary.date_kind if primary else None)
        levels = include & {'factoid', 'qualified'}
        for information in QipInformation.objects.filter(project=project, level__in=levels):
            append(information, information.level, information)
        return Response(result)


class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project', '')
        project = ResearchProject.objects.filter(pk=project_id).first() if project_id.isdecimal() else None
        if not project or not ProjectMembership.objects.filter(project=project, user=request.user).exists():
            raise PermissionDenied('No permission in this project.')
        query = request.query_params.get('q', '').strip()
        kind = request.query_params.get('kind', 'all')
        field = request.query_params.get('field', 'all')
        try:
            terms = list(dict.fromkeys(shlex.split(query)))
        except ValueError:
            raise ValidationError({'q': 'Unclosed quotation mark.'})
        limit = request.query_params.get('limit', '50')
        offset = request.query_params.get('offset', '0')
        if len(query) > 250 or kind not in ('all', 'source', 'factoid', 'qualified', 'entity', 'type') or field not in (
                'all', 'label', 'description', 'reference', 'author', 'citation', 'date') or len(terms) > 8 or not (
                limit.isdecimal() and 1 <= int(limit) <= 100 and offset.isdecimal() and int(offset) <= 100000):
            raise ValidationError({'filters': 'Invalid search criteria.'})

        def matches(fields, term):
            chosen = (path for paths in fields.values() for path in paths) if field == 'all' else fields.get(field, ())
            condition = Q()
            for path in chosen:
                condition |= Q(**{f'{path}__icontains': term})
            return condition

        results = []
        definitions = (
            ('source', QipSource, 'title', {'label': ('title',), 'description': ('description',),
                'reference': ('reference', 'locator'), 'author': ('author_label',), 'date': ('datings__date_text',)}),
            ('entity', QipEntity, 'label', {'label': ('label',), 'description': ('description',)}),
            ('type', ResearchType, 'name', {'label': ('name',), 'description': ('definition',), 'reference': ('semantic_uri',)}),
            ('factoid', QipInformation, 'label', {'label': ('label',), 'description': ('description',),
                'citation': ('citations__quotation', 'citations__locator', 'citations__note'), 'date': ('date_text',)}),
            ('qualified', QipInformation, 'label', {'label': ('label',), 'description': ('description',),
                'citation': ('citations__quotation', 'citations__locator', 'citations__note'), 'date': ('date_text',)}),
        )
        for resource_kind, model, label, fields in definitions:
            if kind != 'all' and kind != resource_kind:
                continue
            queryset = model.objects.filter(project=project)
            if model is QipInformation:
                queryset = queryset.filter(level=resource_kind)
            if terms:
                matched = {}
                if field == 'all' or field in fields:
                    for term in terms:
                        for pk in queryset.filter(matches(fields, term)).values_list('pk', flat=True).distinct():
                            matched.setdefault(pk, []).append(term)
                queryset = queryset.filter(pk__in=matched)
            else:
                matched = {}
            for row in queryset.order_by('pk'):
                results.append({'resource_kind': resource_kind, 'resource_id': row.pk,
                                'label': getattr(row, label), 'matched_terms': matched.get(row.pk, [])})
        start = int(offset)
        end = start + int(limit)
        return Response({'results': results[start:end], 'terms': terms, 'total': len(results),
                         'next_offset': end if end < len(results) else None, 'truncated': end < len(results)})
