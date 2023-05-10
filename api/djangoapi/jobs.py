import logging

import mandrill
from django.conf import settings
from django.db import transaction
from django_rq import job

mandrill_client = mandrill.Mandrill(settings.MANDRILL_API_KEY)

logger = logging.getLogger(__name__)


@job
def email_send_template(
    template_name,
    vars,
    subject,
    recipient,
    sender_name=None,
    user_event_uuid=None,
    from_email=None,
):
    vars.setdefault("APP_URL", settings.APP_URL)

    merge_vars = []
    for key, value in vars.items():
        merge_vars.append({"name": key, "content": value})

    try:
        recipient_email = recipient.email
    except Exception as e:
        recipient_email = recipient.get("email")

    if not from_email:
        from_email = settings.MEMBER_FROM_EMAIL

    message = {
        "to": [{"email": recipient_email}],
        "from_email": from_email,
        "from_name": sender_name if sender_name else settings.MEMBER_FROM_NAME,
        "subject": subject,
        "merge": True,
        "merge_vars": [{"rcpt": recipient_email, "vars": merge_vars}],
        "merge_language": "mailchimp",
    }

    if user_event_uuid:
        with transaction.atomic():
            pass
    response = None

    try:
        response = mandrill_client.messages.send_template(template_name, [], message)
    except Exception as e:
        if user_event_uuid:
            with transaction.atomic():
                pass
            raise
    else:
        if user_event_uuid:
            with transaction.atomic():
                pass
    return response


@job
def email_send_plain(subject, recipient_email, html_body):
    message = {
        "to": [{"email": recipient_email}],
        "from_email": settings.MEMBER_FROM_EMAIL,
        "from_name": settings.MEMBER_FROM_NAME,
        "subject": subject,
        "merge": False,
        "html": html_body,
    }
    mandrill_client.messages.send(message=message)
