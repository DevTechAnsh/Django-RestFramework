from io import BytesIO
from itertools import chain
from urllib.parse import urlencode

import requests
from django.conf import settings as s
from django.core.cache import cache
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404
from django.utils.six import text_type
from auth.jobs import slack_webhook_customer_success
from jwt import ExpiredSignatureError
from rest_framework import generics, mixins, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenViewBase
from tags.models import Country

from . import serializers as auth_serializers
from .models import (
    ClientProfile,
    User,
)
from .permissions import (
    AdminPermission,
    ClientPermission,
)


class TokenRefreshView(TokenViewBase):
    serializer_class = auth_serializers.TokenRefreshSerializer
    __doc__ = """
        post:
           # This api is used to refresh the user token
        endpoint: /auth/refresh-token
        """

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ExpiredSignatureError as e:
            return Response(data={"code": str(e)}, status=status.HTTP_401_UNAUTHORIZED)


token_refresh = TokenRefreshView.as_view()


class TokenObtainPairView(TokenViewBase):
    serializer_class = auth_serializers.TokenObtainPairSerializer
    __doc__ = """
    post:
       # This api is used to signin in the HM platform and it will return the refresh and access token
    endpoint: /auth/login
    """

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        refresh_token_text = serializer.validated_data["refresh"]
        if serializer.user.issue_refresh_token(refresh_token_text):
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "violating refresh token consistency"},
                status.HTTP_409_CONFLICT,
            )


token_obtain_pair = TokenObtainPairView().as_view()


class TokenObtainPairFromTokenView(GenericAPIView):
    permission_classes = [AdminPermission]
    serializer_class = auth_serializers.TokenObtainPairFromTokenSerializer
    __doc__ = """
       post:
          # This api is used to signin in the  platform and it will return the refresh and access token
       endpoint: /auth/login/<uuid:<user__uuid>>
       """

    def post(self, request, *args, **kwargs):
        data = request.data.copy()
        data["login_as_token"] = kwargs["uuid"]

        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        refresh_token_text = serializer.validated_data["refresh"]
        if serializer.user.issue_refresh_token(refresh_token_text):
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "violating refresh token consistency"},
                status.HTTP_409_CONFLICT,
            )


token_obtain_pair_from_token = TokenObtainPairFromTokenView().as_view()


class ClientBillingCreateAPIView(generics.RetrieveUpdateAPIView):
    queryset = ClientProfile.objects.all()
    permission_classes = [ClientPermission]
    serializer_class = auth_serializers.ClientBillingSerializer
    lookup_field = "uuid"
    lookup_url_kwarg = "uuid"
    __doc__ = """
                get:
                    # This api is used to get the billing info for client
                put:
                    # This api is used to update the billing info for client
                patch:
                    # This api is used to update the billing info for client
                endpoint:
                    /auth/{client_uuid}/billing-info
        """

    def perform_update(self, serializer):
        if self.request._data:
            instance = serializer.save()
            country = Country.objects.filter(
                uuid=self.request.data["billing_country"]
            ).first()
            user = self.request.user.fetch()
            name = (
                serializer.validated_data["billing_name"]
                if serializer.validated_data["billing_name"]
                else None
            )
            address_city = (
                serializer.validated_data["billing_city"]
                if serializer.validated_data["billing_city"]
                else None
            )
            address_state = (
                serializer.validated_data["billing_state"]
                if serializer.validated_data["billing_state"]
                else None
            )
            address_country = country.code.upper()
            address_line1 = (
                serializer.validated_data["billing_address_1"]
                if serializer.validated_data["billing_address_1"]
                else None
            )
            address_line2 = (
                serializer.validated_data["billing_address_2"]
                if serializer.validated_data["billing_address_2"]
                else None
            )
            address_zip = (
                serializer.validated_data["billing_postal"]
                if serializer.validated_data["billing_postal"]
                else None
            )
            phone = (
                serializer.validated_data["billing_phone"]
                if serializer.validated_data["billing_phone"]
                else None
            )
            email = (
                serializer.validated_data["billing_email"]
                if serializer.validated_data["billing_email"]
                else None
            )
            tax_type_id = (
                self.request.data["billing_tax"]
                if self.request.data["billing_tax"]
                else None
            )
            tax_value = (
                self.request.data["stripe_tax_value"]
                if self.request.data["stripe_tax_value"]
                else None
            )
            metadata = {"user_id": user.uuid}
            address = {
                "city": address_city,
                "country": address_country,
                "state": address_state,
                "postal_code": address_zip,
                "line1": address_line1,
                "line2": address_line2,
            }

            # Create or Update thre stripe details
            customer = user.create_or_update_stripe_customer(
                name, phone, email, metadata, address
            )
            # if instance.billing_tax.uuid != tax_type_id :
            user_stripe_tax = user.create_customer_tax_id(tax_type_id, tax_value)
            if user_stripe_tax:
                instance.stripe_tax_id = user_stripe_tax.id
                instance.save()

            return Response(data={"billing_data": "updated"}, status=status.HTTP_200_OK)

