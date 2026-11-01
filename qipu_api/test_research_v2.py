from tempfile import TemporaryDirectory

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from .models import User


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   ALLOWED_HOSTS=['qip.taan.ovh'])
class PasswordResetLinkTests(TestCase):
    def test_emailed_link_opens_frontend_on_the_public_domain(self):
        User.objects.create_user(username='reader', email='reader@example.test', password='pass')
        response = self.client.post('/password-reset/', {'email': 'reader@example.test'},
                                    HTTP_HOST='qip.taan.ovh', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://qip.taan.ovh/password-reset-confirm/', mail.outbox[0].body)
        self.assertFalse(mail.outbox[0].body.strip().endswith('/'))


@override_settings(SECURE_SSL_REDIRECT=False)
class ResearchV2Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='researcher', email='r@example.test', password='pass')
        self.other = User.objects.create_user(username='other_v2', email='o@example.test', password='pass')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.project = self.client.post('/api/v2/projects/', {'name': 'Corpus'}, format='json').data['id']
        self.info_type = self.kind('information', 'Naissance')
        self.relation_type = self.kind('relation', 'Concerne')

    def kind(self, kind, name):
        response = self.client.post('/api/v2/types/', {'project': self.project, 'kind': kind, 'name': name}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def information(self, level, **extra):
        return {'project': self.project, 'level': level, 'label': 'Naissance', 'type': self.info_type, **extra}

    def test_two_time_axes_source_factoid_qualified_and_birthplace(self):
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Registre',
            'datings': [{'date_kind': 'publication', 'is_primary': True,
                         'begin_of_begin': '1900-01-01', 'end_of_end': '1900-12-31'}]}, format='json')
        self.assertEqual(source.status_code, 201, source.data)
        person = self.client.post('/api/v2/entities/', {'project': self.project, 'kind': 'person', 'label': 'Ada'}, format='json')
        place = self.client.post('/api/v2/entities/', {'project': self.project, 'kind': 'geographical_place',
            'label': 'Paris', 'latitude': '48.856600', 'longitude': '2.352200'}, format='json')
        self.assertEqual(person.status_code, 201, person.data)
        self.assertEqual(place.status_code, 201, place.data)
        factoid_data = self.information('factoid', begin_of_begin='1880-01-01', end_of_end='1880-12-31',
            citations=[{'source': source.data['id'], 'locator': 'p. 4'}])
        factoid = self.client.post('/api/v2/informations/', factoid_data, format='json')
        self.assertEqual(factoid.status_code, 201, factoid.data)
        qualified = self.client.post('/api/v2/informations/', self.information('qualified',
            begin_of_begin='1881-01-01', end_of_end='1881-12-31',
            evidence=[{'factoid_information': factoid.data['id'], 'relation': 'contradicts'}],
            entities=[{'entity': person.data['id'], 'type': self.relation_type}]), format='json')
        self.assertEqual(qualified.status_code, 201, qualified.data)
        birth = self.client.post('/api/v2/person-births/', {'person': person.data['id'],
            'information': qualified.data['id'], 'place': place.data['id']}, format='json')
        self.assertEqual(birth.status_code, 201, birth.data)
        self.assertEqual(self.client.get(f"/api/v2/entities/{person.data['id']}/").data['birth']['place'], place.data['id'])
        birth_relations = self.client.get(f"/api/v2/informations/{qualified.data['id']}/").data['entities']
        self.assertIn(place.data['id'], [row['entity'] for row in birth_relations])
        self.assertIn(person.data['id'], [row['entity'] for row in birth_relations])
        markers = self.client.get('/api/v2/timeline/', {'project': self.project}).data
        self.assertEqual(len(markers), 6)
        self.assertEqual({row['time_axis'] for row in markers}, {'historical', 'recorded'})
        self.assertEqual(next(row for row in markers if row['resource_kind'] == 'source' and row['time_axis'] == 'historical')['date_kind'], 'publication')

    def test_factoid_requires_source_and_all_links_remain_in_project(self):
        factoid = self.client.post('/api/v2/informations/', self.information('factoid'), format='json')
        self.assertEqual(factoid.status_code, 400)
        other_project = self.client.post('/api/v2/projects/', {'name': 'Autre'}, format='json').data['id']
        foreign = self.client.post('/api/v2/sources/', {'project': other_project, 'title': 'Other'}, format='json').data['id']
        response = self.client.post('/api/v2/informations/', self.information('factoid',
            citations=[{'source': foreign}]), format='json')
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v2/sources/').data, [])
        self.assertEqual(self.client.get('/api/v2/timeline/', {'project': self.project}).status_code, 403)

    def test_unknown_historical_date_does_not_invent_a_marker(self):
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Undated'}, format='json')
        self.assertEqual(source.status_code, 201, source.data)
        recorded = self.client.get('/api/v2/timeline/', {'project': self.project, 'axes': 'recorded'}).data
        historical = self.client.get('/api/v2/timeline/', {'project': self.project, 'axes': 'historical'}).data
        self.assertEqual(len(recorded), 1)
        self.assertEqual(historical, [])

    def test_coordinates_and_factoid_citation_cannot_be_invalidated(self):
        bad = self.client.post('/api/v2/entities/', {'project': self.project, 'kind': 'geographical_place',
            'label': 'Outside', 'latitude': 91, 'longitude': 1}, format='json')
        self.assertEqual(bad.status_code, 400)
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Record'}, format='json')
        factoid = self.client.post('/api/v2/informations/', self.information('factoid',
            citations=[{'source': source.data['id']}]), format='json')
        self.assertEqual(factoid.status_code, 201, factoid.data)
        self.assertEqual(self.client.patch(f"/api/v2/informations/{factoid.data['id']}/",
            {'citations': []}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(f"/api/v2/sources/{source.data['id']}/").status_code, 400)

    def test_local_file_access_is_project_scoped(self):
        with TemporaryDirectory() as location, override_settings(QIP_LOCAL_STORAGE=True, MEDIA_ROOT=location):
            upload = self.client.post('/api/v2/sources/upload-file/', {'project': self.project,
                'file': SimpleUploadedFile('source.txt', b'historical text', content_type='text/plain')}, format='multipart')
            self.assertEqual(upload.status_code, 201, upload.data)
            source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Source',
                'content_type': 'text/plain', 'storage_key': upload.data['storage_key']}, format='json')
            self.assertEqual(source.status_code, 201, source.data)
            response = self.client.get(f"/api/v2/sources/{source.data['id']}/download/")
            self.assertEqual(b''.join(response.streaming_content), b'historical text')
            self.client.force_authenticate(self.other)
            self.assertEqual(self.client.get(f"/api/v2/sources/{source.data['id']}/download/").status_code, 404)

    def test_historical_hours_use_project_timezone_without_changing_date_only_bounds(self):
        self.assertEqual(self.client.patch(f'/api/v2/projects/{self.project}/',
            {'timezone': 'Europe/Paris'}, format='json').status_code, 200)
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Gazette',
            'datings': [{'date_kind': 'publication', 'begin_of_begin': '2024-06-01',
                         'begin_of_begin_time': '14:30', 'end_of_end': '2024-06-01',
                         'end_of_end_time': '14:30'}]}, format='json')
        self.assertEqual(source.status_code, 201, source.data)
        info = self.client.post('/api/v2/informations/', self.information('qualified',
            begin_of_begin='2024-06-01', end_of_end='2024-06-01'), format='json')
        self.assertEqual(info.status_code, 201, info.data)
        historical = self.client.get('/api/v2/timeline/', {'project': self.project, 'axes': 'historical'}).data
        dated = next(row for row in historical if row['resource_kind'] == 'source')
        self.assertEqual(dated['historical_instants']['begin_of_begin'], '2024-06-01T14:30:00+02:00')
        self.assertEqual(next(row for row in historical if row['resource_kind'] == 'qualified')
                         ['historical_instants']['begin_of_begin'], None)
        self.assertEqual(self.client.post('/api/v2/informations/', self.information('qualified',
            begin_of_begin_time='12:00'), format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v2/informations/', self.information('qualified',
            begin_of_begin='2024-03-31', begin_of_begin_time='02:30'), format='json').status_code, 400)

    def test_search_fields_categories_and_project_membership(self):
        source = self.client.post('/api/v2/sources/', {'project': self.project, 'title': 'Gazette',
            'reference': 'Archive B42'}, format='json')
        self.client.post('/api/v2/informations/', self.information('factoid', label='Annonce',
            citations=[{'source': source.data['id'], 'quotation': 'La ville est prise'}]), format='json')
        result = self.client.get('/api/v2/search/', {'project': self.project, 'q': 'B42',
            'field': 'reference'}).data['results']
        self.assertEqual([row['resource_kind'] for row in result], ['source'])
        result = self.client.get('/api/v2/search/', {'project': self.project, 'q': 'ville',
            'field': 'citation', 'kind': 'factoid'}).data['results']
        self.assertEqual([row['label'] for row in result], ['Annonce'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v2/search/', {'project': self.project, 'q': 'Gazette'}).status_code, 403)

    def test_search_terms_are_temporary_and_results_are_paginated_without_dropping_matches(self):
        for title in ['Gazette Paris', 'Chronique Paris', 'Gazette Londres']:
            self.client.post('/api/v2/sources/', {'project': self.project, 'title': title}, format='json')
        params = {'project': self.project, 'q': 'Gazette Paris', 'kind': 'source', 'field': 'label', 'limit': 1}
        first = self.client.get('/api/v2/search/', params).data
        self.assertEqual(first['terms'], ['Gazette', 'Paris'])
        self.assertEqual(first['total'], 3)
        self.assertEqual(first['results'][0]['matched_terms'], ['Gazette', 'Paris'])
        self.assertEqual(first['next_offset'], 1)
        second = self.client.get('/api/v2/search/', {**params, 'offset': first['next_offset']}).data
        self.assertEqual(second['results'][0]['matched_terms'], ['Paris'])
        phrase = self.client.get('/api/v2/search/', {**params, 'q': '"Gazette Paris"'}).data
        self.assertEqual(phrase['total'], 1)
        self.assertEqual(phrase['terms'], ['Gazette Paris'])
        self.assertEqual(self.client.get('/api/v2/search/', {**params, 'q': '"inachevé'}).status_code, 400)

    def test_search_pagination_reaches_results_beyond_first_fifty(self):
        from .models import QipSource, ResearchProject
        project = ResearchProject.objects.get(pk=self.project)
        QipSource.objects.bulk_create([QipSource(project=project, created_by=self.user,
            title=f'Archive {number}') for number in range(55)])
        first = self.client.get('/api/v2/search/', {'project': self.project, 'q': 'Archive', 'limit': 50}).data
        self.assertEqual(first['total'], 55)
        self.assertEqual(first['next_offset'], 50)
        second = self.client.get('/api/v2/search/', {'project': self.project, 'q': 'Archive',
            'limit': 50, 'offset': 50}).data
        self.assertEqual(len(second['results']), 5)
        self.assertIsNone(second['next_offset'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ExpiredCookieAuthenticationTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='existing_v2', email='existing@example.test', password='test-pass')
        self.client = Client()
        self.client.cookies['authToken'] = 'expired-or-invalid-token'

    def test_login_replaces_stale_cookie_and_restores_session(self):
        response = self.client.post('/login/', {'username': 'existing_v2', 'password': 'test-pass'},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('authToken', response.cookies)
        self.assertTrue(response.cookies['authToken'].value)
        self.assertEqual(self.client.get('/check_session/').status_code, 200)

    def test_signup_works_with_stale_cookie(self):
        from .terms import TERMS_VERSION
        response = self.client.post('/signup/', {'username': 'new_v2', 'email': 'new@example.test',
            'password': 'test-pass', 'first_name': 'New', 'last_name': 'User',
            'accept_terms': True, 'terms_version': TERMS_VERSION}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        new_user = User.objects.get(username='new_v2')
        self.assertEqual(new_user.terms_version, TERMS_VERSION)
        self.assertIsNotNone(new_user.terms_accepted_at)

    def test_signup_requires_the_published_terms_and_explicit_acceptance(self):
        from .terms import TERMS_VERSION
        terms = self.client.get('/api/terms/')
        self.assertEqual(terms.status_code, 200)
        self.assertEqual(terms.json()['version'], TERMS_VERSION)
        self.assertTrue(terms.json()['sections'])
        data = {'username': 'without_terms', 'email': 'terms@example.test', 'password': 'test-pass',
                'first_name': 'New', 'last_name': 'User'}
        for consent in ({}, {'accept_terms': False, 'terms_version': TERMS_VERSION},
                        {'accept_terms': 'true', 'terms_version': TERMS_VERSION},
                        {'accept_terms': True, 'terms_version': 'old-version'}):
            response = self.client.post('/signup/', {**data, **consent}, content_type='application/json')
            self.assertEqual(response.status_code, 400)
            self.assertIn('accept_terms', response.json())
        self.assertFalse(User.objects.filter(username='without_terms').exists())

    def test_stale_cookie_is_cleared_when_checking_session(self):
        response = self.client.get('/check_session/')
        self.assertEqual(response.status_code, 403)
        self.assertIn('authToken', response.cookies)
        self.assertEqual(response.cookies['authToken'].value, '')

    def test_signup_rejects_oversized_username_without_server_error(self):
        from .terms import TERMS_VERSION
        response = self.client.post('/signup/', {'username': 'x' * 31, 'email': 'valid@example.test',
            'password': 'test-pass', 'first_name': 'New', 'last_name': 'User',
            'accept_terms': True, 'terms_version': TERMS_VERSION}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
