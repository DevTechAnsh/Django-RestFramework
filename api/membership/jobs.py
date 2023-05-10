from typing import AnyStr

from django_rq import job
from auth.models import User

from .models import Membership


@job
def subscribe_user_job(user_uuid, membership_uuid: AnyStr):
    """
    Job that safely processing payment for project posting and marks it as
    active when payment executed successfully
    """
    membership = Membership.objects.get(uuid=membership_uuid)
    user = User.objects.get(uuid=user_uuid)
    membership.subscribe(user)

    recurring_cost = float(membership.price_month) if membership.price_month else 0.0
    user.send_email(
        "User Subscription",
        {
            "MEMBERSHIP_NAME": membership.name,
            "RECURRING_COST": recurring_cost,
            "FIRST_NAME": user.get_user_profile().first_name,
        },
        "User Subscription",
        delay=False,
    )
