from django.urls import path
from .views import (
    ChatView,
    SessionView,
    HealthView,
    SSOConfigView,
    SSOTokenExchangeView,
    WhoAmIView,
)

urlpatterns = [
    path("chat/", ChatView.as_view(), name="chat"),
    path("session/", SessionView.as_view(), name="session"),
    path("health/", HealthView.as_view(), name="health"),
    path("sso/config/", SSOConfigView.as_view(), name="sso_config"),
    path("sso/token/", SSOTokenExchangeView.as_view(), name="sso_token"),
    path("sso/whoami/", WhoAmIView.as_view(), name="whoami"),
]
