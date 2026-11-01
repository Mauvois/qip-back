from rest_framework import serializers
# Note the changes here
from .models import User, Media, Post, Event, Contact, Attendee, Unique, RelationshipLabel, Tag, UserTag


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, style={
                                     'input_type': 'password'})

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'email',
                  'first_name', 'last_name', 'created_time', 'picture', 'bio']

    def create(self, validated_data):
        # Remove the password from the validated data and create a user
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=['password'])
        return instance


class MediaSerializer(serializers.ModelSerializer):
    tagIds = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = '__all__'  # Includes all fields from the Media model, plus the tagIds we're adding
        read_only_fields = ['user', 'created_time']

    def get_tagIds(self, obj):
        # Get all MediaTag instances related to this media and return their tag IDs
        return list(obj.mediatag_set.all().values_list('tag__id', flat=True))


class PostSerializer(serializers.ModelSerializer):
    tagIds = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = '__all__'  # Includes all fields from the Post model, plus the tagIds we're adding
        read_only_fields = ['user', 'created_time']

    def get_tagIds(self, obj):
        # Get all PostTag instances related to this post and return their tag IDs
        return list(obj.posttag_set.all().values_list('tag__id', flat=True))


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = '__all__'
        read_only_fields = ['user', 'created_time']


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'
        read_only_fields = ['requester']

    def validate(self, attrs):
        if self.instance and 'recipient' in attrs and attrs['recipient'] != self.instance.recipient:
            raise serializers.ValidationError({'recipient': 'Cannot change recipient.'})
        return attrs


class AttendeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendee
        fields = '__all__'

    def validate(self, attrs):
        event = attrs.get('event', self.instance.event if self.instance else None)
        if not self.instance and event and event.user_id != self.context['request'].user.pk:
            raise serializers.ValidationError({'event': 'Only the event owner can invite.'})
        if self.instance and event != self.instance.event:
            raise serializers.ValidationError({'event': 'Cannot change event.'})
        if self.instance and 'user' in attrs and attrs['user'] != self.instance.user:
            raise serializers.ValidationError({'user': 'Cannot change attendee.'})
        return attrs


class UniqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unique
        fields = '__all__'


class RelationshipLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelationshipLabel
        fields = '__all__'


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = '__all__'


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError("Passwords do not match")
        return data
