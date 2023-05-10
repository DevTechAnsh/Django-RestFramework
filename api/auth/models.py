import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, AnyStr, Dict, Mapping, NoReturn, Optional, Tuple, Union
from urllib.parse import urljoin

import stripe
from core.draft.models import DraftBase
from core.models import MoneyField, UUIDModel
from core.money import Amount
from django.apps import apps
from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import JSONField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models.manager import EmptyManager
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse as django_reverse
from django.utils.functional import cached_property
from django.utils.timezone import now
from flex_team.models import FlexTeam
from djangoapi.jobs import email_send_plain, email_send_template
from auth.hubspot import export_contacts_client, export_contacts_freelancer
from auth.jobs import create_or_update_hubspot_contact
from auth.language_levels import (LanguageLevelsUnpacked,
                                    unpack_language_levels_data)
from project_membership.models import ProjectMembership
from projects.models import Project
from rest_framework_simplejwt.compat import CallableFalse, CallableTrue
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from standard_packages.models import (StandardPackageInterest,
                                      StandardPackageSelection)
from subscriptions.models import TierSubscription
from tags.models import BillingTax

logger = logging.getLogger(__name__)


class UserManager(BaseUserManager):
    def create_user(
        self, email, password, project=None, standard_package=None, **extra_fields
    ):
        from membership.models import Membership

        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email.lower())

        model_kwargs = {}
        m2ms = {}
        for field, value in extra_fields.items():
            if isinstance(value, (list, tuple)):  # TODO: find better m2m check
                m2ms[field] = value
            else:
                model_kwargs[field] = value

        user = self.model(email=email, **model_kwargs)
        user.set_password(password)
        user.save(using=self._db)

        if project is not None:
            instance, is_created = ProjectMembership.objects.get_or_create(
                user=user, project=project
            )

            if is_created:
                project.get_or_create_phi_settings()

                project.client.send_email(
                    template_name="Your invitation was accepted",
                    vars={
                        "FREELANCER": instance.user.firstname_lastname,
                        "PROJECT": instance.project.title,
                        "PROJECT_TEAM_LINK": settings.PROJECT_TEAM_LINK_NEW.format(
                            instance.project.uuid
                        ),
                        "CUSTOM_MESSAGE": instance.project.phi_settings.survey_message,
                    },
                    subject=None,
                )

        if standard_package is not None:
            StandardPackageInterest.objects.get_or_create(
                user=user, standard_package=standard_package
            )

        for field, value in m2ms.items():
            getattr(user, field).set(value)

        membership = Membership.objects.get_users_initial(user)
        if membership is None:
            # Do not crash here if there is no membership for user, just
            # let it continue and log the error
            logger.error(
                f"Initial membership for {user} of type {user.profile_type} "
                f"not found, continue with empty membership"
            )
        else:
            membership.subscribe(user)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_reviewed", True)
        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        """
        Used to authenticate users with lowercase email
        """
        return self.get(**{self.model.USERNAME_FIELD: username.lower()})

    def update_by_refresh_token(
        self, pk, last_refresh_token, refresh_token_text
    ) -> bool:
        """
        Update user refresh token by last_refresh token and user pk
        """
        return bool(
            User.objects.filter(pk=pk, last_refresh_token=last_refresh_token).update(
                last_refresh_token=refresh_token_text
            )
        )


class ApprovedUsersManager(BaseUserManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_reviewed=True, is_active=True)


