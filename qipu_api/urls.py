# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet, MediaViewSet, PostViewSet, EventViewSet,
    ContactViewSet, AttendeeViewSet, UniqueViewSet,
    RelationshipLabelViewSet, TagSearchView, SignupView,
    LoginView, LogoutView, CheckSessionView, MediaDetailView,
    GenerateSignedURLView, AddItemView, PasswordResetRequestView, PasswordResetConfirmView,
    TagViewSet
)

router = DefaultRouter()
router.register(r'users', UserViewSet)
router.register(r'media', MediaViewSet, basename='media')
router.register(r'posts', PostViewSet, basename='posts')
router.register(r'events', EventViewSet)
router.register(r'contacts', ContactViewSet)
router.register(r'attendees', AttendeeViewSet)
router.register(r'uniques', UniqueViewSet)
router.register(r'relationship_labels', RelationshipLabelViewSet)
router.register(r'tags', TagViewSet, basename='tags')

urlpatterns = [
    path('signup/', SignupView.as_view(), name='signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('', include(router.urls)),
    path('check_session/', CheckSessionView.as_view(), name='check_session'),
    path('tag_search/', TagSearchView.as_view(), name='tag_search'),
    path('media-detail/<int:media_id>/',
         MediaDetailView.as_view(), name='media-detail'),
    path('generate-signed-url/', GenerateSignedURLView.as_view(),
         name='generate-signed-url'),
    path('items/add/', AddItemView.as_view(), name='add-item'),
    path('password-reset/', PasswordResetRequestView.as_view(),
         name='password_reset'),
    path('password-reset-confirm/<uidb64>/<token>/',
         PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]
