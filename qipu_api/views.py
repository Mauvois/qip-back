from datetime import datetime
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
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')

        if User.objects.filter(username=username).exists():
            raise ValidationError({'error': 'Username already exists'})

        user = User.objects.create_user(
            username=username, email=email, password=password, first_name=first_name, last_name=last_name)

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


class MediaViewSet(PermissionMixin, viewsets.ModelViewSet):
    queryset = Media.objects.all()
    serializer_class = MediaSerializer

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


class ContactViewSet(PermissionMixin, ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrInvolved]


class AttendeeViewSet(PermissionMixin, ModelViewSet):
    queryset = Attendee.objects.all()
    serializer_class = AttendeeSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrInvolved]


class UniqueViewSet(PermissionMixin, ModelViewSet):
    queryset = Unique.objects.all()
    serializer_class = UniqueSerializer


class RelationshipLabelViewSet(PermissionMixin, ModelViewSet):
    queryset = RelationshipLabel.objects.all()
    serializer_class = RelationshipLabelSerializer


class TagViewSet(PermissionMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]


class TagSearchView(ListAPIView):
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        query = self.request.query_params.get('q', '')
        queryset = Tag.objects.filter(name__icontains=query)[:4]
        return queryset


from urllib.parse import urlparse

class MediaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, media_id):
        try:
            media_object = Media.objects.get(pk=media_id)
            object_url = media_object.storage_file.name

            # Debugging output
            print(f"Object URL from database: {object_url}")

            if object_url.startswith('https://') or object_url.startswith('http://'):
                parsed_url = urlparse(object_url)
                object_name = parsed_url.path.lstrip('/')
            else:
                object_name = object_url

            object_name = object_name.strip('/')
            if object_name.startswith('qip_media/'):
                object_name = object_name.replace('qip_media/', '', 1)

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

        except Media.DoesNotExist:
            return Response({'error': 'Media object not found'}, status=404)
        except Exception as e:
            print(f"Error fetching media details: {str(e)}")  # Print the error for debugging
            return Response({'error': str(e)}, status=500)





class GenerateSignedURLView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({'error': 'Unauthorized'}, status=403)

        filename = request.query_params.get('filename')
        content_type = request.query_params.get('contentType')
        if not filename or not content_type:
            return Response({'error': 'Missing filename or contentType'}, status=400)

        try:
            bucket_name = os.environ.get('GS_BUCKET_NAME')
            signed_url = generate_signed_url(bucket_name, filename, content_type, method='PUT')
            print("Generated Signed URL:", signed_url)
            return Response({'signedUrl': signed_url})
        except Exception as e:
            return Response({'error': str(e)}, status=500)







class AddItemView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({'error': 'Unauthorized'}, status=403)

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
                media_type = 'video' if media_url.lower().endswith(('.mp4', '.avi', '.mov')) else 'image'
                storage = CustomGoogleCloudStorage()
                # Ensure the URL is stored correctly
                custom_url = storage.url(media_url.split('/')[-1])
                media = Media.objects.create(
                    user=user,
                    caption=content if content else '',
                    media_type=media_type,
                    permalink=custom_url,  # Use the custom URL
                    shortcode=media_url.split('/')[-1],
                    storage_file=custom_url,  # Ensure this is correct
                    is_published=True,
                    category=1
                )
                for tag_id in tags:
                    tag = Tag.objects.get(id=tag_id)
                    MediaTag.objects.create(media=media, tag=tag)

            return Response({'message': 'Item added successfully'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)





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
                reverse('password_reset_confirm', kwargs={
                        'uidb64': uid, 'token': reset_token})
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
