from django.urls import path

from . import views

app_name = "auth"

urlpatterns = [
    path("/login", views.token_obtain_pair, name="login"),
    path("/refresh-token", views.token_refresh, name="refresh_token"),
    path("/login/<uuid:uuid>", views.token_obtain_pair_from_token, name="login_as"),
    path(
        "/<uuid:uuid>/billing-info",
        views.ClientBillingCreateAPIView.as_view(),
        name="client_billing_info_create",
    )
]
