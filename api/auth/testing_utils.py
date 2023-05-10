import logging
from django.contrib.auth import _clean_credentials

from rest_framework.test import APIClient, APITestCase
from rest_framework import status

from rest_framework_simplejwt.compat import reverse


logger = logging.getLogger(__name__)


def client_action_wrapper(action):
    def wrapper_method(self, *args, **kwargs):
        if self.view_name is None:
            raise ValueError('Must give value for `view_name` property')

        reverse_args = kwargs.pop('reverse_args', tuple())
        reverse_kwargs = kwargs.pop('reverse_kwargs', dict())
        query_string = kwargs.pop('query_string', None)

        url = reverse(self.view_name, args=reverse_args, kwargs=reverse_kwargs)
        if query_string is not None:
            url = url + '?{0}'.format(query_string)

        return getattr(self.client, action)(url, *args, **kwargs)

    return wrapper_method


class APIViewTestCase(APITestCase):
    client_class = APIClient

    def logout(self):
        self.client._credentials = _clean_credentials(self.client._credentials)

    def authenticate_with_token(self, type, token):
        """
        Authenticates requests with the given token.
        """
        self.client.credentials(HTTP_AUTHORIZATION='{} {}'.format(type, token))

    def authenticate_user(self, user):
        response = self.client.post(
            reverse('auth:login'),
            {'email': user.email, 'password': 'secret_pw'})
        if response.status_code != 200:
            print(response.json())
        response_json = response.json()
        if response.status_code != status.HTTP_200_OK:
            logger.debug(response_json)
        token = response_json['access']
        self.authenticate_with_token('Bearer', token)
        return response_json

    view_name = None

    view_post = client_action_wrapper('post')
    view_get = client_action_wrapper('get')

    def assert_response(self, response, status, body):
        try:
            self.assertEqual(response.status_code, status)
        except AssertionError:
            # TODO: use logger to display error to stdout
            raise
        self.assertEqual(response.json(), body)
