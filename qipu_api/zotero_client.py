"""OAuth 1.0a and Zotero Web API v3, with fixed destinations and bounded requests."""
import base64
import hashlib
import os
from urllib.parse import parse_qs, urlencode

import requests
from cryptography.fernet import Fernet
from django.conf import settings
from oauthlib.oauth1 import Client
from rest_framework.exceptions import ValidationError


API = 'https://api.zotero.org'
OAUTH = 'https://www.zotero.org/oauth'


def cipher():
    secret = os.environ.get('ZOTERO_TOKEN_ENCRYPTION_KEY')
    if not secret and not settings.DEBUG:
        raise ValidationError({'zotero': 'Configure a separate Zotero token encryption key on the server.'})
    secret = secret or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    return cipher().decrypt(value.encode()).decode()


def credentials():
    key = os.environ.get('ZOTERO_OAUTH_CLIENT_KEY', '')
    secret = os.environ.get('ZOTERO_OAUTH_CLIENT_SECRET', '')
    if not key or not secret:
        raise ValidationError({'zotero': 'Configure the Zotero OAuth application keys on the server.'})
    return key, secret


def oauth_request(method, url, *, token=None, secret=None, callback=None, verifier=None, data=None, headers=None):
    key, client_secret = credentials()
    signer = Client(key, client_secret=client_secret, resource_owner_key=token,
                    resource_owner_secret=secret, callback_uri=callback, verifier=verifier,
                    signature_type='AUTH_HEADER')
    body = None if data is None else urlencode(data)
    signed_url, signed_headers, body = signer.sign(url, http_method=method, body=body, headers=headers or {})
    try:
        response = requests.request(method, signed_url, headers=signed_headers, data=body,
                                    timeout=20, allow_redirects=False)
    except requests.RequestException:
        raise ValidationError({'zotero': 'Zotero is unreachable. Try again later.'})
    if response.status_code >= 400 or response.status_code in (301, 302, 307, 308):
        raise ValidationError({'zotero': f'Zotero returned HTTP {response.status_code}.'})
    return response


def oauth_tokens(response):
    values = parse_qs(response.text)
    return {key: value[0] for key, value in values.items()}


def api_request(credential, method, path, *, payload=None, version=None):
    if not path.startswith('/') or '://' in path or '..' in path:
        raise ValidationError({'zotero': 'Invalid API path.'})
    headers = {'Zotero-API-Version': '3', 'Accept': 'application/json'}
    if payload is not None:
        import json
        headers['Content-Type'] = 'application/json'
        payload = json.dumps(payload, ensure_ascii=False)
    if version is not None:
        headers['If-Unmodified-Since-Version'] = str(version)
    return oauth_request(method, API + path, token=decrypt(credential.token_encrypted),
                         secret=decrypt(credential.token_secret_encrypted), data=None,
                         headers=headers) if payload is None else _json_request(credential, method, path, payload, headers)


def _json_request(credential, method, path, payload, headers):
    key, client_secret = credentials()
    signer = Client(key, client_secret=client_secret, resource_owner_key=decrypt(credential.token_encrypted),
                    resource_owner_secret=decrypt(credential.token_secret_encrypted), signature_type='AUTH_HEADER')
    url, signed_headers, body = signer.sign(API + path, http_method=method, body=payload, headers=headers)
    try:
        response = requests.request(method, url, headers=signed_headers, data=body,
                                    timeout=20, allow_redirects=False)
    except requests.RequestException:
        raise ValidationError({'zotero': 'Zotero is unreachable. Try again later.'})
    if response.status_code >= 400 or response.status_code in (301, 302, 307, 308):
        raise ValidationError({'zotero': f'Zotero returned HTTP {response.status_code}.'})
    return response


def paged(credential, path, *, limit=100, max_items=2000):
    collected = []
    for start in range(0, max_items + 1, limit):
        suffix = '&' if '?' in path else '?'
        response = api_request(credential, 'GET', f'{path}{suffix}start={start}&limit={limit}')
        try:
            page = response.json()
        except ValueError:
            raise ValidationError({'zotero': 'Zotero returned invalid JSON.'})
        if not isinstance(page, list):
            raise ValidationError({'zotero': 'Zotero returned an unexpected response.'})
        if start == max_items and page:
            raise ValidationError({'zotero': 'Collection exceeds 2000 items. Split it into smaller collections.'})
        collected.extend(page)
        if len(page) < limit:
            return collected
    raise ValidationError({'zotero': 'Collection exceeds 2000 items. Split it into smaller collections.'})
