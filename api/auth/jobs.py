import json
import logging

import requests
from django.conf import settings as s
from django_rq import job

logger = logging.getLogger(__name__)


@job
def slack_webhook_customer_success(user_uuid):
    """This function is used to put the notification on slack when new user signed up"""
    if not s.SLACK_WEBHOOK_CUSTOMER_SUCCESS:
        return

    from auth.models import User

    try:
        user = User.objects.get(uuid=user_uuid)
    except User.DoesNotExist:
        # should never hit here!
        return

    webhook_url = s.SLACK_WEBHOOK_CUSTOMER_SUCCESS
    link = None
    if user.profile_type == "client":
        link = s.CLIENT_PROFILE_ADMIN_LINK

    slack_data = {
        "text": "The {0.profile_type} `{0.firstname_lastname} <{0.email}>` has "
        "signed up! :rocket:\nCheck in Admin: {link}".format(
            user, link=link.format(user.id)
        )
    }

    requests.post(
        webhook_url,
        data=json.dumps(slack_data),
        headers={"Content-Type": "application/json"},
    )