class User(AbstractBaseUser):
    USERNAME_FIELD = "email"

    PROFILE_TYPES = [
        ("client", "client"),
        ("freelancer", "freelancer"),
        ("adviser", "adviser"),
    ]

    PROFILE_TYPES_MAP = {
        "client": "auth.ClientProfile",
        "freelancer": "auth.FreelancerProfile",
        "adviser": "auth.AdviserProfile",
    }

    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64)
    skills = models.ManyToManyField(
        "tags.Skill", related_name="skills_for_user", blank=True
    )

    photo = models.ForeignKey(
        "pix.Picture",
        on_delete=models.CASCADE,
        limit_choices_to={"context": "profile"},
        related_name="user_photo",
        null=True,
        blank=True,
    )

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)

    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)

    is_superuser = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # show_welcome_message = models.BooleanField(default=True)

    date_joined = models.DateTimeField(default=now)
    last_login = models.DateTimeField(default=now)

    is_reviewed = models.BooleanField(default=False)
    # TODO: the field is_profile_completed is not used anymore and it's legacy
    # TODO: remove it from JWT payload and then from the model
    is_profile_completed = models.BooleanField(default=False)
    is_email_confirmed = models.BooleanField(default=False)

    profile_type = models.CharField(max_length=16, choices=PROFILE_TYPES)

    last_refresh_token = models.TextField("Base 64 refresh token")
    login_as_token = models.TextField(null=True, blank=True)

    stripe_customer_token = models.CharField(max_length=128, null=True, blank=True)

    current_membership = models.ForeignKey(
        "membership.Membership", on_delete=models.PROTECT, null=True, blank=True
    )

    last_membership_downgrade_date = models.DateField(null=True, blank=True)
    last_membership_payment_date = models.DateField(null=True, blank=True)

    has_comet_chat_account = models.BooleanField(default=False)

    entry_point_url = models.CharField(max_length=200, null=True, blank=True)
    entry_point_type = models.CharField(max_length=128, null=True, blank=True)

    mailchimp_id = models.CharField(max_length=200, null=True, blank=True)

    kvk = models.CharField(
        max_length=8,
        validators=[
            RegexValidator(
                regex="^[0-9]{8}$",
                message="Value does not match format xxxxxxxx, where x is a digit.",
                code="nomatch",
            )
        ],
        null=True,
        blank=True,
    )
    btw = models.CharField(
        max_length=14,
        validators=[
            RegexValidator(
                regex="^NL[0-9]{9}B[0-9]{2}$",
                message="Value does not match format NL xxxxxxxxx B xx, where x is a digit.",
                code="nomatch",
            )
        ],
        null=True,
        blank=True,
    )

    referred_site = models.ForeignKey(
        "auth.ReferredSite", on_delete=models.PROTECT, null=True, blank=True
    )
    objects = UserManager()
    approved_objects = ApprovedUsersManager()

    def generate_login_as_token(self):
        if not self.is_reviewed:
            raise ValueError("User is not Reviewed")
        if not self.is_active:
            raise ValueError("User is not Active")
        if self.profile_type not in (
            "client",
            "freelancer",
        ):
            raise ValueError("User is not Client or Freelancer")

        self.login_as_token = str(uuid.uuid4())
        self.save(update_fields=["login_as_token"])

        return self.login_as_token

    def clear_login_as_token(self):
        self.login_as_token = None
        self.save(update_fields=["login_as_token"])

    def __repr__(self):
        return f"<User {self.email}>"

    def has_module_perms(self, app_label):
        return True

    def has_perm(self, app_label):
        return True

    @classmethod
    def admin_user(cls, email):
        return cls(first_name="", last_name="Admin", email=email)

    @property
    def skills_name(self):
        _list = []
        for s in self.skills.all():
            try:
                _list.append(s.name)
            except AttributeError:
                pass
        return _list

    @property
    def photo_file(self):
        try:
            return self.photo.file.url
        except (AttributeError, TypeError):
            pass

    @property
    def can_downgrade_membership(self):
        """
        Downgrade plan can be done only once per month
        """
        if self.last_membership_downgrade_date is None:
            return True
        else:
            today = date.today()
            return (
                self.last_membership_downgrade_date.year != today.year
                or self.last_membership_downgrade_date.month != today.month
            )

    @property
    def hubspot_skills_name(self):
        return ",".join(self.skills_name)

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        return super().save(*args, **kwargs)

    def get_default_card(self):
        """
        return default card from stripe
        """
        customer = self.get_stripe_customer()
        if customer is not None and customer.default_source is not None:
            return customer.sources.retrieve(customer.default_source)
        else:
            return None

    def add_card(self, source_token: str):
        customer, _ = self.get_or_create_stripe_customer()
        new_card = customer.sources.create(source=source_token)
        existing_fingerprints = [card.fingerprint for card in customer.sources.data]
        if new_card.fingerprint in existing_fingerprints:
            self.delete_card(new_card.id)
            return None
        return new_card

    def has_card_id(self, card_id: Mapping) -> bool:
        customer = self.get_stripe_customer()
        if customer is None:
            return False
        for user_card in customer.sources.data:
            if user_card["id"] == card_id:
                return True
        return False

    def delete_card(self, card_id: str):
        # print('customer', self.get_stripe_customer())
        for card in self.get_stripe_customer().sources.data:
            if card["id"] == card_id:
                return card.delete()

    def get_charges(self, limit=10, offset=None):
        """
        Returns a list of charges associated with current user.
        """
        if not self.stripe_customer_token:
            return None
        return stripe.Charge.list(customer=self.stripe_customer_token, limit=limit)

    def charge(
        self,
        amount: Decimal,
        description: AnyStr,
        *,
        metadata: Optional[Dict] = None,
        card: Optional["stripe_card_object"] = None,
    ) -> NoReturn:
        """
        Charge one particular user with amount.
        """
        if isinstance(amount, Decimal):
            amount = Amount(amount)
        else:
            raise TypeError(f"bad type on {amount} {type(amount)}")
        if card:
            source = card
        else:
            source = self.get_default_card()
        charge = stripe.Charge.create(
            amount=amount.to_stripe(),
            description=description,
            source=source["id"],
            customer=self.stripe_customer_token,
            currency=settings.DEFAULT_STRIPE_CURRENCY,
            metadata=metadata,
        )

    def charge_direct_card(
        self,
        amount: Decimal,
        application_fee: Decimal,
        stripe_account: AnyStr,
        description: AnyStr,
        source: Optional["stripe_card_object"],
        *,
        metadata: Optional[Dict] = None,
    ) -> "stripe.Charge":
        """
        Implements stripe.connect direct charges.
        Charges the user (client) to a particular stripe account id.
        """
        amount = Amount(amount)
        application_fee = Amount(application_fee)

        customer = self.get_stripe_customer()
        oneoff_source = stripe.Source.create(
            original_source=source["id"],
            usage="single_use",
            customer=customer["id"],
            stripe_account=stripe_account,
        )
        return stripe.Charge.create(
            amount=amount.to_stripe(),
            description=description,
            source=oneoff_source["id"],
            currency=settings.DEFAULT_STRIPE_CURRENCY,
            metadata=metadata,
            stripe_account=stripe_account,
            application_fee=application_fee.to_stripe(),
        )

    def charge_direct_ideal(
        self,
        amount: Decimal,
        application_fee: Decimal,
        stripe_account: AnyStr,
        description: AnyStr,
        source: AnyStr,
        # source: Optional['stripe_card_object'],
        # *,
        metadata: Optional[Dict] = None,
    ) -> "stripe.Charge":
        """
        Implements stripe.connect direct charges with iDEAL payments.
        The difference between charge_direct_card, we don't need to create a
        single-use source because ideal source is a single-use by itself.
        """
        amount = Amount(amount)
        application_fee = Amount(application_fee)

        test_source = source
        customer = self.get_stripe_customer()
        source_id = test_source.get("id")
        return stripe.Charge.create(
            amount=amount.to_stripe(),
            description=description,
            source=source_id,
            currency=settings.DEFAULT_STRIPE_CURRENCY,
            metadata=metadata,
            stripe_account=stripe_account,
            application_fee=application_fee.to_stripe(),
        )

    def refund(
        self, amount: Decimal, description: AnyStr, metadata=Optional[Dict]
    ) -> NoReturn:
        pass

    def create_stripe_customer(self) -> Optional[Dict[AnyStr, Any]]:
        """
        Takes stripe source token as input value then tries to create a
        customer and payments.Card model instance
        """
        if self.stripe_customer_token:
            return None
        else:
            stripe_customer = stripe.Customer.create(email=self.email)
            self.stripe_customer_token = stripe_customer["id"]
            self.save(update_fields=["stripe_customer_token"])
            return stripe_customer

    def get_stripe_customer(self) -> Optional[Dict[AnyStr, Any]]:
        """
        Returns a customer from Stripe API if token exists
        """
        if self.stripe_customer_token:
            return stripe.Customer.retrieve(
                self.stripe_customer_token, expand=["sources", "subscriptions"]
            )
        else:
            return None

    def create_or_update_stripe_customer(
        self, name, phone, email, metadata, address
    ) -> Optional[Dict[AnyStr, Any]]:
        """
        Update  a customer from Stripe API if token exists
        """
        if not self.stripe_customer_token:
            return stripe.Customer.create(
                name=name, phone=phone, email=email, metadata=metadata, address=address
            )
        else:
            return stripe.Customer.modify(
                self.stripe_customer_token,
                name=name,
                email=email,
                phone=phone,
                address=address,
                metadata=metadata,
            )

    def create_customer_tax_id(self, tax_type_id, tax_value):
        """
        Returns the created stripe customer tax id & tax type
        """
        billing_tax = BillingTax.objects.filter(uuid=tax_type_id).first()
        if self.stripe_customer_token:
            try:
                return stripe.Customer.create_tax_id(
                    self.stripe_customer_token,
                    type=billing_tax.country_code,
                    value=tax_value,
                )
            except stripe.error.InvalidRequestError:
                return None
        else:
            return None

    def send_invoice_overview_email(self):
        self.send_email(
            template_name="Client - Invoice sent overview",
            vars={
                "NAME": self.firstname_lastname,
                "MY_PROJECTS_LINK": settings.CLIENT_PROJECTS_LINK,
            },
            subject=f"We finalised last months project hours!",
            from_email=settings.ADMIN_INVOICES_EMAIL,
        )

    def paid_or_finalize_customer_invoice(self, stripe_invoice, create_invoice):
        if self.stripe_customer_token:
            pay_invoice = {}
            open_invoice = {}
            if create_invoice:
                if stripe_invoice.status == "paid":
                    try:
                        pay_invoice = stripe.Invoice.pay(
                            create_invoice.id, paid_out_of_band="true"
                        )
                        stripe_invoice.stripe_working_hours.filter(
                            status="APPROVED"
                        ).update(status="PAID")
                    except Exception as e:
                        raise (e)
                else:
                    open_invoice = stripe.Invoice.finalize_invoice(create_invoice.id)
                    stripe.Invoice.send_invoice(create_invoice.id)
                    # send email
                    if self.profile_type == "client":
                        if stripe_invoice.stripe_working_hours.filter(
                            contract__status="IN_PROGRESS"
                        ).exists():
                            self.send_invoice_overview_email()
                    stripe_invoice.status = "open"
                    timestamp = datetime.fromtimestamp(create_invoice.due_date)
                    stripe_invoice.due_date = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    stripe_invoice.save()
                stripe_invoice.stripe_url = (
                    open_invoice.hosted_invoice_url
                    if open_invoice
                    else pay_invoice.hosted_invoice_url
                )
                stripe_invoice.customer_id = self.stripe_customer_token
                stripe_invoice.stripe_invoice_id = create_invoice.id
                stripe_invoice.save()
        else:
            return None

    def create_customer_monthly_invoice(self, stripe_invoice):
        collection_method = "send_invoice"
        auto_advance = "false"
        automatic_tax = {"enabled": "false"}
        if self.stripe_customer_token:
            customer_id = self.stripe_customer_token
            try:
                create_invoice = stripe.Invoice.create(
                    customer=customer_id,
                    auto_advance=auto_advance,
                    collection_method=collection_method,
                    automatic_tax=automatic_tax,
                    days_until_due=30,
                    payment_settings={
                        "payment_method_options": {
                            "customer_balance": {
                                "funding_type": "bank_transfer",
                                "bank_transfer": {
                                    "type": "eu_bank_transfer",
                                    "eu_bank_transfer": {"country": "NL"},
                                },
                            },
                            "card": {"request_three_d_secure": "any"},
                        },
                        "payment_method_types": [
                            "sofort",
                            "sepa_debit",
                            "ideal",
                            "giropay",
                            "eps",
                            "bancontact",
                            "p24",
                            "customer_balance",
                        ],
                    },
                )
                if create_invoice:
                    self.paid_or_finalize_customer_invoice(
                        stripe_invoice, create_invoice
                    )
            except Exception as e:
                raise (e)
        else:
            return None

    def get_or_create_stripe_customer(self) -> Tuple[bool, Dict[AnyStr, Any]]:
        """
        Returns a customer from Stripe API if token exists
        """
        if self.stripe_customer_token:
            return (
                stripe.Customer.retrieve(
                    self.stripe_customer_token, expand=["sources"]
                ),
                False,
            )
        else:
            return self.create_stripe_customer(), True

    def delete_on_stripe(self) -> bool:
        stripe_customer = self.get_stripe_customer()
        if stripe_customer:
            res = stripe_customer.delete()
            self.stripe_customer_token = None
            return res["deleted"]
        else:
            return False

    def set_default_card(self, card: "stripe source object") -> Dict:
        """
        sets default stripe card and updates Stripe API
        """
        return stripe.Customer.modify(
            self.stripe_customer_token, default_source=card["id"]
        )

    def create_one_off_token(self, prefix: AnyStr) -> AnyStr:
        """
        Returns and sets an one-off UUID for given user
        """
        one_off_token = uuid.uuid4()
        token_lifetime = 24 * 60 * 60  # one day
        cache.set(f"{prefix}_{one_off_token}", self.pk, token_lifetime)
        return one_off_token

    def get_jwt_payload(self) -> Dict[str, Union[str, bool]]:
        payload = dict(
            profile_type=self.profile_type,
            is_email_confirmed=self.is_email_confirmed,
            is_reviewed=self.is_reviewed,
            is_profile_completed=self.is_profile_completed,
            is_concierge=bool(self.login_as_token),
            user_uuid=str(self.uuid),
            user_email=self.email,
        )
        return payload


    def issue_refresh_token(self, refresh_token_text: AnyStr) -> bool:
        """
        Updates last_refresh_token field and blacklists the old value
        """
        if self.last_refresh_token:
            try:
                RefreshToken(self.last_refresh_token).blacklist()
            except TokenError:
                # no need to backlist expired token
                pass
        # avoiding concurrent operation on update
        updated = User.objects.update_by_refresh_token(
            self.pk, self.last_refresh_token, refresh_token_text
        )
        self.refresh_from_db()
        return updated

    def get_user_profile(self):
        owner_profile = None
        profile_type_name = self.get_profile_type_display()
        if not profile_type_name:
            return None
        profile_class_name = self.PROFILE_TYPES_MAP.get(profile_type_name, "")
        if not profile_class_name:
            return None
        profile_class = apps.get_model(profile_class_name)
        if profile_class:
            owner_profile = profile_class.objects.filter(user_ptr__id=self.id).first()
        return owner_profile

    def create_user_profile(self):
        """
        TODO: create a function get_profile_class
        """
        profile_type_name = self.get_profile_type_display()
        if not profile_type_name:
            return None
        profile_class_name = self.PROFILE_TYPES_MAP.get(profile_type_name, "")
        if not profile_class_name:
            return None
        profile_class = apps.get_model(profile_class_name)

        # Dirty hack to prevent child model to overwrite the parent one
        # https://code.djangoproject.com/ticket/7623
        profile = profile_class(user_ptr=self)
        profile.__dict__.update(self.__dict__)
        profile.save()
        return profile

    def restore_photo_ownership(self):
        """
        binds photo ownership to current user see #215
        """
        if self.photo.user is None:
            photo = self.photo
            photo.user = self
            photo.save(update_fields=["user"])
        elif self.photo.user_id == self.pk:
            logging.error(
                f"trying to restore ownership where picture is already owned. "
                "user_id: {self.pk} pix_id: {self.photo_id}"
            )
        elif self.photo.user_id != self.pk:
            logging.error(
                f"restoring picture owned by another user, aborting. "
                "user_id: {self.pk} pix_id: {self.photo_id}"
            )

    def stripe_subscribe(self, stripe_plan_id: AnyStr, metadata: Dict = None) -> Dict:
        subscription = stripe.Subscription.create(
            customer=self.stripe_customer_token,
            items=[{"plan": stripe_plan_id}],
        )
        return subscription

    @property
    def firstname_lastname(self):
        return "{} {}".format(self.first_name, self.last_name)


