#models.py

from django.db import models
from .utility import media_file_upload, validate_bio_length
from datetime import datetime, timedelta
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


# Create your models here.


class Unique(models.Model):
    created_time = models.DateTimeField(auto_now_add=True)

    # Vous pouvez ajouter d'autres champs au besoin.


class User (AbstractUser):
    created_time = models.DateTimeField(auto_now_add=True, blank=False)
    first_name = models.CharField(max_length=30, blank=False)
    last_name = models.CharField(max_length=30, blank=False)
    username = models.CharField(max_length=30, unique=True, blank=False)
    email = models.EmailField(unique=True, blank=False)
    picture = models.CharField(
        max_length=500, default='default_profile_picture.jpg')
    bio = models.CharField(max_length=250, validators=[
                           validate_bio_length], default='New user at QipU!')
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name']


class Media (models.Model):
    created_time = models.DateTimeField(auto_now_add=True, blank=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        blank=False
    )
    caption = models.CharField(max_length=150)
    media_type = models.CharField(max_length=20, blank=False)
    permalink = models.CharField(max_length=500, blank=False)
    shortcode = models.CharField(max_length=50)
    storage_file = models.FileField(upload_to=media_file_upload, blank=False)
    is_published = models.BooleanField(default=False)
    category = models.IntegerField()


class Post (models.Model):
    created_time = models.DateTimeField(auto_now_add=True, blank=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE, blank=False
    )
    content = models.TextField(max_length=1000, blank=False)


class Event (models.Model):
    created_time = models.DateTimeField(auto_now_add=True, blank=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100, blank=False)
    description = models.TextField(max_length=1000, blank=False)
    location = models.CharField(max_length=150, blank=False)
    start_time = models.DateTimeField(blank=False)
    end_time = models.DateTimeField()
    recurrence_id = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE)


class RelationshipLabel(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Contact(models.Model):
    requester = models.ForeignKey(
        User, related_name="outgoing_requests", on_delete=models.CASCADE)
    recipient = models.ForeignKey(
        User, related_name="incoming_requests", on_delete=models.CASCADE)
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('refused', 'Refused'),
    )
    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, default='pending')
    # Automatically set when the request is sent
    request_sent_at = models.DateTimeField(auto_now_add=True)
    # To be set when the request is responded to
    response_received_at = models.DateTimeField(null=True, blank=True)
    labels = models.ManyToManyField(RelationshipLabel, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('requester', 'recipient')

    def __str__(self):
        return f"{self.requester.username} → {self.recipient.username}"


class Attendee (models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE, blank=False
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE, blank=False
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('refused', 'Refused'),
    )
    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, blank=False, default='pending')


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class UserTag(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="user_tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        unique_together = ['user', 'tag', 'content_type', 'object_id']

    def __str__(self):
        return f"{self.user.username} - {self.tag.name} - {self.content_object}"


class PostTag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('post', 'tag')  # Ensure uniqueness

    def __str__(self):
        return f"{self.post} - {self.tag}"


class MediaTag(models.Model):
    media = models.ForeignKey(Media, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('media', 'tag')  # Ensure uniqueness

    def __str__(self):
        return f"{self.media} - {self.tag}"
