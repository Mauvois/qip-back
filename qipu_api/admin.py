from django.contrib import admin
from .models import User, Media, Post, Event, Contact, Attendee, Unique, RelationshipLabel, Tag, UserTag

admin.site.register(User)
admin.site.register(Media)
admin.site.register(Post)
admin.site.register(Event)
admin.site.register(Contact)
admin.site.register(Attendee)
admin.site.register(Unique)
admin.site.register(RelationshipLabel)
admin.site.register(Tag)
admin.site.register(UserTag)
