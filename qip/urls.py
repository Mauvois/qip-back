from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.views import serve
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('qipu_api.urls')),
    path("__reload__/", include("django_browser_reload.urls")),
    path('api-auth/', include('rest_framework.urls')),
    # JWT endpoints
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

# if settings.DEBUG:
#     urlpatterns += static(settings.STATIC_URL, view=serve)
