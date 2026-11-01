"""Explicit, project-scoped Zotero exchange. Preview first; no inferred deletion."""
import json
import os
from datetime import timedelta
from urllib.parse import quote

from django.db import transaction
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (BibliographicRecord, ProjectMembership, QipSource, ResearchProject,
                     ZoteroCollection, ZoteroCredential, ZoteroItemLink, ZoteroOAuthAttempt, ZoteroPreview)
from .zotero_client import OAUTH, api_request, credentials, decrypt, encrypt, oauth_request, oauth_tokens, paged
from .zotero_formats import (export_ris, from_zotero, normalize_csl, parse_csl_json, parse_ris,
                             publication_bounds, ris_warnings, to_zotero, zotero_import_warnings, zotero_warnings)
from .zotero_sync import candidates, create_source, link_item, source_csl, update_source, verify_source


def project_access(request, *, write=False, owner=False):
    value = request.data.get('project') if request.method == 'POST' else request.query_params.get('project')
    project = ResearchProject.objects.filter(pk=value).first() if str(value).isdecimal() else None
    if not project or not ProjectMembership.objects.filter(project=project, user=request.user).exists():
        raise PermissionDenied('No permission in this project.')
    roles = ['owner'] if owner else ['owner', 'editor'] if write else ['owner', 'editor', 'viewer']
    if not ProjectMembership.objects.filter(project=project, user=request.user, role__in=roles).exists():
        raise PermissionDenied('No permission to change this project.')
    return project


def credential_for(user):
    credential = ZoteroCredential.objects.filter(user=user).first()
    if not credential:
        raise ValidationError({'zotero': 'Connect your Zotero account first.'})
    return credential


def selected_collection(project):
    connection = ZoteroCollection.objects.filter(project=project).select_related('connected_by').first()
    if not connection:
        raise ValidationError({'zotero': 'Select a Zotero collection for this project.'})
    return connection


def library_path(kind, library_id):
    if kind not in ('users', 'groups') or not str(library_id).isdecimal():
        raise ValidationError({'library': 'Invalid Zotero library.'})
    return f'/{kind}/{library_id}'


def collection_path(connection):
    return library_path(connection.library_kind, connection.library_id) + f'/collections/{connection.collection_key}'


def preview_payload(preview):
    return {'id': str(preview.pk), 'direction': preview.direction, 'rows': preview.rows,
            'applied': preview.applied, 'created_at': preview.created_at.isoformat()}


class ZoteroStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project = project_access(request)
        own = ZoteroCredential.objects.filter(user=request.user).first()
        collection = ZoteroCollection.objects.filter(project=project).first()
        return Response({'oauth_available': bool(os.environ.get('ZOTERO_OAUTH_CLIENT_KEY') and
            os.environ.get('ZOTERO_OAUTH_CLIENT_SECRET') and
            (settings.DEBUG or os.environ.get('ZOTERO_TOKEN_ENCRYPTION_KEY'))),
            'connected_account': {'user_id': own.zotero_user_id, 'name': own.display_name} if own else None,
            'collection': {'name': collection.name, 'key': collection.collection_key,
                'library_kind': collection.library_kind, 'library_id': collection.library_id} if collection else None})


class ZoteroOAuthStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        credentials()
        project = project_access(request, owner=True)
        callback = request.build_absolute_uri('/api/v2/zotero/oauth/callback/')
        data = oauth_tokens(oauth_request('POST', OAUTH + '/request', callback=callback))
        if not data.get('oauth_token') or not data.get('oauth_token_secret'):
            raise ValidationError({'zotero': 'Zotero did not return an authorization token.'})
        ZoteroOAuthAttempt.objects.filter(user=request.user).delete()
        ZoteroOAuthAttempt.objects.create(user=request.user, project=project, request_token=data['oauth_token'],
                                          secret_encrypted=encrypt(data['oauth_token_secret']))
        return Response({'authorize_url': OAUTH + '/authorize?oauth_token=' + quote(data['oauth_token'])})


class ZoteroOAuthCallbackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        token = request.query_params.get('oauth_token', '')
        verifier = request.query_params.get('oauth_verifier', '')
        attempt = ZoteroOAuthAttempt.objects.filter(user=request.user, request_token=token,
            created_at__gte=timezone.now() - timedelta(minutes=15)).first()
        if not attempt or not verifier:
            raise ValidationError({'zotero': 'Authorization expired or denied.'})
        data = oauth_tokens(oauth_request('POST', OAUTH + '/access', token=token,
                                          secret=decrypt(attempt.secret_encrypted), verifier=verifier))
        if not data.get('oauth_token') or not data.get('oauth_token_secret') or not data.get('userID'):
            raise ValidationError({'zotero': 'Zotero did not return a connected account.'})
        ZoteroCredential.objects.update_or_create(user=request.user, defaults={
            'zotero_user_id': data['userID'], 'display_name': data.get('username', ''),
            'token_encrypted': encrypt(data['oauth_token']),
            'token_secret_encrypted': encrypt(data['oauth_token_secret'])})
        attempt.delete()
        return HttpResponseRedirect(f'/dashboard?zotero=connected&project={attempt.project_id}')


class ZoteroLibrariesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_access(request, owner=True)
        credential = credential_for(request.user)
        groups = paged(credential, f'/users/{credential.zotero_user_id}/groups')
        return Response([{'kind': 'users', 'id': credential.zotero_user_id,
                          'name': credential.display_name or 'Bibliothèque personnelle'},
                         *[{'kind': 'groups', 'id': str(row.get('id', '')),
                            'name': row.get('data', {}).get('name', 'Groupe')}
                           for row in groups if str(row.get('id', '')).isdecimal()]])


class ZoteroCollectionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_access(request, owner=True)
        credential = credential_for(request.user)
        kind, library_id = request.query_params.get('kind'), request.query_params.get('id')
        path = library_path(kind, library_id)
        if kind == 'users' and library_id != credential.zotero_user_id:
            raise PermissionDenied('Different Zotero account.')
        if kind == 'groups' and library_id not in [str(row.get('id')) for row in paged(
                credential, f'/users/{credential.zotero_user_id}/groups')]:
            raise PermissionDenied('Not a Zotero group you belong to.')
        rows = paged(credential, path + '/collections')
        return Response([{'key': row.get('key'), 'name': row.get('data', {}).get('name'),
                          'parent': row.get('data', {}).get('parentCollection')}
                         for row in rows if row.get('key') and row.get('data', {}).get('name')])


class ZoteroConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        project = project_access(request, owner=True)
        kind = request.data.get('kind')
        library_id = str(request.data.get('library_id', ''))
        key = request.data.get('collection_key', '')
        path = library_path(kind, library_id)
        if not isinstance(key, str) or len(key) != 8 or not key.isalnum():
            raise ValidationError({'collection_key': 'Choose a Zotero collection.'})
        credential = credential_for(request.user)
        if kind == 'users' and library_id != credential.zotero_user_id:
            raise PermissionDenied('Different Zotero account.')
        if kind == 'groups' and library_id not in [str(row.get('id')) for row in paged(
                credential, f'/users/{credential.zotero_user_id}/groups')]:
            raise PermissionDenied('Not a Zotero group you belong to.')
        collection = next((row for row in paged(credential, path + '/collections') if row.get('key') == key), None)
        if not collection:
            raise ValidationError({'collection_key': 'Collection not found in this library.'})
        existing = ZoteroCollection.objects.filter(project=project).first()
        if existing and ZoteroItemLink.objects.filter(collection=existing).exists() and (
                existing.library_kind != kind or existing.library_id != library_id or existing.collection_key != key):
            raise ValidationError({'collection': 'References are linked to this collection. Preserve the existing connection.'})
        connected, _ = ZoteroCollection.objects.update_or_create(project=project, defaults={
            'connected_by': request.user, 'library_kind': kind, 'library_id': library_id,
            'collection_key': key, 'name': collection['data']['name']})
        return Response({'collection': connected.name})


class ZoteroFilePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        project = project_access(request, write=True)
        uploaded = request.FILES.get('file')
        fmt = request.data.get('format')
        if not uploaded or uploaded.size > 3 * 1024 * 1024 or fmt not in ('csl-json', 'ris'):
            raise ValidationError({'file': 'Choose a CSL JSON or RIS file under 3 MB.'})
        raw = uploaded.read()
        rows = parse_csl_json(raw, with_warnings=True) if fmt == 'csl-json' else parse_ris(raw, with_warnings=True)
        preview_rows = []
        for index, (csl, warnings) in enumerate(rows):
            if csl is None:
                preview_rows.append({'id': f'file:{index}', 'status': 'unmapped',
                    'reason': 'Reference has no usable title.', 'warnings': warnings, 'applied': False})
            else:
                preview_rows.append({'id': f'file:{index}', 'csl': csl, 'candidates': candidates(project, csl),
                    'status': 'new', 'warnings': warnings, 'applied': False,
                    'publication_span': {key: value.isoformat() for key, value in (
                        publication_bounds(csl.get('issued')) or {}).items()}})
        preview = ZoteroPreview.objects.create(project=project, user=request.user, direction='file', rows=preview_rows)
        return Response(preview_payload(preview))


class ZoteroFileExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project = project_access(request)
        fmt = request.query_params.get('file_format')
        if fmt not in ('csl-json', 'ris'):
            raise ValidationError({'format': 'Choose csl-json or ris.'})
        ids = request.query_params.get('source_ids', '')
        queryset = QipSource.objects.filter(project=project, parent__isnull=True).order_by('id')
        if ids:
            values = ids.split(',')
            if len(values) > 2000 or any(not value.isdecimal() for value in values):
                raise ValidationError({'source_ids': 'Expected source identifiers.'})
            queryset = queryset.filter(pk__in=values)
            if queryset.count() != len(set(values)):
                raise ValidationError({'source_ids': 'Unknown source in the project.'})
        items = [source_csl(source) for source in queryset[:2001]]
        if len(items) > 2000:
            raise ValidationError({'sources': 'Select at most 2000 references.'})
        if request.query_params.get('manifest') == '1':
            return Response({'warnings': [{'title': csl['title'], 'fields': ris_warnings(csl)}
                for csl in items if ris_warnings(csl)] if fmt == 'ris' else []})
        content = json.dumps(items, ensure_ascii=False, indent=2) if fmt == 'csl-json' else export_ris(items)
        response = HttpResponse(content, content_type='application/json; charset=utf-8' if fmt == 'csl-json'
                                else 'application/x-research-info-systems; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="qip-references.{"json" if fmt == "csl-json" else "ris"}"'
        return response


class ZoteroSyncPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        project = project_access(request, write=True)
        collection = selected_collection(project)
        credential = credential_for(collection.connected_by)
        remote = paged(credential, collection_path(collection) + '/items/top')
        existing = {link.item_key: link for link in ZoteroItemLink.objects.filter(
            collection=collection).select_related('source', 'source__bibliography')}
        rows, seen = [], set()
        for item in remote:
            data = item.get('data', {})
            if data.get('itemType') in ('attachment', 'note', 'annotation'):
                continue
            key = item.get('key')
            if not key or not isinstance(data.get('title'), str) or not data['title'].strip():
                rows.append({'id': f'skipped:{len(rows)}', 'status': 'unmapped',
                    'reason': 'Zotero item has no title or key.', 'applied': False})
                continue
            seen.add(key)
            csl = from_zotero(data)
            link = existing.get(key)
            row = {'id': f'remote:{key}', 'status': 'new_remote', 'csl': csl,
                   'item_key': key, 'item_version': item.get('version', data.get('version', 0)),
                   'candidates': [] if link else candidates(project, csl), 'applied': False,
                   'import_warnings': zotero_import_warnings(data),
                   'publication_span': {name: value.isoformat() for name, value in (
                       publication_bounds(csl.get('issued')) or {}).items()}}
            if link:
                local = source_csl(link.source)
                remote_changed = csl != link.last_synced
                local_changed = local != link.last_synced
                row.update({'source_id': link.source_id, 'source_updated': link.source.updated_at.isoformat(),
                            'local_csl': local, 'status': ('conflict' if local_changed and remote_changed
                            else 'remote_changed' if remote_changed else 'local_changed' if local_changed else 'unchanged')})
                row['warnings'] = zotero_warnings(local)
            rows.append(row)
        for key, link in existing.items():
            if key not in seen:
                rows.append({'id': f'missing:{key}', 'item_key': key, 'source_id': link.source_id,
                             'status': 'remote_missing', 'reason': 'Missing or moved out of the selected collection.',
                             'applied': False})
        linked_ids = {link.source_id for link in existing.values()}
        for source in QipSource.objects.filter(project=project, parent__isnull=True).select_related('bibliography'):
            if source.pk not in linked_ids:
                rows.append({'id': f'local:{source.pk}', 'status': 'local_new', 'source_id': source.pk,
                             'source_updated': source.updated_at.isoformat(), 'local_csl': source_csl(source),
                             'warnings': zotero_warnings(source_csl(source)), 'applied': False})
        identity = f'{collection.library_kind}:{collection.library_id}:{collection.collection_key}'
        for row in rows:
            row['collection_identity'] = identity
        preview = ZoteroPreview.objects.create(project=project, user=request.user,
            collection=collection, direction='sync', rows=rows)
        return Response(preview_payload(preview))


class ZoteroPreviewDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        preview = ZoteroPreview.objects.filter(pk=pk, user=request.user,
            project__memberships__user=request.user).first()
        if not preview:
            raise PermissionDenied('Unknown preview.')
        return Response(preview_payload(preview))


def remote_item(credential, connection, key):
    response = api_request(credential, 'GET', library_path(connection.library_kind, connection.library_id) +
                           '/items/' + key)
    item = response.json()
    return item


def apply_remote(preview, row, decision):
    project = preview.project
    connection = preview.collection
    credential = credential_for(connection.connected_by)
    action = decision['action']
    if row['status'] in ('remote_missing', 'unmapped'):
        raise ValidationError({'action': 'Cannot write missing or unsupported references.'})
    key = row.get('item_key')
    if action in ('create', 'link', 'update'):
        if not key or row['status'] not in ('new_remote', 'remote_changed', 'conflict', 'local_changed', 'unchanged'):
            raise ValidationError({'action': 'Expected a Zotero reference.'})
        current = remote_item(credential, connection, key)
        if current.get('version') != row['item_version'] or connection.collection_key not in current.get('data', {}).get('collections', []):
            raise ValidationError({'zotero': 'Zotero changed since preview; prepare a new comparison.'})
        csl = from_zotero(current['data'])
        if csl != row['csl']:
            raise ValidationError({'zotero': 'Zotero changed since preview; prepare a new comparison.'})
        if action == 'create':
            if row.get('source_id'):
                raise ValidationError({'action': 'Already linked. Choose update or ignore.'})
            source = create_source(project, preview.user, csl)
        elif action == 'link':
            if row.get('source_id'):
                raise ValidationError({'action': 'Already linked.'})
            source = verify_source(project, row, decision.get('source_id'))
            update_source(source, csl, overwrite=False)
        else:
            source = verify_source(project, row, decision.get('source_id') or row.get('source_id'))
            if row.get('source_id') and source.id != row['source_id']:
                raise ValidationError({'source': 'Choose the linked Qip source.'})
            update_source(source, csl, overwrite=True)
        link_item(source, connection, key, current['version'], csl)
        return source
    if action == 'push':
        if row['status'] not in ('local_new', 'local_changed', 'remote_changed', 'conflict', 'unchanged'):
            raise ValidationError({'action': 'Cannot send this row to Zotero.'})
        source = verify_source(project, row, row.get('source_id'))
        csl = source_csl(source)
        if csl != row['local_csl']:
            raise ValidationError({'source': 'Source changed since preview.'})
        path = library_path(connection.library_kind, connection.library_id) + '/items'
        data = to_zotero(csl)
        if key:
            current = remote_item(credential, connection, key)
            if current.get('version') != row['item_version'] or from_zotero(current['data']) != row['csl']:
                raise ValidationError({'zotero': 'Zotero changed since preview; prepare a new comparison.'})
            # PATCH only bibliographic fields: preserve collections, attachments and unknown Zotero fields.
            response = api_request(credential, 'PATCH', path + '/' + key, payload=data, version=current['version'])
            updated = response.json() if response.content else {}
            version = updated.get('version') or int(response.headers.get('Last-Modified-Version', current['version'] + 1))
        else:
            data['collections'] = [connection.collection_key]
            response = api_request(credential, 'POST', path, payload=[data])
            written = response.json()
            if written.get('failed') or not written.get('successful', {}).get('0'):
                raise ValidationError({'zotero': 'Zotero did not create the reference.'})
            item = written['successful']['0']
            key = item['key']
            version = item['version']
        link_item(source, connection, key, version, csl)
        return source
    raise ValidationError({'action': 'Unknown decision.'})


class ZoteroPreviewApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        preview = ZoteroPreview.objects.filter(pk=pk, user=request.user).select_related('project', 'collection').first()
        if not preview:
            raise PermissionDenied('Unknown preview.')
        membership = ProjectMembership.objects.filter(project=preview.project, user=request.user,
                                                       role__in=['owner', 'editor']).exists()
        if not membership:
            raise PermissionDenied('No permission to apply this preview.')
        if preview.applied or preview.created_at < timezone.now() - timedelta(minutes=30):
            raise ValidationError({'preview': 'Already applied or expired. Prepare another comparison.'})
        if preview.collection and ZoteroCollection.objects.filter(pk=preview.collection_id,
                project=preview.project).exists() is False:
            raise ValidationError({'collection': 'Connection changed.'})
        if preview.collection and any(row.get('collection_identity') !=
                f'{preview.collection.library_kind}:{preview.collection.library_id}:{preview.collection.collection_key}'
                for row in preview.rows):
            raise ValidationError({'collection': 'Collection changed since preview.'})
        decisions = request.data.get('decisions')
        if not isinstance(decisions, list) or len(decisions) != len(preview.rows):
            raise ValidationError({'decisions': 'Provide one decision per row.'})
        choices = {row['id']: row for row in preview.rows}
        if set(row.get('id') for row in decisions if isinstance(row, dict)) != set(choices) or len({
                row.get('id') for row in decisions if isinstance(row, dict)}) != len(decisions):
            raise ValidationError({'decisions': 'Unknown or duplicate row.'})
        outcomes = []
        for decision in decisions:
            row = choices[decision['id']]
            action = decision.get('action')
            if row.get('applied'):
                outcomes.append({'id': row['id'], 'status': 'previously_applied'}); continue
            if action == 'ignore':
                row['applied'] = True
                outcomes.append({'id': row['id'], 'status': 'ignored'}); continue
            if preview.direction == 'file':
                if row['status'] == 'unmapped':
                    raise ValidationError({'action': 'A reference without a usable title can only be ignored.'})
                if action not in ('create', 'update', 'link'):
                    raise ValidationError({'action': 'Choose create, link, update or ignore.'})
                with transaction.atomic():
                    if action == 'create':
                        source = create_source(preview.project, request.user, row['csl'])
                    else:
                        source = verify_source(preview.project, row, decision.get('source_id'))
                        update_source(source, row['csl'], overwrite=action == 'update')
            else:
                if preview.collection_id != ZoteroCollection.objects.get(project=preview.project).pk:
                    raise ValidationError({'collection': 'Collection changed since preview.'})
                with transaction.atomic():
                    source = apply_remote(preview, row, decision)
            row['applied'] = True
            outcomes.append({'id': row['id'], 'status': 'applied', 'source_id': source.id})
            # Persist after each item: a later remote failure cannot replay a successful remote write.
            preview.rows = list(choices.values())
            preview.save(update_fields=['rows'])
        preview.rows = list(choices.values())
        preview.applied = all(row['applied'] for row in preview.rows)
        preview.save(update_fields=['rows', 'applied'])
        return Response({'outcomes': outcomes, 'applied': preview.applied})
