import datetime
import json
import logging
from copy import copy

import jwt
import stripe
from core.exceptions import ConflictValidationError
from django.conf import settings
from django.contrib.auth.backends import UserModel
from django.core import serializers as core_serializers
from django.db.models import Model
from django.utils.six import text_type
from django.utils.translation import ugettext_lazy as _

from rest_framework.fields import (CharField,
                                SerializerMethodField, UUIDField)
from rest_framework.serializers import (ModelSerializer,
                                        Serializer, ValidationError)
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from tiers.models import Tier
from  auth.utils import get_comet_chat_key
from . import models


# from attr import fields


logger = logging.getLogger(__name__)


class TokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super(TokenObtainPairSerializer, cls).get_token(user)
        # RefreshToken doesn't have method update, we can't update it like dict
        for key, value in user.get_jwt_payload().items():
            token[key] = value
        return token

    def validate(self, attrs):
        data = super(TokenObtainPairSerializer, self).validate(attrs)
        self.user.clear_login_as_token()
        return data


class TokenObtainPairFromTokenSerializer(TokenObtainPairSerializer):
    login_as_token = UUIDField(required=True)

    def __init__(self, *args, **kwargs):
        super(TokenObtainPairFromTokenSerializer, self).__init__(*args, **kwargs)

        del self.fields[self.username_field]
        del self.fields["password"]

    def validate(self, attrs):
        try:
            self.user = UserModel._default_manager.get(
                **{"login_as_token": attrs["login_as_token"]}
            )
        except UserModel.DoesNotExist:
            self.user = None

        if self.user is None or not self.user.is_active or not self.user.is_reviewed:
            raise ValidationError(
                _("No account found with the given token"),
            )

        refresh = self.get_token(self.user)

        data = dict()
        data["refresh"] = text_type(refresh)
        data["access"] = text_type(refresh.access_token)

        return data


class TokenRefreshSerializer(Serializer):
    refresh = CharField()

    def validate(self, attrs):

        refresh_data = jwt.decode(
            attrs["refresh"], settings.JWT_PUBLIC_KEY, algorithm="RS512"
        )
        user = models.User.objects.filter(
            is_active=True, uuid=refresh_data["user_uuid"]
        ).first()
        if user is None:
            logger.error(
                f"inactive or not existing user " f'token {refresh_data["user_uuid"]}'
            )
            raise ValidationError({"refresh": "inactive or not existing user token"})

        refresh = RefreshToken.for_user(user)
        for key, value in user.get_jwt_payload().items():
            refresh[key] = value
        if user.issue_refresh_token(text_type(refresh)):
            data = {
                "access": text_type(refresh.access_token),
                "refresh": text_type(refresh),
            }
        else:
            raise ConflictValidationError(
                {
                    "error": "violating refresh token consistency, "
                    "concurrent refresh requests"
                }
            )
        return data


class ClientBillingSerializer(ModelSerializer):
    class Meta:
        model = models.ClientProfile
        fields = (
            "billing_name",
            "billing_phone",
            "billing_email",
            "billing_city",
            "billing_country",
            "billing_address_1",
            "billing_address_2",
            "billing_postal",
            "billing_state",
            "billing_tax",
            "stripe_tax_value",
            "billing_kvk",
        )

