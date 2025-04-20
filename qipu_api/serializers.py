from rest_framework import serializers
# Note the changes here
from .models import User, Media, Post, Event, Contact, Attendee, Unique, RelationshipLabel, Tag, UserTag


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={
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


class MediaSerializer(serializers.ModelSerializer):
    tagIds = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = '__all__'  # Includes all fields from the Media model, plus the tagIds we're adding

    def get_tagIds(self, obj):
        # Get all MediaTag instances related to this media and return their tag IDs
        return list(obj.mediatag_set.all().values_list('tag__id', flat=True))


class PostSerializer(serializers.ModelSerializer):
    tagIds = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = '__all__'  # Includes all fields from the Post model, plus the tagIds we're adding

    def get_tagIds(self, obj):
        # Get all PostTag instances related to this post and return their tag IDs
        return list(obj.posttag_set.all().values_list('tag__id', flat=True))


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'


class AttendeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendee
        fields = '__all__'


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
