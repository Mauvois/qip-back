import json
import os
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import (BibliographicRecord, QipSource, ResearchProject, User, ZoteroCollection,
                     ZoteroCredential, ZoteroItemLink)
from .zotero_formats import from_zotero, parse_csl_json, parse_ris, publication_bounds, to_zotero
from .zotero_client import decrypt
from .zotero_sync import create_source, update_source


@override_settings(SECURE_SSL_REDIRECT=False)
class ZoteroExchangeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='zotero_owner', email='z@example.test', password='pass')
        self.other = User.objects.create_user(username='zotero_other', email='o@example.test', password='pass')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.project = self.client.post('/api/v2/projects/', {'name': 'Zotero'}, format='json').data['id']

    def preview_file(self, text, fmt='csl-json'):
        name = 'references.json' if fmt == 'csl-json' else 'references.ris'
        return self.client.post('/api/v2/zotero/file/preview/', {'project': self.project, 'format': fmt,
            'file': SimpleUploadedFile(name, text.encode('utf-8'))}, format='multipart')

    def test_file_preview_and_roundtrip_keep_imprecise_date_and_factoid_links(self):
        data = [{'type': 'article-journal', 'title': 'Article historique', 'DOI': '10.1111/test',
                 'author': [{'family': 'Durand', 'given': 'Anne'}],
                 'issued': {'raw': 'vers 1870'}, 'container-title': 'Revue'}]
        preview = self.preview_file(json.dumps(data))
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(QipSource.objects.count(), 0)
        row = preview.data['rows'][0]
        applied = self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': [{'id': row['id'], 'action': 'create'}]}, format='json')
        self.assertEqual(applied.status_code, 200, applied.data)
        source = QipSource.objects.get()
        self.assertEqual(source.datings.get().date_text, 'vers 1870')
        self.assertIsNone(source.datings.get().begin_of_begin)
        self.assertEqual(source.bibliography.csl['DOI'], '10.1111/test')
        exported = self.client.get('/api/v2/zotero/file/export/', {'project': self.project, 'file_format': 'csl-json'})
        self.assertEqual(parse_csl_json(exported.content)[0]['DOI'], '10.1111/test')
        ris = self.client.get('/api/v2/zotero/file/export/', {'project': self.project, 'file_format': 'ris'})
        self.assertEqual(parse_ris(ris.content)[0]['title'], 'Article historique')
        self.assertEqual(self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': [{'id': row['id'], 'action': 'create'}]}, format='json').status_code, 400)

    def test_possible_duplicate_requires_explicit_choice_and_access_is_scoped(self):
        existing = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Ouvrage'}, format='json').data['id']
        preview = self.preview_file('[{"title":"Ouvrage","DOI":"10.42/reference"}]')
        self.assertEqual(preview.data['rows'][0]['candidates'][0]['id'], existing)
        self.assertEqual(QipSource.objects.count(), 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/v2/zotero/preview/{preview.data['id']}/").status_code, 403)
        self.assertEqual(self.client.get('/api/v2/zotero/file/export/',
            {'project': self.project, 'file_format': 'ris'}).status_code, 403)
        self.client.force_authenticate(self.owner)
        decision = [{'id': preview.data['rows'][0]['id'], 'action': 'link', 'source_id': existing}]
        self.assertEqual(self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': decision}, format='json').status_code, 200)
        self.assertEqual(QipSource.objects.count(), 1)
        self.assertEqual(BibliographicRecord.objects.count(), 1)

    def test_editing_bibliography_preserves_existing_information_citations(self):
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Registre',
            'bibliography': {'type': 'book', 'DOI': '10.55/old'}}, format='json')
        self.assertEqual(source.status_code, 201, source.data)
        self.assertEqual(source.data['bibliography']['DOI'], '10.55/old')
        updated = self.client.patch(f"/api/v2/sources/{source.data['id']}/",
            {'bibliography': {'type': 'book', 'DOI': '10.55/new'}}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['bibliography']['DOI'], '10.55/new')
        unsafe = self.client.patch(f"/api/v2/sources/{source.data['id']}/",
            {'bibliography': {'URL': 'javascript:alert(1)'}}, format='json')
        self.assertEqual(unsafe.status_code, 200, unsafe.data)
        self.assertNotIn('URL', unsafe.data['bibliography'])

    def test_remote_publication_change_updates_only_an_unqualified_imported_dating(self):
        project = ResearchProject.objects.get(pk=self.project)
        source = create_source(project, self.owner, {'title': 'Chronique', 'issued': {'raw': 'vers 1850'}})
        update_source(source, {'title': 'Chronique', 'issued': {'raw': 'vers 1852'}}, overwrite=True)
        self.assertEqual(source.datings.get().date_text, 'vers 1852')
        dating = source.datings.get()
        dating.begin_of_begin = '1852-01-01'
        dating.save()
        update_source(source, {'title': 'Chronique', 'issued': {'raw': 'vers 1855'}}, overwrite=True)
        self.assertEqual(source.datings.get().date_text, 'vers 1852')
        self.assertEqual(source.datings.get().begin_of_begin.isoformat(), '1852-01-01')

    def test_identifier_match_suggested_even_when_title_changes(self):
        self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Ancien titre',
            'bibliography': {'type': 'book', 'DOI': '10.55/stable'}}, format='json')
        preview = self.preview_file('[{"title":"Nouveau titre","DOI":"10.55/STABLE"}]')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['rows'][0]['candidates'][0]['reason'], 'identifier')

    def test_ris_parser_and_invalid_file(self):
        ris = 'TY  - BOOK\nTI  - Cahier\nAU  - Martin, Luc\nPY  - 1900?\nER  - \n'
        self.assertEqual(self.preview_file(ris, fmt='ris').data['rows'][0]['csl']['issued']['raw'], '1900?')
        self.assertEqual(self.preview_file('{invalid').status_code, 400)
        untitled = self.preview_file('[{"URL":"https://example.test/record"},{"title":"Valide"}]')
        self.assertEqual(untitled.status_code, 200, untitled.data)
        self.assertEqual(untitled.data['rows'][0]['status'], 'unmapped')
        self.assertEqual(untitled.data['rows'][1]['status'], 'new')
        with_unmapped = self.preview_file('[{"title":"Livre","id":"export-id","note":"interne"}]')
        self.assertEqual(with_unmapped.data['rows'][0]['warnings'], ['note'])
        self.assertEqual(with_unmapped.data['rows'][0]['csl']['id'], 'export-id')
        unsafe_url = self.preview_file('[{"title":"Livre","URL":"javascript:alert(1)"}]')
        self.assertEqual(unsafe_url.status_code, 200, unsafe_url.data)
        self.assertNotIn('URL', unsafe_url.data['rows'][0]['csl'])
        self.assertIn('URL', unsafe_url.data['rows'][0]['warnings'])

    def test_csl_import_tolerates_zotero_urls_and_long_titles(self):
        data = [{'id': 'http://zotero.org/users/2170690/items/B4MCRDJM', 'type': 'document',
                 'title': 'Titre ' * 70, 'URL': 'centroprodh.org.mx/document.pdf',
                 'author': [{'family': 'Centre de documentation', 'given': ''}]},
                {'title': 'Lien à écarter', 'URL': 'file:///private/report.pdf'}]
        preview = self.preview_file(json.dumps(data))
        self.assertEqual(preview.status_code, 200, preview.data)
        first, second = preview.data['rows']
        self.assertEqual(first['csl']['URL'], 'https://centroprodh.org.mx/document.pdf')
        self.assertIn('URL (https added)', first['warnings'])
        self.assertEqual(first['csl']['id'], data[0]['id'])
        self.assertGreater(len(first['csl']['title']), 250)
        self.assertNotIn('URL', second['csl'])
        self.assertIn('URL', second['warnings'])

    def test_zotero_date_parts_place_only_known_precision_on_historical_timeline(self):
        cases = [('Année', ['2004'], '2004-01-01', '2004-12-31'),
                 ('Mois', ['1998', 10], '1998-10-01', '1998-10-31'),
                 ('Jour', ['1997', 10, 1], '1997-10-01', '1997-10-01'),
                 ('Bissextile', ['2000', 2], '2000-02-01', '2000-02-29')]
        data = [{'id': 'http://zotero.org/users/2170690/items/M33I6NAW',
                 'type': 'article-journal', 'title': title, 'issued': {'date-parts': [parts]},
                 'accessed': {'date-parts': [[2015, 4, 24]]}, 'ISSN': '0022-216X',
                 'source': 'JSTOR', 'container-title': 'Journal of Latin American Studies'}
                for title, parts, _, _ in cases]
        data.append({'title': 'Datation incertaine', 'issued': {'raw': 'vers 1870'}})
        preview = self.preview_file(json.dumps(data))
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['rows'][0]['publication_span']['end_of_end'], '2004-12-31')
        self.assertEqual(preview.data['rows'][1]['csl']['issued']['date-parts'], [['1998', 10]])
        decisions = [{'id': row['id'], 'action': 'create'} for row in preview.data['rows']]
        applied = self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
                                   {'decisions': decisions}, format='json')
        self.assertEqual(applied.status_code, 200, applied.data)
        for title, parts, first, last in cases:
            source = QipSource.objects.get(title=title)
            dating = source.datings.get(date_kind='publication')
            self.assertEqual(dating.begin_of_begin.isoformat(), first)
            self.assertEqual(dating.end_of_end.isoformat(), last)
            self.assertEqual(source.bibliography.csl['accessed']['date-parts'], [[2015, 4, 24]])
            self.assertEqual(source.bibliography.csl['ISSN'], '0022-216X')
        self.assertIsNone(QipSource.objects.get(title='Datation incertaine').datings.get().begin_of_begin)
        historical = self.client.get('/api/v2/timeline/', {'project': self.project, 'axes': 'historical'})
        self.assertEqual(historical.status_code, 200, historical.data)
        self.assertEqual({entry['label'] for entry in historical.data}, {title for title, *_ in cases})
        exported = self.client.get('/api/v2/zotero/file/export/', {'project': self.project, 'file_format': 'csl-json'})
        restored = {entry['title']: entry for entry in json.loads(exported.content)}
        self.assertEqual(restored['Mois']['issued']['date-parts'], [['1998', 10]])
        self.assertEqual(restored['Mois']['source'], 'JSTOR')

    def test_publication_update_refreshes_derived_bounds_but_preserves_manual_bounds(self):
        project = ResearchProject.objects.get(pk=self.project)
        source = create_source(project, self.owner, {'title': 'Titre', 'issued': {'date-parts': [[1997]]}})
        update_source(source, {'title': 'Titre', 'issued': {'date-parts': [[2000, 2]]}}, overwrite=True)
        dating = source.datings.get()
        self.assertEqual(dating.begin_of_begin.isoformat(), '2000-02-01')
        self.assertEqual(dating.end_of_end.isoformat(), '2000-02-29')
        dating.begin_of_begin = '1999-01-01'
        dating.save()
        update_source(source, {'title': 'Titre', 'issued': {'date-parts': [[2001]]}}, overwrite=True)
        self.assertEqual(source.datings.get().begin_of_begin.isoformat(), '1999-01-01')

    def test_inexact_and_invalid_dates_are_never_fabricated(self):
        self.assertIsNone(publication_bounds({'raw': 'vers 1870'}))
        self.assertIsNone(publication_bounds({'date-parts': [[2001, 2, 29]]}))
        self.assertIsNone(publication_bounds({'raw': '2012-2014'}))
        seasonal = {'date-parts': [[2003]], 'season': 'Abril'}
        self.assertEqual(publication_bounds(seasonal)['end_of_end'].isoformat(), '2003-12-31')
        self.assertEqual(parse_csl_json(json.dumps({'title': 'Saison', 'issued': seasonal}))[0]['issued'], seasonal)

    def test_ris_export_reports_fields_it_cannot_represent(self):
        created = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Cahier',
            'bibliography': {'type': 'book', 'editor': [{'literal': 'Archiviste'}],
                             'language': 'fr'}}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        manifest = self.client.get('/api/v2/zotero/file/export/', {'project': self.project,
            'file_format': 'ris', 'source_ids': created.data['id'], 'manifest': '1'}).data
        self.assertEqual(manifest['warnings'][0]['fields'], ['editor', 'language'])
        missing = self.client.get('/api/v2/zotero/file/export/', {'project': self.project,
            'file_format': 'ris', 'source_ids': 999999})
        self.assertEqual(missing.status_code, 400)

    @patch.dict(os.environ, {'ZOTERO_OAUTH_CLIENT_KEY': 'test-key', 'ZOTERO_OAUTH_CLIENT_SECRET': 'test-secret',
                             'ZOTERO_TOKEN_ENCRYPTION_KEY': 'test-encryption-key'})
    @patch('qipu_api.zotero_views.oauth_request')
    def test_oauth_callback_stores_encrypted_tokens_only_for_authorized_user(self, oauth):
        oauth.return_value.text = 'oauth_token=request-token&oauth_token_secret=request-secret'
        start = self.client.post('/api/v2/zotero/oauth/start/', {'project': self.project}, format='json')
        self.assertEqual(start.status_code, 200, start.data)
        self.assertIn('request-token', start.data['authorize_url'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v2/zotero/oauth/callback/', {
            'oauth_token': 'request-token', 'oauth_verifier': 'verifier'}).status_code, 400)
        self.client.force_authenticate(self.owner)
        oauth.return_value.text = 'oauth_token=private-access&oauth_token_secret=private-secret&userID=77&username=Archiviste'
        callback = self.client.get('/api/v2/zotero/oauth/callback/', {
            'oauth_token': 'request-token', 'oauth_verifier': 'verifier'})
        self.assertEqual(callback.status_code, 302)
        credential = ZoteroCredential.objects.get(user=self.owner)
        self.assertNotIn('private-access', credential.token_encrypted)
        self.assertEqual(decrypt(credential.token_encrypted), 'private-access')
        self.assertNotIn('private-access', str(self.client.get('/api/v2/zotero/status/', {'project': self.project}).data))

    @patch('qipu_api.zotero_views.api_request')
    @patch('qipu_api.zotero_views.paged')
    def test_manual_push_creates_remote_link_and_rejects_replay(self, pages, api):
        ZoteroCredential.objects.create(user=self.owner, zotero_user_id='100', token_encrypted='encrypted',
                                        token_secret_encrypted='encrypted')
        ZoteroCollection.objects.create(project=ResearchProject.objects.get(pk=self.project),
            connected_by=self.owner, library_kind='users', library_id='100', collection_key='ABCDEFGH', name='Corpus')
        local = QipSource.objects.create(project_id=self.project, created_by=self.owner, title='Cahier local')
        pages.return_value = []
        preview = self.client.post('/api/v2/zotero/sync/preview/', {'project': self.project}, format='json')
        self.assertEqual(preview.data['rows'][0]['status'], 'local_new')
        api.return_value.json.return_value = {'successful': {'0': {'key': 'NEWITEM1', 'version': 1}}}
        choice = [{'id': preview.data['rows'][0]['id'], 'action': 'push'}]
        result = self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': choice}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(ZoteroItemLink.objects.get(source=local).item_key, 'NEWITEM1')
        self.assertEqual(api.call_args.kwargs['payload'][0]['collections'], ['ABCDEFGH'])
        self.assertEqual(self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': choice}, format='json').status_code, 400)

    @patch('qipu_api.zotero_views.paged')
    def test_owner_can_choose_a_nested_group_collection_and_reader_cannot_write(self, pages):
        from .models import ProjectMembership
        ZoteroCredential.objects.create(user=self.owner, zotero_user_id='100', token_encrypted='encrypted',
                                        token_secret_encrypted='encrypted')
        pages.side_effect = [[{'id': 77, 'data': {'name': 'Archives'}}],
                             [{'key': 'ABCDEFGH', 'data': {'name': 'Sous-collection', 'parentCollection': 'PARENT01'}}]]
        result = self.client.post('/api/v2/zotero/connect/', {'project': self.project, 'kind': 'groups',
            'library_id': '77', 'collection_key': 'ABCDEFGH'}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(ZoteroCollection.objects.get(project_id=self.project).library_kind, 'groups')
        ProjectMembership.objects.create(project_id=self.project, user=self.other, role='viewer')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v2/zotero/status/', {'project': self.project}).status_code, 200)
        self.assertEqual(self.client.post('/api/v2/zotero/sync/preview/',
            {'project': self.project}, format='json').status_code, 403)

    @patch('qipu_api.zotero_views.remote_item')
    @patch('qipu_api.zotero_views.paged')
    def test_connected_preview_detects_bidirectional_conflicts_and_no_deletion(self, pages, remote_item):
        ZoteroCredential.objects.create(user=self.owner, zotero_user_id='100', token_encrypted='encrypted',
                                        token_secret_encrypted='encrypted')
        collection = ZoteroCollection.objects.create(project=ResearchProject.objects.get(pk=self.project),
            connected_by=self.owner, library_kind='users', library_id='100', collection_key='ABCDEFGH', name='Corpus')
        source = QipSource.objects.create(project=collection.project, created_by=self.owner, title='Titre local')
        BibliographicRecord.objects.create(source=source, csl={'title': 'Titre initial', 'type': 'book'})
        ZoteroItemLink.objects.create(source=source, collection=collection, item_key='ITEM0001',
                                      item_version=2, last_synced={'title': 'Titre initial', 'type': 'book'})
        pages.return_value = [{'key': 'ITEM0001', 'version': 3, 'data': {'title': 'Titre distant',
            'itemType': 'book', 'collections': ['ABCDEFGH']}}]
        preview = self.client.post('/api/v2/zotero/sync/preview/', {'project': self.project}, format='json')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['rows'][0]['status'], 'conflict')
        self.assertEqual(source.title, 'Titre local')
        remote_item.return_value = pages.return_value[0]
        decision = [{'id': row['id'], 'action': 'update' if row['status'] == 'conflict' else 'ignore',
                     'source_id': source.id} for row in preview.data['rows']]
        result = self.client.post(f"/api/v2/zotero/preview/{preview.data['id']}/apply/",
            {'decisions': decision}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(QipSource.objects.get(pk=source.pk).title, 'Titre distant')
        pages.return_value = []
        missing = self.client.post('/api/v2/zotero/sync/preview/', {'project': self.project}, format='json')
        self.assertEqual(missing.data['rows'][0]['status'], 'remote_missing')
        self.assertTrue(QipSource.objects.filter(pk=source.pk).exists())

    @patch('qipu_api.zotero_views.remote_item')
    @patch('qipu_api.zotero_views.paged')
    def test_remote_change_after_preview_rejects_stale_update(self, pages, remote_item):
        ZoteroCredential.objects.create(user=self.owner, zotero_user_id='100', token_encrypted='encrypted',
                                        token_secret_encrypted='encrypted')
        collection = ZoteroCollection.objects.create(project_id=self.project, connected_by=self.owner,
            library_kind='users', library_id='100', collection_key='ABCDEFGH', name='Corpus')
        source = QipSource.objects.create(project_id=self.project, created_by=self.owner, title='Avant')
        ZoteroItemLink.objects.create(source=source, collection=collection, item_key='ITEM0001',
            item_version=1, last_synced={'title': 'Avant', 'type': 'book'})
        pages.return_value = [{'key': 'ITEM0001', 'version': 2, 'data': {'title': 'Après',
            'itemType': 'book', 'collections': ['ABCDEFGH']}}]
        preview = self.client.post('/api/v2/zotero/sync/preview/', {'project': self.project}, format='json').data
        remote_item.return_value = {**pages.return_value[0], 'version': 3}
        choice = [{'id': preview['rows'][0]['id'], 'action': 'update', 'source_id': source.id}]
        result = self.client.post(f"/api/v2/zotero/preview/{preview['id']}/apply/",
            {'decisions': choice}, format='json')
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(QipSource.objects.get(pk=source.id).title, 'Avant')
