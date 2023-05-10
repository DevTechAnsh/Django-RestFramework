from django.conf import settings
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import Token
from six import text_type


class AccessToken(Token):
    token_type = "access"
    lifetime = settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]

    @classmethod
    def for_user(cls, user):
        """
        Returns an authorization token for the given user that will be provided
        after authenticating the user's credentials.
        """
        user_id = getattr(user, api_settings.USER_ID_FIELD)
        if not isinstance(user_id, int):
            user_id = text_type(user_id)

        token = cls()
        token[api_settings.USER_ID_CLAIM] = user_id
        token["profile_type"] = user.profile_type
        return token
