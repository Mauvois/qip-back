# utility.py

import os
import uuid
from django.http import HttpResponse
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from google.cloud import storage
from datetime import timedelta
from storages.backends.gcloud import GoogleCloudStorage
from urllib.parse import urlparse
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


# code proposé par ChatGPT3.5 tel quel


def media_file_upload(instance, filename):
    # Generate a unique filename using UUID
    filename_base, filename_ext = os.path.splitext(filename)
    unique_filename = f"{uuid.uuid4().hex}{filename_ext}"
    # Determine the directory structure
    return f"media_files/{instance.user.username}/{unique_filename}"


def validate_bio_length(value):
    if len(value) < 5:
        raise ValidationError('Bio must be at least 10 characters long.')


def set_token_cookie(response: HttpResponse, token: str) -> None:
    """Sets the JWT token as a httpOnly cookie."""
    response.set_cookie(
        key='authToken',
        value=token,
        httponly=True,
        samesite='Lax' if settings.QIP_LOCAL_STORAGE else 'None',
        secure=not settings.QIP_LOCAL_STORAGE,
        # Add other properties as needed
    )


class TokenFromCookieMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.COOKIES.get('authToken', None)
        invalid_token = False
        if token:
            try:
                AccessToken(token)
            except TokenError:
                invalid_token = True
            else:
                # Authentication endpoints must remain usable to switch accounts.
                if request.path not in ('/login/', '/signup/', '/password-reset/') and 'HTTP_AUTHORIZATION' not in request.META:
                    request.META['HTTP_AUTHORIZATION'] = f"Bearer {token}"
        response = self.get_response(request)
        # Do not overwrite the fresh authToken set by a successful login.
        if invalid_token and 'authToken' not in response.cookies:
            response.delete_cookie('authToken')
        return response


class RedirectAuthenticatedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            if request.path in [reverse('login'), reverse('signup')]:
                return redirect('Dashboard')
        return None




def generate_signed_url(bucket_name, object_name, content_type=None, expiration=timedelta(minutes=60), method='GET'):
    """Generates a signed URL for a GCS object."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    return blob.generate_signed_url(
        expiration=expiration, version="v4", method=method, content_type=content_type
    )



class CustomGoogleCloudStorage(GoogleCloudStorage):
    def url(self, name):
        url = super().url(name)
        parsed_url = urlparse(url)
        new_url = f"https://storage.cloud.google.com{parsed_url.path}"
        return new_url
