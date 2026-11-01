from datetime import datetime
import uuid
from django.conf import settings
from rest_framework import viewsets, status
import requests
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.db.models import Q
from rest_framework.generics import ListAPIView
from django.contrib.auth import authenticate
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.http import HttpResponse
from .utility import set_token_cookie, generate_signed_url, CustomGoogleCloudStorage
from .permissions import IsOwner, IsOwnerOrInvolved, PermissionMixin
from urllib.parse import urlparse
from .models import User, Media, Post, Event, Contact, Attendee, Unique, RelationshipLabel, Tag, MediaTag, PostTag
from .serializers import (UserSerializer, MediaSerializer, PostSerializer,
                          EventSerializer, ContactSerializer, AttendeeSerializer,
                          UniqueSerializer, RelationshipLabelSerializer, TagSerializer,
                          PasswordResetRequestSerializer, PasswordResetSerializer)
import os
import dotenv
import pytest
from django.utils.crypto import get_random_string
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.utils import timezone
from .terms import TERMS_SECTIONS, TERMS_VERSION


class TermsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'version': TERMS_VERSION, 'sections': TERMS_SECTIONS})


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')

        if request.data.get('accept_terms') is not True or request.data.get('terms_version') != TERMS_VERSION:
            raise ValidationError({'accept_terms': 'Accept the current conditions of use to create an account.'})

        if any(not isinstance(value, str) or not value.strip() for value in
               (username, password, email, first_name, last_name)):
            raise ValidationError({'error': 'All registration fields are required.'})
        if len(username) > 30 or len(first_name) > 30 or len(last_name) > 30 or len(email) > 254:
            raise ValidationError({'error': 'One or more registration fields are too long.'})

        if User.objects.filter(username=username).exists():
            raise ValidationError({'error': 'Username already exists'})
        if User.objects.filter(email=email).exists():
            raise ValidationError({'error': 'Email already exists'})

        user = User.objects.create_user(
            username=username, email=email, password=password, first_name=first_name, last_name=last_name,
            terms_version=TERMS_VERSION, terms_accepted_at=timezone.now())

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        return Response({'token': access_token, 'user': UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')

        user = authenticate(username=username, password=password)
        if user is None:
            raise ValidationError({'error': 'Invalid Credentials'})

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        response = JsonResponse(
            {'user': UserSerializer(user).data}, status=status.HTTP_200_OK)
        set_token_cookie(response, access_token)

        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        response = HttpResponse("Logged out", status=status.HTTP_200_OK)
        response.delete_cookie('authToken')
        return response


class CheckSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated:
            return Response({'user': UserSerializer(user).data})
        else:
            raise ValidationError({'error': 'Not Authenticated'})


class UserViewSet(PermissionMixin, ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def perform_create(self, serializer):
        raise PermissionDenied('Use signup to create an account.')


class MediaViewSet(PermissionMixin, viewsets.ModelViewSet):
    queryset = Media.objects.all()
    serializer_class = MediaSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        tag_ids = self.request.query_params.get('tag', '')
        if tag_ids:
            tag_id_list = [int(tag_id)
                           for tag_id in tag_ids.split(',') if tag_id.isdigit()]
            queryset = queryset.filter(
                mediatag__tag__id__in=tag_id_list, user=self.request.user)
        return queryset


class PostViewSet(PermissionMixin, viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        tag_ids = self.request.query_params.get('tag', '')
        if tag_ids:
            tag_id_list = [int(tag_id)
                           for tag_id in tag_ids.split(',') if tag_id.isdigit()]
            queryset = queryset.filter(
                posttag__tag__id__in=tag_id_list, user=self.request.user)
        return queryset


class EventViewSet(PermissionMixin, ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactViewSet(PermissionMixin, ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrInvolved]

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)


class AttendeeViewSet(PermissionMixin, ModelViewSet):
    queryset = Attendee.objects.all()
    serializer_class = AttendeeSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrInvolved]


class UniqueViewSet(PermissionMixin, ModelViewSet):
    queryset = Unique.objects.all()
    serializer_class = UniqueSerializer

    def perform_create(self, serializer):
        raise PermissionDenied()


class RelationshipLabelViewSet(PermissionMixin, ModelViewSet):
    queryset = RelationshipLabel.objects.all()
    serializer_class = RelationshipLabelSerializer

    def get_permissions(self):
        if self.action not in ('list', 'retrieve'):
            from rest_framework.permissions import IsAdminUser
            return [IsAdminUser()]
        return [IsAuthenticated()]


class TagViewSet(PermissionMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_staff:
            return queryset
        user = self.request.user
        return queryset.filter(Q(posttag__post__user=user) | Q(mediatag__media__user=user) | Q(usertag__user=user)).distinct()

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            from rest_framework.permissions import IsAdminUser
            return [IsAdminUser()]
        return [IsAuthenticated()]


class TagSearchView(ListAPIView):
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        query = self.request.query_params.get('q', '')
        user = self.request.user
        queryset = Tag.objects.filter(
            Q(posttag__post__user=user) | Q(mediatag__media__user=user) | Q(usertag__user=user),
            name__icontains=query,
        ).distinct()[:4]
        return queryset


class MediaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, media_id):
        media_object = get_object_or_404(Media, pk=media_id, user=request.user)
        try:
            object_url = media_object.storage_file.name

            if object_url.startswith('https://') or object_url.startswith('http://'):
                parsed_url = urlparse(object_url)
                object_name = parsed_url.path.lstrip('/')
                bucket_prefix = f"{os.environ.get('GS_BUCKET_NAME')}/"
                if object_name.startswith(bucket_prefix):
                    object_name = object_name[len(bucket_prefix):]
            else:
                object_name = object_url

            object_name = object_name.strip('/')
            # Generate the signed URL for fetching the media
            signed_url = generate_signed_url(
                bucket_name=os.environ.get('GS_BUCKET_NAME'),
                object_name=object_name,
                content_type=None,  # GET request does not need content_type
                method='GET'
            )

            media_data = {
                'id': media_object.id,
                'caption': media_object.caption,
                'media_type': media_object.media_type,
                'signed_url': signed_url,
                'user': media_object.user.username
            }

            return Response(media_data)

        except Exception:
            return Response({'error': 'Unable to retrieve media'}, status=500)





class GenerateSignedURLView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        filename = request.query_params.get('filename')
        content_type = request.query_params.get('contentType')
        if not filename or not os.path.basename(filename) or not content_type:
            return Response({'error': 'Missing filename or contentType'}, status=400)

        try:
            bucket_name = os.environ.get('GS_BUCKET_NAME')
            # Never sign an arbitrary path supplied by a client: isolate every upload.
            object_name = f"uploads/{request.user.pk}/{uuid.uuid4().hex}/{os.path.basename(filename)}"
            signed_url = generate_signed_url(bucket_name, object_name, content_type, method='PUT')
            return Response({'signedUrl': signed_url})
        except Exception:
            return Response({'error': 'Unable to sign upload'}, status=500)







class AddItemView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        content = request.data.get('content')
        created_time = request.data.get('created_time', None)
        media_url = request.data.get('media_url')
        tags = request.data.get('tags', [])
        is_media = request.data.get('is_media', False)

        try:
            user = request.user
            if not created_time:
                created_time = datetime.now().isoformat()
            created_datetime = datetime.fromisoformat(created_time)

            if not is_media:
                post = Post.objects.create(user=user, content=content, created_time=created_datetime)
                for tag_id in tags:
                    tag = Tag.objects.get(id=tag_id)
                    PostTag.objects.create(post=post, tag=tag)
            else:
                if not media_url:
                    raise ValidationError({'media_url': 'Required for media.'})
                parsed = urlparse(media_url)
                bucket = os.environ.get('GS_BUCKET_NAME')
                object_name = parsed.path.lstrip('/')
                if parsed.scheme != 'https' or parsed.hostname not in ('storage.googleapis.com', 'storage.cloud.google.com') or not object_name.startswith(f'{bucket}/'):
                    raise ValidationError({'media_url': 'Invalid upload location.'})
                object_name = object_name[len(bucket) + 1:]
                if not object_name.startswith(f'uploads/{user.pk}/'):
                    raise ValidationError({'media_url': 'Invalid upload location.'})
                media_type = 'video' if media_url.lower().endswith(('.mp4', '.avi', '.mov')) else 'image'
                storage = CustomGoogleCloudStorage()
                custom_url = storage.url(object_name)
                media = Media.objects.create(
                    user=user,
                    caption=content if content else '',
                    media_type=media_type,
                    permalink=custom_url,  # Use the custom URL
                    shortcode=os.path.basename(object_name)[:50],
                    storage_file=object_name,
                    is_published=True,
                    category=1
                )
                for tag_id in tags:
                    tag = Tag.objects.get(id=tag_id)
                    MediaTag.objects.create(media=media, tag=tag)

            return Response({'message': 'Item added successfully'})
        except ValidationError:
            raise
        except Exception:
            return Response({'error': 'Unable to add item'}, status=500)





class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        user = User.objects.filter(email=email).first()

        if user:
            reset_token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_url = request.build_absolute_uri(
                f'/password-reset-confirm/{uid}/{reset_token}'
            )
            send_mail(
                'Password Reset Request',
                f'Please click the link to reset your password: {reset_url}',
                'noreply@yourdomain.com',
                [email],
                fail_silently=False,
            )
        return Response({'message': 'Password reset link sent'}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token, *args, **kwargs):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['password']

        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user and default_token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            return Response({'message': 'Password has been reset'}, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
