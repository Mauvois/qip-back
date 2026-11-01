#models.py

from django.db import models
from .utility import media_file_upload, validate_bio_length
from datetime import datetime, timedelta
import uuid
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


# Create your models here.


class Unique(models.Model):
    created_time = models.DateTimeField(auto_now_add=True)

    # Vous pouvez ajouter d'autres champs au besoin.


class User (AbstractUser):
    created_time = models.DateTimeField(auto_now_add=True, blank=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=32, blank=True)
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


# Research domain: kept alongside the prototype tables until existing data is inventoried.
class ResearchProject(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_research_projects')
    timezone = models.CharField(max_length=64, default='UTC')
    created_at = models.DateTimeField(auto_now_add=True)


class ProjectMembership(models.Model):
    ROLE_CHOICES = [('owner', 'Owner'), ('editor', 'Editor'), ('viewer', 'Viewer')]
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='research_memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'user'], name='unique_research_membership')]


class ResearchType(models.Model):
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT, related_name='research_types')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=[('generic', 'Générique'), ('source', 'Source'),
        ('entity', 'Entité'), ('information', 'Information'), ('relation', 'Relation')], default='generic')
    name = models.CharField(max_length=150)
    definition = models.TextField(blank=True)
    semantic_uri = models.URLField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'kind', 'name'], name='unique_research_type_kind_name')]


class HistoricalEntity(models.Model):
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT, related_name='historical_entities')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    label = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    type = models.ForeignKey(ResearchType, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class ResearchMedia(models.Model):
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT, related_name='research_media')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    reference = models.TextField(blank=True)
    author_label = models.CharField(max_length=250, blank=True)
    date_text = models.CharField(max_length=250, blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='parts')
    locator = models.CharField(max_length=250, blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    content_type = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EpistemicStatus(models.Model):
    code = models.SlugField(unique=True)
    label = models.CharField(max_length=100)
    definition = models.TextField(blank=True)


class ResearchItem(models.Model):
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT, related_name='research_items')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    type = models.ForeignKey(ResearchType, on_delete=models.PROTECT)
    epistemic_status = models.ForeignKey(EpistemicStatus, on_delete=models.PROTECT)
    label = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    date_text = models.CharField(max_length=250, blank=True)
    # CIDOC CRM E52 Time-Span bounds; null means unknown, never a fabricated date.
    begin_of_begin = models.DateField(null=True, blank=True)
    end_of_begin = models.DateField(null=True, blank=True)
    begin_of_end = models.DateField(null=True, blank=True)
    end_of_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ItemEntityParticipation(models.Model):
    item = models.ForeignKey(ResearchItem, on_delete=models.CASCADE, related_name='entity_participations')
    entity = models.ForeignKey(HistoricalEntity, on_delete=models.PROTECT)
    type = models.ForeignKey(ResearchType, on_delete=models.PROTECT)
    as_written = models.CharField(max_length=250, blank=True)


class ItemItemParticipation(models.Model):
    item = models.ForeignKey(ResearchItem, on_delete=models.CASCADE, related_name='item_participations')
    participant = models.ForeignKey(ResearchItem, on_delete=models.PROTECT, related_name='participates_in')
    type = models.ForeignKey(ResearchType, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(check=~models.Q(item=models.F('participant')), name='no_self_item_participation')]


class ItemMediaReference(models.Model):
    item = models.ForeignKey(ResearchItem, on_delete=models.CASCADE, related_name='media_references')
    media = models.ForeignKey(ResearchMedia, on_delete=models.PROTECT)
    locator = models.CharField(max_length=250, blank=True)
    note = models.TextField(blank=True)


# Qip research v2. These tables coexist with the prototype and v1 until their
# contents have been inventoried; an item cannot safely be migrated by renaming it.
class QipSource(models.Model):
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    type = models.ForeignKey(ResearchType, null=True, blank=True, on_delete=models.PROTECT)
    title = models.CharField(max_length=2000)
    description = models.TextField(blank=True)
    reference = models.TextField(blank=True)
    author_label = models.CharField(max_length=250, blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='parts')
    locator = models.CharField(max_length=250, blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    content_type = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SourceDating(models.Model):
    DATE_KINDS = [('production', 'Production'), ('issue', 'Émission'), ('publication', 'Publication')]
    source = models.ForeignKey(QipSource, on_delete=models.CASCADE, related_name='datings')
    date_kind = models.CharField(max_length=20, choices=DATE_KINDS)
    date_text = models.CharField(max_length=250, blank=True)
    begin_of_begin = models.DateField(null=True, blank=True)
    end_of_begin = models.DateField(null=True, blank=True)
    begin_of_end = models.DateField(null=True, blank=True)
    end_of_end = models.DateField(null=True, blank=True)
    begin_of_begin_time = models.TimeField(null=True, blank=True)
    end_of_begin_time = models.TimeField(null=True, blank=True)
    begin_of_end_time = models.TimeField(null=True, blank=True)
    end_of_end_time = models.TimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source'], condition=models.Q(is_primary=True),
                                            name='one_primary_source_dating')]


