from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from .consumers import MyConsumer

websocket_urlpatterns = [
    path('ws/some_path/', MyConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    'websocket': URLRouter(websocket_urlpatterns)
})