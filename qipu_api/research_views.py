import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import FileResponse
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (ResearchProject, ProjectMembership, ResearchType, HistoricalEntity,
                     ResearchMedia, EpistemicStatus, ResearchItem)
from .research_serializers import (
    ResearchProjectSerializer, ProjectMembershipSerializer, ResearchTypeSerializer,
    HistoricalEntitySerializer, ResearchMediaSerializer, EpistemicStatusSerializer,
    ResearchItemSerializer,
)
from .utility import generate_signed_url


def require_role(user, project, roles):
    if not ProjectMembership.objects.filter(project=project, user=user, role__in=roles).exists():
        raise PermissionDenied('No permission in this project.')


class ProjectScopedViewSet(viewsets.ModelViewSet):
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
        project = serializer.validated_data['project']
        require_role(self.request.user, project, ['owner', 'editor'])
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


class ResearchProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ResearchProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ResearchProject.objects.filter(memberships__user=self.request.user).distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        project = serializer.save(owner=self.request.user)
        ProjectMembership.objects.create(project=project, user=self.request.user, role='owner')

    def perform_update(self, serializer):
        require_role(self.request.user, serializer.instance, ['owner'])
        serializer.save()

    def perform_destroy(self, instance):
        raise PermissionDenied('Projects are preserved to protect their research data.')


class ProjectMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectMembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ProjectMembership.objects.filter(project__memberships__user=self.request.user).distinct()
        project = self.request.query_params.get('project')
        if project:
            if not project.isdecimal():
                raise ValidationError({'project': 'Expected a project id.'})
            queryset = queryset.filter(project_id=project)
        return queryset

    def perform_create(self, serializer):
        require_role(self.request.user, serializer.validated_data['project'], ['owner'])
        serializer.save()

    def perform_update(self, serializer):
        require_role(self.request.user, serializer.instance.project, ['owner'])
        serializer.save()

    def perform_destroy(self, instance):
        require_role(self.request.user, instance.project, ['owner'])
        if instance.user_id == instance.project.owner_id:
            raise ValidationError({'user': 'The project owner cannot leave the project.'})
        instance.delete()


class ResearchTypeViewSet(ProjectScopedViewSet):
    queryset = ResearchType.objects.all()
    serializer_class = ResearchTypeSerializer


class HistoricalEntityViewSet(ProjectScopedViewSet):
    queryset = HistoricalEntity.objects.all()
    serializer_class = HistoricalEntitySerializer


class ResearchMediaViewSet(ProjectScopedViewSet):
    queryset = ResearchMedia.objects.all()
    serializer_class = ResearchMediaSerializer

    @action(detail=False, methods=['post'], url_path='upload-url')
    def upload_url(self, request):
        if settings.QIP_LOCAL_STORAGE:
            raise ValidationError({'detail': 'Use upload-file in local mode.'})
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

    @action(detail=False, methods=['post'], url_path='upload-file')
    def upload_file(self, request):
        if not settings.QIP_LOCAL_STORAGE:
            raise ValidationError({'detail': 'Local file uploads are disabled.'})
        project = ResearchProject.objects.filter(pk=request.data.get('project')).first()
        if not project:
            raise ValidationError({'project': 'Unknown project.'})
        require_role(request.user, project, ['owner', 'editor'])
        file = request.FILES.get('file')
        if not file:
            raise ValidationError({'file': 'A file is required.'})
        name = os.path.basename(file.name)
        key = default_storage.save(f'research/{request.user.pk}/{uuid.uuid4().hex}/{name}', file)
        return Response({'storage_key': key}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='file')
    def file(self, request, pk=None):
        media = self.get_object()
        while media and not media.storage_key:
            media = media.parent
        if not media:
            return Response({'detail': 'No file attached.'}, status=status.HTTP_404_NOT_FOUND)
        if settings.QIP_LOCAL_STORAGE:
            return Response({'signed_url': f'/api/v1/media/{pk}/download/'})
        return Response({'signed_url': generate_signed_url(
            os.environ['GS_BUCKET_NAME'], media.storage_key, method='GET')})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        if not settings.QIP_LOCAL_STORAGE:
            return Response(status=status.HTTP_404_NOT_FOUND)
        media = self.get_object()
        while media and not media.storage_key:
            media = media.parent
        if not media or not default_storage.exists(media.storage_key):
            return Response(status=status.HTTP_404_NOT_FOUND)
        return FileResponse(default_storage.open(media.storage_key, 'rb'),
                            content_type=media.content_type or 'application/octet-stream')


class EpistemicStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EpistemicStatus.objects.all()
    serializer_class = EpistemicStatusSerializer
    permission_classes = [IsAuthenticated]


class ResearchItemViewSet(ProjectScopedViewSet):
    queryset = ResearchItem.objects.all()
    serializer_class = ResearchItemSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related('type', 'epistemic_status')
        params = self.request.query_params
        for name, lookup in (('entity_id', 'entity_participations__entity_id'),
                             ('type_id', 'type_id'), ('epistemic_status_id', 'epistemic_status_id')):
            value = params.get(name)
            if value:
                if not value.isdecimal():
                    raise ValidationError({name: 'Expected an integer id.'})
                queryset = queryset.filter(**{lookup: value})
        # Incomplete spans remain visible if their known bounds overlap the requested range.
        if params.get('from') or params.get('to'):
            from rest_framework.fields import DateField
            parser = DateField()
            queryset = queryset.exclude(begin_of_begin__isnull=True, end_of_begin__isnull=True,
                                        begin_of_end__isnull=True, end_of_end__isnull=True)
            if params.get('from'):
                start = parser.run_validation(params['from'])
                queryset = queryset.filter(Q(end_of_end__gte=start) |
                                           Q(end_of_end__isnull=True, begin_of_end__gte=start) |
                                           Q(end_of_end__isnull=True, begin_of_end__isnull=True))
            if params.get('to'):
                end = parser.run_validation(params['to'])
                queryset = queryset.filter(Q(begin_of_begin__lte=end) |
                                           Q(begin_of_begin__isnull=True, end_of_begin__lte=end) |
                                           Q(begin_of_begin__isnull=True, end_of_begin__isnull=True))
        return queryset.distinct().order_by('begin_of_begin', 'id')