class QipEntity(models.Model):
    KINDS = [('person', 'Personne'), ('geographical_place', 'Lieu géographique'), ('other', 'Autre')]
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    kind = models.CharField(max_length=25, choices=KINDS)
    type = models.ForeignKey(ResearchType, null=True, blank=True, on_delete=models.PROTECT)
    label = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class QipPerson(models.Model):
    entity = models.OneToOneField(QipEntity, primary_key=True, on_delete=models.CASCADE, related_name='person')


class GeographicalPlace(models.Model):
    entity = models.OneToOneField(QipEntity, primary_key=True, on_delete=models.CASCADE, related_name='place')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    coordinate_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=(models.Q(latitude__isnull=True, longitude__isnull=True) |
                models.Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180)),
                name='valid_geographical_coordinates'),
        ]


class QipInformation(models.Model):
    LEVELS = [('factoid', 'Factoïde'), ('qualified', 'Information qualifiée')]
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    level = models.CharField(max_length=12, choices=LEVELS)
    type = models.ForeignKey(ResearchType, on_delete=models.PROTECT)
    label = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    date_text = models.CharField(max_length=250, blank=True)
    begin_of_begin = models.DateField(null=True, blank=True)
    end_of_begin = models.DateField(null=True, blank=True)
    begin_of_end = models.DateField(null=True, blank=True)
    end_of_end = models.DateField(null=True, blank=True)
    begin_of_begin_time = models.TimeField(null=True, blank=True)
    end_of_begin_time = models.TimeField(null=True, blank=True)
    begin_of_end_time = models.TimeField(null=True, blank=True)
    end_of_end_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class InformationCitation(models.Model):
    information = models.ForeignKey(QipInformation, on_delete=models.CASCADE, related_name='citations')
    source = models.ForeignKey(QipSource, on_delete=models.PROTECT)
    locator = models.CharField(max_length=250, blank=True)
    quotation = models.TextField(blank=True)
    note = models.TextField(blank=True)


class InformationEvidence(models.Model):
    RELATIONS = [('supports', 'Appuie'), ('contradicts', 'Contredit'), ('contextualizes', 'Contextualise')]
    qualified_information = models.ForeignKey(QipInformation, on_delete=models.CASCADE, related_name='evidence')
    factoid_information = models.ForeignKey(QipInformation, on_delete=models.PROTECT, related_name='used_as_evidence')
    relation = models.CharField(max_length=20, choices=RELATIONS)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['qualified_information', 'factoid_information', 'relation'],
                                            name='unique_information_evidence')]


class InformationEntityRelation(models.Model):
    information = models.ForeignKey(QipInformation, on_delete=models.CASCADE, related_name='entities')
    entity = models.ForeignKey(QipEntity, on_delete=models.PROTECT)
    type = models.ForeignKey(ResearchType, on_delete=models.PROTECT)
    as_written = models.CharField(max_length=250, blank=True)
    note = models.TextField(blank=True)


class PersonBirth(models.Model):
    person = models.OneToOneField(QipPerson, on_delete=models.CASCADE, related_name='birth')
    information = models.OneToOneField(QipInformation, on_delete=models.PROTECT, related_name='person_birth')
    place = models.ForeignKey(GeographicalPlace, null=True, blank=True, on_delete=models.PROTECT)
    note = models.TextField(blank=True)


class BibliographicRecord(models.Model):
    source = models.OneToOneField(QipSource, on_delete=models.CASCADE, related_name='bibliography')
    csl = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class ZoteroCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='zotero_credential')
    zotero_user_id = models.CharField(max_length=40)
    display_name = models.CharField(max_length=150, blank=True)
    token_encrypted = models.TextField()
    token_secret_encrypted = models.TextField()


class ZoteroOAuthAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE)
    request_token = models.CharField(max_length=150, unique=True)
    secret_encrypted = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class ZoteroCollection(models.Model):
    project = models.OneToOneField(ResearchProject, on_delete=models.CASCADE, related_name='zotero_collection')
    connected_by = models.ForeignKey(User, on_delete=models.PROTECT)
    library_kind = models.CharField(max_length=6, choices=[('users', 'Personal'), ('groups', 'Group')])
    library_id = models.CharField(max_length=40)
    collection_key = models.CharField(max_length=20)
    name = models.CharField(max_length=250)


class ZoteroItemLink(models.Model):
    source = models.OneToOneField(QipSource, on_delete=models.CASCADE, related_name='zotero_link')
    collection = models.ForeignKey(ZoteroCollection, on_delete=models.PROTECT)
    item_key = models.CharField(max_length=20)
    item_version = models.PositiveIntegerField()
    last_synced = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['collection', 'item_key'], name='unique_zotero_item_link')]


class ZoteroPreview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    collection = models.ForeignKey(ZoteroCollection, on_delete=models.CASCADE, null=True, blank=True)
    direction = models.CharField(max_length=10)
    rows = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    applied = models.BooleanField(default=False)
