import functools
import logging
from datetime import date
from decimal import Decimal
from typing import AnyStr, Dict, NoReturn, Optional

import stripe
from core.models import MoneyField, UUIDModel
from django.db import models, transaction
from auth.models import User
from payment.models import PaymentFee

logger = logging.getLogger(__name__)


class MembershipManager(models.Manager):
    def get_users_initial(self, user: User):
        return Membership.objects.filter(
            profile_type=user.profile_type, is_initial=True
        ).first()


class Membership(UUIDModel):
    name = models.CharField(max_length=32)
    application_fee_percentage = models.PositiveSmallIntegerField()
    concierge_price = MoneyField(null=True, blank=True)
    expert_review_discount_percentage = MoneyField(null=True, blank=True)
    matchmaking_fee = MoneyField()
    marketing_package_discount_percentage = MoneyField(null=True, blank=True)
    price_month = MoneyField(null=True, blank=True)
    price_annual = MoneyField(null=True, blank=True)
    project_price = MoneyField(null=True, blank=True)
    profile_type = models.CharField(max_length=16, choices=User.PROFILE_TYPES)

    stripe_monthly_product_name = models.CharField(
        max_length=128, null=True, blank=True
    )
    stripe_annual_product_name = models.CharField(max_length=128, null=True, blank=True)

    is_initial = models.BooleanField()

    is_active = models.BooleanField(default=True)

    objects = MembershipManager()

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        raise TypeError("cannot remove membership")

    @transaction.atomic
    def subscribe(self, user: User) -> NoReturn:
        """
        TODO: Consider moving this functionality to auth.User
        """
        update_fields = ["current_membership"]
        stripe_subscription_id = None
        stripe_plan_id = None
        if self.is_downgrade(user):
            user.last_membership_downgrade_date = date.today()
            update_fields.append("last_membership_downgrade_date")
            # deactivate all his packages if it's a freelancer
            if user.profile_type == "freelancer":
                user.get_user_profile().package_set.update(is_active=False)

            # user.refund(self)
        elif not self.is_initial:  # don't create stripe subscription on initial
            stripe_plan: Dict = self.get_stripe_plan()
            stripe_plan_id: str = stripe_plan["id"]
            # TODO: switching from monthly  to annual and
            #  reverse should happen here
            stripe_subscription = user.stripe_subscribe(
                stripe_plan_id, {"object_type": "membership", "uuid": str(self.uuid)}
            )
            stripe_subscription_id = stripe_subscription["id"]

        user.current_membership = self
        user.save(update_fields=update_fields)
        MembershipHistory.objects.create(
            user=user,
            membership=self,
            stripe_plan_id=stripe_plan_id,
            stripe_subscription_id=stripe_subscription_id,
        )

    def is_downgrade(self, user: User) -> bool:
        """
        Checks if current subscription price less than another subscription price
        """
        current_membership = user.current_membership
        if current_membership is None or current_membership.is_initial:
            return False
        elif self.is_initial:
            return True
        else:
            return self.price_month < current_membership.price_month

    def get_stripe_plan(self) -> Optional[Dict]:
        if self.is_initial:
            return None  # Initial Memberships don't have plans

        # TODO: add annual plan here when we going to add it
        stripe_product_names = (self.stripe_monthly_product_name,)
        for plan in stripe.Plan.list():
            if plan["name"] in stripe_product_names:
                return plan
        logger.error("Plan not found for {self.pk}")

    def get_project_price_detailed(
        self, has_concierge_service: bool, add_stripe_fee: bool
    ) -> Dict[AnyStr, Decimal]:
        """
        Returns a dictionary with all the price details.
        I put it here, not in projects.Project model just because we need to
        show project prices without existing project instance, but with existing
        membership instance.
        """
        membership: Membership = self
        payment_fee = PaymentFee.get_current_fees()
        project_price: Decimal = payment_fee.project_posting_price or Decimal(0.0)
        if has_concierge_service:
            concierge_price: Decimal = membership.concierge_price or Decimal(0.0)
            subtotal = project_price + concierge_price
        else:
            concierge_price = Decimal(0.0)
            subtotal = project_price

        vat_price = Decimal(subtotal * payment_fee.tax_percentage / 100)
        if add_stripe_fee:
            stripe_fee = Decimal(subtotal * payment_fee.stripe_percentage / 100)
        else:
            stripe_fee = Decimal(0.0)

        _round = functools.partial(round, ndigits=2)
        return {
            "project_price": _round(project_price),
            "concierge_price": _round(concierge_price),
            "vat_price": _round(vat_price),
            "stripe_fee": _round(stripe_fee),
        }

    def get_project_posting_price(
        self, has_concierge_service: bool, add_stripe_fee: bool
    ) -> Decimal:
        price_dict: Dict[AnyStr, Decimal] = self.get_project_price_detailed(
            has_concierge_service, add_stripe_fee
        )
        return sum(price_dict.values())


class MembershipHistory(UUIDModel):
    """
    The history of change subscriptions for one particular user.
    """

    membership = models.ForeignKey("Membership", on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=64, null=True, blank=True)
    stripe_plan_id = models.CharField(max_length=64, null=True, blank=True)
