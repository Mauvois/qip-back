from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from .models import (User, ResearchProject, ResearchType, HistoricalEntity,
                     ResearchMedia, ResearchItem, ItemEntityParticipation, EpistemicStatus)


@override_settings(SECURE_SSL_REDIRECT=False)
class ResearchApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='test-pass')
        self.other = User.objects.create_user(username='other', email='other@example.com', password='test-pass')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.project = self.client.post('/api/v1/projects/', {'name': 'Enquête'}, format='json').data['id']
        self.kind = self.client.post('/api/v1/types/', {'project': self.project, 'name': 'Situation'}, format='json').data['id']
        self.role = self.client.post('/api/v1/types/', {'project': self.project, 'name': 'Concerne'}, format='json').data['id']
        self.entity = self.client.post('/api/v1/entities/', {
            'project': self.project, 'label': 'Personne', 'type': self.kind,
        }, format='json').data['id']
        self.factoid = EpistemicStatus.objects.get(code='factoid').pk

    def item_data(self, **kwargs):
        data = {'project': self.project, 'type': self.kind, 'epistemic_status': self.factoid,
                'label': 'Mention', 'entity_participations': [{'entity': self.entity, 'type': self.role}]}
        data.update(kwargs)
        return data

    def test_item_without_media_and_partial_time_and_nested_participation(self):
        response = self.client.post('/api/v1/items/', self.item_data(
            begin_of_begin='2001-01-01', end_of_begin='2001-01-31', date_text='janvier 2001'), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['media_references'], [])
        self.assertIsNone(response.data['begin_of_end'])
        self.assertEqual(ItemEntityParticipation.objects.get(item_id=response.data['id']).entity_id, self.entity)
        self.assertEqual(len(self.client.get(f'/api/v1/items/?entity_id={self.entity}').data), 1)
        self.assertEqual(len(self.client.get('/api/v1/items/?from=2001-01-15&to=2001-02-01').data), 1)

        second = self.client.post('/api/v1/items/', self.item_data(
            label='Qualification', epistemic_status=EpistemicStatus.objects.get(code='qualified').pk,
            exact_begin='2002-06-01', exact_end='2002-06-01',
            item_participations=[{'participant': response.data['id'], 'type': self.role}],
        ), format='json')
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data['begin_of_begin'], '2002-06-01')
        self.assertEqual(second.data['end_of_end'], '2002-06-01')

    def test_malformed_dates_and_cross_project_references_rejected(self):
        bad = self.client.post('/api/v1/items/', self.item_data(
            begin_of_begin='2002-01-01', end_of_begin='2001-01-01'), format='json')
        self.assertEqual(bad.status_code, 400)
        other_project = ResearchProject.objects.create(name='Other', owner=self.other)
        foreign = HistoricalEntity.objects.create(project=other_project, created_by=self.other, label='Private')
        response = self.client.post('/api/v1/items/', self.item_data(
            entity_participations=[{'entity': foreign.pk, 'type': self.role}]), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ResearchItem.objects.exists())

    def test_viewer_cannot_write_and_nonmember_cannot_read(self):
        created = self.client.post('/api/v1/memberships/', {
            'project': self.project, 'username': 'other', 'role': 'viewer'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/projects/').data[0]['id'], self.project)
        self.assertEqual(self.client.post('/api/v1/items/', self.item_data(), format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/entities/', {
            'project': self.project, 'label': 'No'}, format='json').status_code, 403)
        self.client.force_authenticate(self.owner)
        self.client.delete(f"/api/v1/memberships/{created.data['id']}/")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/entities/').data, [])
        self.assertEqual(self.client.get(f'/api/v1/projects/{self.project}/').status_code, 404)

    def test_editor_can_update_but_not_manage_members_and_owner_is_immutable(self):
        response = self.client.post('/api/v1/memberships/', {
            'project': self.project, 'username': 'other', 'role': 'editor'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.client.force_authenticate(self.other)
        entity = self.client.post('/api/v1/entities/', {'project': self.project, 'label': 'Auteur'}, format='json')
        self.assertEqual(entity.status_code, 201, entity.data)
        self.assertEqual(entity.data['created_by'], self.other.pk)
        self.assertEqual(self.client.post('/api/v1/memberships/', {
            'project': self.project, 'username': 'owner', 'role': 'viewer'}, format='json').status_code, 403)
        self.client.force_authenticate(self.owner)
        owner_membership = self.client.get('/api/v1/memberships/', {'project': self.project}).data
        owner_id = next(row['id'] for row in owner_membership if row['role'] == 'owner')
        self.assertEqual(self.client.delete(f'/api/v1/memberships/{owner_id}/').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/memberships/{owner_id}/', {'username': 'other'}, format='json').status_code, 400)

    def test_project_scoped_item_update_cannot_import_foreign_relation(self):
        first = self.client.post('/api/v1/items/', self.item_data(), format='json')
        self.assertEqual(first.status_code, 201)
        foreign_project = ResearchProject.objects.create(name='Autre', owner=self.other)
        foreign_type = ResearchType.objects.create(project=foreign_project, created_by=self.other, name='Rôle privé')
        response = self.client.patch(f"/api/v1/items/{first.data['id']}/", {
            'entity_participations': [{'entity': self.entity, 'type': foreign_type.pk}]}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.client.get(f"/api/v1/items/{first.data['id']}/").data['entity_participations']), 1)

    def test_type_hierarchy_is_project_scoped_and_acyclic(self):
        child = self.client.post('/api/v1/types/', {
            'project': self.project, 'name': 'Sous-type', 'parent': self.kind}, format='json')
        self.assertEqual(child.status_code, 201, child.data)
        self.assertEqual(self.client.patch(f'/api/v1/types/{self.kind}/', {
            'parent': child.data['id']}, format='json').status_code, 400)
        foreign_project = ResearchProject.objects.create(name='Second', owner=self.other)
        foreign = ResearchType.objects.create(project=foreign_project, created_by=self.other, name='Externe')
        self.assertEqual(self.client.patch(f'/api/v1/types/{self.kind}/', {
            'parent': foreign.pk}, format='json').status_code, 400)

    @override_settings(QIP_LOCAL_STORAGE=False)
    def test_media_can_be_whole_or_part_and_signed_file_is_scoped(self):
        parent = self.client.post('/api/v1/media/', {'project': self.project, 'title': 'Rapport'}, format='json')
        self.assertEqual(parent.status_code, 201, parent.data)
        child = self.client.post('/api/v1/media/', {
            'project': self.project, 'title': 'Page', 'parent': parent.data['id'], 'locator': 'p. 5',
        }, format='json')
        self.assertEqual(child.status_code, 201, child.data)
        with patch('qipu_api.research_views.generate_signed_url', return_value='https://example.test/signed'):
            upload = self.client.post('/api/v1/media/upload-url/', {
                'project': self.project, 'filename': 'rapport.pdf', 'content_type': 'application/pdf',
            }, format='json')
            self.assertEqual(upload.status_code, 200, upload.data)
            self.assertTrue(upload.data['storage_key'].startswith(f'research/{self.owner.pk}/'))
            media = self.client.post('/api/v1/media/', {
                'project': self.project, 'title': 'Fichier', 'storage_key': upload.data['storage_key'],
            }, format='json')
            self.assertEqual(media.status_code, 201, media.data)
            self.assertNotIn('storage_key', media.data)
            self.assertEqual(self.client.get(f"/api/v1/media/{media.data['id']}/file/").status_code, 200)
            part = self.client.post('/api/v1/media/', {
                'project': self.project, 'title': 'Passage', 'parent': media.data['id'], 'locator': 'p. 4',
            }, format='json')
            self.assertEqual(part.status_code, 201, part.data)
            self.assertTrue(part.data['has_file'])
            self.assertEqual(self.client.get(f"/api/v1/media/{part.data['id']}/file/").status_code, 200)
            self.client.force_authenticate(self.other)
            self.assertEqual(self.client.get(f"/api/v1/media/{media.data['id']}/file/").status_code, 404)

    def test_local_upload_and_protected_download(self):
        with TemporaryDirectory() as location, override_settings(QIP_LOCAL_STORAGE=True, MEDIA_ROOT=location):
            uploaded = self.client.post('/api/v1/media/upload-file/', {
                'project': self.project,
                'file': SimpleUploadedFile('test.txt', b'historical text', content_type='text/plain'),
            }, format='multipart')
            self.assertEqual(uploaded.status_code, 201, uploaded.data)
            media = self.client.post('/api/v1/media/', {
                'project': self.project, 'title': 'Text', 'content_type': 'text/plain',
                'storage_key': uploaded.data['storage_key'],
            }, format='json')
            self.assertEqual(media.status_code, 201, media.data)
            file_url = f"/api/v1/media/{media.data['id']}/file/"
            self.assertEqual(self.client.get(file_url).data['signed_url'],
                             f"/api/v1/media/{media.data['id']}/download/")
            download = self.client.get(f"/api/v1/media/{media.data['id']}/download/")
            self.assertEqual(b''.join(download.streaming_content), b'historical text')
            self.client.force_authenticate(self.other)
            self.assertEqual(self.client.get(f"/api/v1/media/{media.data['id']}/download/").status_code, 404)
