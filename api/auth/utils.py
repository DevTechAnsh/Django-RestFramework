import os

from django.conf import settings

from djangoapi.settings import MAILCHIMP

import mailchimp_marketing as MailchimpMarketing
from mailchimp_marketing.api_client import ApiClientError
from rest_framework_simplejwt.authentication import JWTAuthentication


def get_raw_token_from_request(request) -> str:
    """This function is used to return the raw token from request"""
    header = JWTAuthentication.get_header(None, request)
    return JWTAuthentication.get_raw_token(None, header)


def subscribe_to_mailchimp(user):
    try:
        client = MailchimpMarketing.Client()
        client.set_config(
            {"api_key": MAILCHIMP.get("API_KEY"), "server": MAILCHIMP.get("SERVER")}
        )

        list_id = MAILCHIMP.get("LIST_ID")
        company = user.company.name if user.company else ""
        entry_point = user.entry_point_type if user.entry_point_type else "Default"
        job_title = (
            user.job_title
            if not user.profile_type == "freelancer" and user.job_title
            else ""
        )

        env = os.environ["DJANGO_SETTINGS"]

        merge_fields = {
            "FNAME": user.first_name,
            "LNAME": user.last_name,
            "COMPANY": company,
            "JOBTITLE": job_title,
        }
        tags = [entry_point, env, user.profile_type]

        response = client.lists.add_list_member(
            list_id,
            {
                "email_address": user.email,
                "status": "subscribed",
                "merge_fields": merge_fields,
                "tags": tags,
            },
        )
        return response.get("id")
    except ApiClientError as error:
        print("Error: {}".format(error.text))
        return False


def get_comet_chat_key():
    try:
        if settings.COMET_CHAT and settings.COMET_CHAT["API_KEY"] is not None :
            return True
    except:
        return False
