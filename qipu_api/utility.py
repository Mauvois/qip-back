# utility.py

import os
import uuid
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from google.cloud import storage
from datetime import timedelta
from storages.backends.gcloud import GoogleCloudStorage
from urllib.parse import urlparse


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
        samesite='None',  # Setting the SameSite attribute to 'None'
        secure=True,      # Ensuring the cookie is sent over HTTPS
        # Add other properties as needed
    )


class TokenFromCookieMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.COOKIES.get('authToken', None)
        if token:
            print("Token extracted:", token)
            request.META['HTTP_AUTHORIZATION'] = f"Bearer {token}"
            print("Authorization header set:",
                  request.META['HTTP_AUTHORIZATION'])
        else:
            print("No token found in cookies.")

        response = self.get_response(request)
        print("Response status:", response.status_code)
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
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        signed_url = blob.generate_signed_url(
            expiration=expiration,
            version="v4",
            method=method,
            content_type=content_type  # Include content_type if provided
        )
        print("Generated Signed URL:", signed_url)
        return signed_url
    except Exception as e:
        print("Error generating signed URL:", str(e))
        raise



class CustomGoogleCloudStorage(GoogleCloudStorage):
    def url(self, name):
        url = super().url(name)
        parsed_url = urlparse(url)
        new_url = f"https://storage.cloud.google.com{parsed_url.path}"
        print(f"Generated URL: {new_url}")  # Debug statement
        return new_url