@receiver(pre_delete, sender=User)
def user_pre_delete(instance, **kwargs):
    instance.delete_on_stripe()


@receiver(post_save, sender=User)
def user_post_save(instance: User, **kwargs):
    if kwargs.get("created"):
        profile = instance.create_user_profile()
        if profile is not None:
            if profile.photo is not None:
                profile.restore_photo_ownership()


class ProfileBase(models.Model):
    phone = models.CharField(max_length=16, null=True, blank=True)
    city = models.CharField(max_length=32, null=True, blank=True)
    country = models.ForeignKey(
        "tags.Country",
        on_delete=models.PROTECT,
        related_name="%(class)s_country_profiles",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    review_comments = models.TextField(null=True, blank=True)
    is_public = models.BooleanField(default=False)
    disable_emails = models.BooleanField(default=False)

    class Meta:
        abstract = True

    @property
    def country_name(self):
        try:
            return self.country.name
        except AttributeError:
            pass

    @property
    def hubspot_industries(self):
        _list = []
        for x in self.industries.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return ",".join(_list)

    @property
    def industries_name(self):
        _list = []
        for x in self.industries.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return _list

    @property
    def hubspot_tools(self):
        _list = []
        for x in self.tools.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return ",".join(_list)

    @property
    def tools_name(self):
        _list = []
        for x in self.tools.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return _list

    def is_ready_for_approval(self) -> bool:
        """
        Originally issue zenhub: #185 ready for approval email
        """
        for field in self.approval_fields:
            field_value = getattr(self, field)
            if (
                field == "language_levels" and not field_value or field_value == "[]"
            ):  # dirty hack
                return False
            elif hasattr(field_value, "all") and not field_value.exists():
                return False
            elif not field_value:
                return False
        return True

    def confirm_review(self):
        self.is_reviewed = True
        profile_type = self.profile_type

        if self.profile_type == "freelancer":
            template_name = "Freelancer Default Account Approval"
            subject = "You’re approved. Get ready for Project!"
            sender_name = settings.FREELANCER_MEMBER_FROM_NAME
        elif self.profile_type == "adviser":
            template_name = "Expert profile live"
            subject = "Your advisor profile live!"
            sender_name = settings.MEMBER_FROM_NAME
        else:
            sender_name = settings.CLIENT_MEMBER_FROM_NAME
            if self.entry_point_type == "Playbook":
                template_name = "Client Playbook Account Approval"
                subject = (
                    "Je account is goedgekeurd. Klaar voor Marketing as a Service?"
                )
            elif self.entry_point_type == "FlexTeam":
                template_name = "Client FlexTeam Account Approval"
                subject = "Your account is approved. Ready for Marketing as a Service?"
            else:
                template_name = "Client Default Account Approval"
                subject = "Your account is approved. Ready for Marketing as a Service?"

        self.send_email(
            template_name,
            {
                "LOGIN_LINK": settings.LOGIN_LINK,
                "PROFILE_LINK": settings.PROFILE_LINK,
                "USER_FIRST_NAME": self.first_name,
            },
            subject,
            sender_name=sender_name,
        )

        return self.save(update_fields=["is_reviewed"])

    def update_playbook_tour(self):
        self.show_playbook_tour = False

        return self.save(update_fields=["show_playbook_tour"])

    def update_planner_tour(self):
        self.show_planner_tour = False

        return self.save(update_fields=["show_planner_tour"])

    def send_review_email(self):
        return self.send_email(
            "Profile review comments",
            {"REVIEW_COMMENTS": self.review_comments, "APP_URL": settings.APP_URL},
            "Profile review comments",
        )


class ProfileBaseDraftMixin(models.Model):
    """
    That's a draft model.
    Common profile fields for all types of profiles
    """

    phone = models.CharField(max_length=16, null=True, blank=True)
    city = models.CharField(max_length=32, null=True, blank=True)
    country = models.ForeignKey(
        "tags.Country",
        on_delete=models.PROTECT,
        related_name="%(class)s_country_profiles",
        null=True,
        blank=True,
    )

    photo = models.ForeignKey(
        "pix.Picture",
        on_delete=models.CASCADE,
        limit_choices_to={"context": "profile"},
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True


class ClientProfile(User, ProfileBase):
    has_marketers = models.BooleanField(default=False)
    has_changed_packages_subscription = models.BooleanField(default=False)
    has_changed_flex_team_subscription = models.BooleanField(default=False)
    has_changed_freelancer_subscription = models.BooleanField(default=False)
    is_free_subscription = models.BooleanField(default=False)
    works_with_marketing_agency = models.BooleanField(default=False)
    job_title = models.CharField(max_length=255, null=True, blank=True)
    flexteam_briefing = JSONField(default=dict, encoder=DjangoJSONEncoder, blank=True)
    is_ideal_enabled = models.BooleanField(default=True)
    is_credit_card_enabled = models.BooleanField(default=True)
    subscription = models.ManyToManyField(TierSubscription)
    show_playbook_tour = models.BooleanField(default=True)
    show_planner_tour = models.BooleanField(default=True)
    show_planner_card = models.BooleanField(default=True)
    show_wishlist_card = models.BooleanField(default=True)
    show_highlight_message = models.BooleanField(default=True)
    is_offline_invoice_enabled = models.BooleanField(default=False)
    projects_spendings_amount = MoneyField(default=Decimal(0.0))
    billing_name = models.TextField(blank=True, null=True)
    billing_email = models.EmailField(unique=True, null=True, blank=True)
    billing_phone = models.CharField(max_length=16, null=True, blank=True)
    billing_city = models.CharField(max_length=32, null=True, blank=True)
    billing_country = models.ForeignKey(
        "tags.Country",
        on_delete=models.PROTECT,
        related_name="%(class)s_billing_country",
        null=True,
        blank=True,
    )
    billing_address_1 = models.CharField(max_length=50, blank=True, null=True)
    billing_address_2 = models.CharField(max_length=50, blank=True, null=True)
    billing_postal = models.CharField(max_length=32, null=True, blank=True)
    billing_state = models.CharField(max_length=32, null=True, blank=True)
    billing_tax = models.ForeignKey(
        "tags.BillingTax",
        blank=True,
        null=True,
        related_name="%(class)s_billing_tax",
        on_delete=models.PROTECT,
    )
    stripe_tax_id = models.CharField(max_length=32, null=True, blank=True)
    stripe_tax_value = models.CharField(max_length=50, null=True, blank=True)
    billing_kvk = models.CharField(
        max_length=8,
        validators=[
            RegexValidator(
                regex="^[0-9]{8}$",
                message="Value does not match format xxxxxxxx, where x is a digit.",
                code="nomatch",
            )
        ],
        null=True,
        blank=True,
    )
    can_post_a_project = models.BooleanField(default=False)

    approval_fields = (
        "photo",
        "first_name",
        "last_name",
        "company",
        "job_title",
        "country",
        "city",
        "phone",
        "industries",
        "marketing_goals",
        "marketing_expertise",
        "tools",
    )

    @property
    def current_period_spendings(self) -> "payment.Spendings":
        return self.spendings.latest("period")

    def track_projects_spendings(self, amount):
        status = ClientProfile.objects.filter(pk=self.pk).update(
            projects_spendings_amount=models.F("projects_spendings_amount") + amount
        )
        if status:
            return True
        else:
            # could not add spendings amount for some reason
            logger.critical(
                f"Can't add projects spendings for {self.uuid} amount: {amount}"
            )
            return False

    @property
    def hubspot_marketing_goals(self):
        _list = []
        for x in self.marketing_goals.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return ",".join(_list)

    @property
    def hubspot_marketing_experience(self):
        _list = []
        for x in self.marketing_expertise.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return ",".join(_list)

    @property
    def hubspot_marketing_agency_types(self):
        _list = []
        for x in self.marketing_agency_types.all():
            try:
                _list.append(x.name)
            except AttributeError:
                pass
        return ",".join(_list)


class ClientProfileDraft(DraftBase, ProfileBaseDraftMixin):
    has_marketers = models.BooleanField(default=False, null=True, blank=True)
    works_with_marketing_agency = models.BooleanField(
        default=False, null=True, blank=True
    )
    job_title = models.CharField(max_length=255, null=True, blank=True)
    industries = models.ManyToManyField("tags.Industry", blank=True)
    tools = models.ManyToManyField("tags.Tool", blank=True)
    marketing_goals = models.ManyToManyField("tags.MarketingGoal", blank=True)
    marketing_expertise = models.ManyToManyField("tags.MarketingExpertise", blank=True)
    marketing_agency_types = models.ManyToManyField(
        "tags.MarketingAgencyType", blank=True
    )




class TokenUser(object):
    """
    TODO: move this class to a separate module
    A dummy user class modeled after django.contrib.auth.models.AnonymousUser.
    Used in conjunction with the `JWTTokenUserAuthentication` backend to
    implement single sign-on functionality across services which share the same
    secret key.  `JWTTokenUserAuthentication` will return an instance of this
    class instead of a `User` model instance.  Instances of this class act as
    stateless user objects which are backed by validated tokens.
    """

    username = ""

    # User is always active since Simple JWT will never issue a token for an
    # inactive user
    is_active = True

    _groups = EmptyManager(auth_models.Group)
    _user_permissions = EmptyManager(auth_models.Permission)

    def __init__(self, token):
        self.token = token

    def __str__(self):
        return "TokenUser {}".format(self.id)

    @cached_property
    def id(self):
        return self.token[api_settings.USER_ID_CLAIM]

    @cached_property
    def pk(self):
        return self.id

    @cached_property
    def is_staff(self):
        return self.token.get("is_staff", False)

    @cached_property
    def is_superuser(self):
        return self.token.get("is_superuser", False)

    @cached_property
    def profile_type(self):
        return self.token.get("profile_type")

    @cached_property
    def uuid(self):
        return self.token.get("user_uuid")

    def __eq__(self, other):
        return self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.id)

    def save(self):
        raise NotImplementedError("Token users have no DB representation")

    def delete(self):
        raise NotImplementedError("Token users have no DB representation")

    def set_password(self, raw_password):
        raise NotImplementedError("Token users have no DB representation")

    def check_password(self, raw_password):
        raise NotImplementedError("Token users have no DB representation")

    @property
    def groups(self):
        return self._groups

    @property
    def user_permissions(self):
        return self._user_permissions

    def get_group_permissions(self, obj=None):
        return set()

    def get_all_permissions(self, obj=None):
        return set()

    def has_perm(self, perm, obj=None):
        return False

    def has_perms(self, perm_list, obj=None):
        return False

    def has_module_perms(self, module):
        return False

    @property
    def is_anonymous(self):
        return CallableFalse

    @property
    def is_authenticated(self):
        return CallableTrue

    def get_username(self):
        return self.username

    def fetch(self):
        return User.objects.get(uuid=self.uuid)


def notify_new_profile(user_profile):
    reverse_str = f"admin:auth_{user_profile._meta.model_name}_change"
    profile_url = django_reverse(reverse_str, args=[user_profile.id])
    profile_url = urljoin(settings.ADMIN_URL, profile_url)
    body = render_to_string(
        "profiles/new_profile_notification.html", {"profile_url": profile_url}
    )

    delay = not settings.IS_UNDER_TEST and settings.RQ_DELAY
    if delay:
        email_send_plain.delay(
            settings.PROFILE_NOTIFICATION_SUBJECT,
            settings.NOTIFICATION_EMAIL_RECIPIENT,
            body,
        )
    else:
        email_send_plain(
            settings.PROFILE_NOTIFICATION_SUBJECT,
            settings.NOTIFICATION_EMAIL_RECIPIENT,
            body,
        )

@receiver(post_save, sender=ClientProfile)
def profile_post_save(instance, **kwargs):
    try :
        export_map = {
            ClientProfile: export_contacts_client,
        }

        export_function = export_map[kwargs["sender"]]
        data = export_function(instance)
        if settings.HUBSPOT_API_KEY:
            delay = not settings.IS_UNDER_TEST and settings.RQ_DELAY
            if delay:
                create_or_update_hubspot_contact.delay(email=instance.email, data=data)
            else:
                create_or_update_hubspot_contact(email=instance.email, data=data)
    except Exception as e:
        print("error", e)

    if kwargs.get("created"):
        sender_name = settings.CLIENT_MEMBER_FROM_NAME
        if instance.entry_point_type == "Playbook":
            template_name = "Client Playbook Account Creation"
            subject = (
                f"Alsjeblieft {instance.first_name}, hier is je marketing Playbook!"
            )
        elif instance.entry_point_type == "FlexTeam":
            template_name = "Client FlexTeam Account Creation"
            subject = "Thank you for joining our project"
        else:
            template_name = "Client Default Account Creation"
            subject = "Thank you for joining our project!"

        instance.send_email(
            template_name,
            {
                "COMPLETE_YOUR_PROFILE": f"{settings.APP_URL}/profile/edit",
                "USER_FIRST_NAME": instance.first_name,
            },
            subject,
            sender_name=sender_name,
        )

        notify_new_profile(instance)

    if not instance.is_reviewed and instance.is_ready_for_approval():
        subject = "User has completed their profile"
        django_admin_url = django_reverse(
            f"admin:auth_{instance._meta.model_name}_change", args=[instance.id]
        )

        email_send_plain(
            subject,
            settings.NOTIFICATION_EMAIL_RECIPIENT,
            f"The {instance.profile_type} {instance.first_name} {instance.last_name} "
            f"has completed their profile and awaiting review and "
            f"approval {settings.ADMIN_URL}{django_admin_url}",
        )

