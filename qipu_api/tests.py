from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import User, Media, Tag, MediaTag  # Import the MediaTag model
from .views import MediaViewSet
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework import status


class MediaViewSetTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpassword', first_name='Test', last_name='User')
        self.other_user = User.objects.create_user(
            username='otheruser', email='other@example.com', password='otherpassword', first_name='Other', last_name='User')

        self.tag1 = Tag.objects.create(name='Tag 1')
        self.tag2 = Tag.objects.create(name='Tag 2')

        dummy_file = SimpleUploadedFile('file.txt', b'file_content')
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
