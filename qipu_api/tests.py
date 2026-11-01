from unittest.mock import patch
from django.test import TestCase
from .models import User, Media, Tag, MediaTag, Post, Contact
from .views import MediaViewSet, PostViewSet, MediaDetailView, GenerateSignedURLView, UserViewSet, ContactViewSet, AddItemView, TagViewSet, TagSearchView
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework import status


class MediaViewSetTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        storage_url = patch('qipu_api.utility.CustomGoogleCloudStorage.url', return_value='https://storage.cloud.google.com/test-bucket/media_files/file.txt')
        storage_url.start()
        self.addCleanup(storage_url.stop)

        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpassword', first_name='Test', last_name='User')
        self.other_user = User.objects.create_user(
            username='otheruser', email='other@example.com', password='otherpassword', first_name='Other', last_name='User')

        self.tag1 = Tag.objects.create(name='Tag 1')
        self.tag2 = Tag.objects.create(name='Tag 2')

        dummy_file = 'media_files/file.txt'
        category_example = 1

        self.media1 = Media.objects.create(
            user=self.user,
            caption='Media 1 Caption',
            media_type='image',
            permalink='http://example.com/media1',
            shortcode='shortcode1',
            storage_file=dummy_file,
            is_published=True,
            category=category_example
        )

        # Instead of self.media1.tags.add(self.tag1), use the MediaTag model
        MediaTag.objects.create(media=self.media1, tag=self.tag1)

        self.media2 = Media.objects.create(
            user=self.user,
            caption='Media 2 Caption',
            media_type='video',
            permalink='http://example.com/media2',
            shortcode='shortcode2',
            storage_file=dummy_file,
            is_published=True,
            category=category_example
        )

        # Use the MediaTag model
        MediaTag.objects.create(media=self.media2, tag=self.tag2)

        self.media3 = Media.objects.create(
            user=self.other_user,
            caption='Media 3 Caption',
            media_type='image',
            permalink='http://example.com/media3',
            shortcode='shortcode3',
            storage_file=dummy_file,
            is_published=True,
            category=category_example
        )

        # Use the MediaTag model
        MediaTag.objects.create(media=self.media3, tag=self.tag1)

    def test_get_queryset_no_tag(self):
        request = self.factory.get('/media/')
        force_authenticate(request, user=self.user)
        view = MediaViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Expecting 2 media items for self.user
        self.assertEqual(len(response.data), 2)

    def test_get_queryset_with_valid_tag(self):
        request = self.factory.get('/media/', {'tag': str(self.tag1.id)})
        force_authenticate(request, user=self.user)
        view = MediaViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Expecting 1 media item tagged with 'Tag 1' for self.user
        self.assertEqual(len(response.data), 1)

    def test_get_queryset_with_invalid_tag(self):
        # Assuming tag ID 999 does not exist
        request = self.factory.get('/media/', {'tag': '999'})
        force_authenticate(request, user=self.user)
        view = MediaViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Expecting no media items for an invalid tag
        self.assertEqual(len(response.data), 0)

    def test_permission(self):
        request = self.factory.get('/media/')
        force_authenticate(request, user=self.other_user)
        view = MediaViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Expecting 1 media item for self.other_user
        self.assertEqual(len(response.data), 1)

    def test_other_user_media_is_not_retrievable_or_editable(self):
        view = MediaViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})
        for method in (self.factory.get, self.factory.delete):
            request = method(f'/media/{self.media3.pk}/')
            force_authenticate(request, user=self.user)
            self.assertEqual(view(request, pk=self.media3.pk).status_code, 404)

    @patch('qipu_api.views.generate_signed_url', return_value='https://signed.example/file')
    def test_media_detail_only_signs_owned_file(self, sign):
        view = MediaDetailView.as_view()
        request = self.factory.get(f'/media-detail/{self.media3.pk}/')
        force_authenticate(request, user=self.user)
        self.assertEqual(view(request, media_id=self.media3.pk).status_code, 404)
        sign.assert_not_called()
        request = self.factory.get(f'/media-detail/{self.media1.pk}/')
        force_authenticate(request, user=self.user)
        self.assertEqual(view(request, media_id=self.media1.pk).status_code, 200)
        sign.assert_called_once()

    @patch('qipu_api.views.generate_signed_url', return_value='https://signed.example/upload')
    def test_upload_key_is_server_owned(self, sign):
        view = GenerateSignedURLView.as_view()
        request = self.factory.get('/generate-signed-url/', {'filename': '../foreign.txt', 'contentType': 'text/plain'})
        force_authenticate(request, user=self.user)
        self.assertEqual(view(request).status_code, 200)
        key = sign.call_args.args[1]
        self.assertTrue(key.startswith(f'uploads/{self.user.pk}/'))
        self.assertTrue(key.endswith('/foreign.txt'))
        self.assertNotIn('..', key)

    def test_posts_are_scoped_and_creator_cannot_be_spoofed(self):
        foreign = Post.objects.create(user=self.other_user, content='foreign')
        view = PostViewSet.as_view({'get': 'list', 'post': 'create'})
        request = self.factory.get('/posts/')
        force_authenticate(request, user=self.user)
        self.assertEqual(view(request).data, [])
        request = self.factory.post('/posts/', {'content': 'mine', 'user': self.other_user.pk})
        force_authenticate(request, user=self.user)
        self.assertEqual(view(request).status_code, 201)
        self.assertEqual(Post.objects.exclude(pk=foreign.pk).get().user, self.user)

    def test_users_are_scoped_to_self(self):
        request = self.factory.get('/users/')
        force_authenticate(request, user=self.user)
        response = UserViewSet.as_view({'get': 'list'})(request)
        self.assertEqual([item['id'] for item in response.data], [self.user.pk])

    def test_contacts_are_scoped_to_participants(self):
        contact = Contact.objects.create(requester=self.other_user, recipient=self.user)
        request = self.factory.get('/contacts/')
        force_authenticate(request, user=self.user)
        self.assertEqual(ContactViewSet.as_view({'get': 'list'})(request).data[0]['id'], contact.pk)
        stranger = User.objects.create_user(username='stranger', email='stranger@example.com', password='pass')
        request = self.factory.get(f'/contacts/{contact.pk}/')
        force_authenticate(request, user=stranger)
        self.assertEqual(ContactViewSet.as_view({'get': 'retrieve'})(request, pk=contact.pk).status_code, 404)

    def test_login_cookie_allows_session_check_without_token_in_body(self):
        response = self.client.post('/login/', {'username': 'testuser', 'password': 'testpassword'}, content_type='application/json', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('token', response.json())
        self.assertTrue(response.cookies['authToken']['httponly'])
        response = self.client.get('/check_session/', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['id'], self.user.pk)

    def test_add_item_rejects_foreign_upload_path(self):
        request = self.factory.post('/items/add/', {
            'content': 'foreign file', 'is_media': True,
            'media_url': f'https://storage.googleapis.com/test-bucket/uploads/{self.other_user.pk}/file.png',
        }, format='json')
        force_authenticate(request, user=self.user)
        self.assertEqual(AddItemView.as_view()(request).status_code, 400)
        self.assertFalse(Media.objects.filter(caption='foreign file').exists())

    def test_tags_from_other_users_are_not_listed_or_searched(self):
        request = self.factory.get('/tags/')
        force_authenticate(request, user=self.other_user)
        self.assertEqual([tag['id'] for tag in TagViewSet.as_view({'get': 'list'})(request).data], [self.tag1.pk])
        request = self.factory.get('/tag_search/', {'q': 'Tag'})
        force_authenticate(request, user=self.other_user)
        self.assertEqual([tag['id'] for tag in TagSearchView.as_view()(request).data], [self.tag1.pk])
