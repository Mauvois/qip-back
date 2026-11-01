# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet, MediaViewSet, PostViewSet, EventViewSet,
    ContactViewSet, AttendeeViewSet, UniqueViewSet,
    RelationshipLabelViewSet, TagSearchView, SignupView,
    LoginView, LogoutView, CheckSessionView, MediaDetailView,
    GenerateSignedURLView, AddItemView, PasswordResetRequestView, PasswordResetConfirmView,
    TagViewSet, TermsView
)
from .research_views import (
    ResearchProjectViewSet, ProjectMembershipViewSet, ResearchTypeViewSet,
    HistoricalEntityViewSet, ResearchMediaViewSet, EpistemicStatusViewSet,
    ResearchItemViewSet,
)
from .research_v2_views import (TypeViewSet as V2TypeViewSet, SourceViewSet as V2SourceViewSet,
    EntityViewSet as V2EntityViewSet, InformationViewSet as V2InformationViewSet,
    BirthViewSet as V2BirthViewSet, TimelineView, SearchView)
from .zotero_views import (ZoteroStatusView, ZoteroOAuthStartView, ZoteroOAuthCallbackView,
    ZoteroLibrariesView, ZoteroCollectionsView, ZoteroConnectView, ZoteroFilePreviewView,
    ZoteroFileExportView, ZoteroSyncPreviewView, ZoteroPreviewDetailView, ZoteroPreviewApplyView)

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

research_router = DefaultRouter()
research_router.register(r'projects', ResearchProjectViewSet, basename='research-projects')
research_router.register(r'memberships', ProjectMembershipViewSet, basename='research-memberships')
research_router.register(r'types', ResearchTypeViewSet, basename='research-types')
research_router.register(r'entities', HistoricalEntityViewSet, basename='research-entities')
research_router.register(r'media', ResearchMediaViewSet, basename='research-media')
research_router.register(r'epistemic-statuses', EpistemicStatusViewSet, basename='epistemic-statuses')
research_router.register(r'items', ResearchItemViewSet, basename='research-items')

v2_router = DefaultRouter()
v2_router.register(r'projects', ResearchProjectViewSet, basename='v2-projects')
v2_router.register(r'memberships', ProjectMembershipViewSet, basename='v2-memberships')
v2_router.register(r'types', V2TypeViewSet, basename='v2-types')
v2_router.register(r'sources', V2SourceViewSet, basename='v2-sources')
v2_router.register(r'entities', V2EntityViewSet, basename='v2-entities')
v2_router.register(r'informations', V2InformationViewSet, basename='v2-informations')
v2_router.register(r'person-births', V2BirthViewSet, basename='v2-person-births')

urlpatterns = [
    path('api/v2/zotero/status/', ZoteroStatusView.as_view()),
    path('api/v2/zotero/oauth/start/', ZoteroOAuthStartView.as_view()),
    path('api/v2/zotero/oauth/callback/', ZoteroOAuthCallbackView.as_view()),
    path('api/v2/zotero/libraries/', ZoteroLibrariesView.as_view()),
    path('api/v2/zotero/collections/', ZoteroCollectionsView.as_view()),
    path('api/v2/zotero/connect/', ZoteroConnectView.as_view()),
    path('api/v2/zotero/file/preview/', ZoteroFilePreviewView.as_view()),
    path('api/v2/zotero/file/export/', ZoteroFileExportView.as_view()),
    path('api/v2/zotero/sync/preview/', ZoteroSyncPreviewView.as_view()),
    path('api/v2/zotero/preview/<uuid:pk>/', ZoteroPreviewDetailView.as_view()),
    path('api/v2/zotero/preview/<uuid:pk>/apply/', ZoteroPreviewApplyView.as_view()),
    path('api/v2/timeline/', TimelineView.as_view(), name='v2-timeline'),
    path('api/v2/search/', SearchView.as_view(), name='v2-search'),
    path('api/v2/', include(v2_router.urls)),
    path('api/v1/', include(research_router.urls)),
    path('signup/', SignupView.as_view(), name='signup'),
    path('api/terms/', TermsView.as_view(), name='terms'),
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
