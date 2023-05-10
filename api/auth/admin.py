from functools import update_wrapper

from django.conf import settings as s
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.forms.models import BaseInlineFormSet
from django.shortcuts import redirect
from django.urls import re_path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from auth import models
from auth.utils import subscribe_to_mailchimp
from events.models import UserEvent
from tiers.models import TierClient


class LanguageLevelAdminMixin:
    readonly_fields = ("language_levels_verbose",)

    def language_levels_verbose(self, obj):
        return obj.get_language_levels_data()


class PhotoOwnerMixin:
    def photo_verbose(self, obj):
        return format_html(
            '<img src="{}" style="max-width: 400px;"/>', obj.photo.file.url
        )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        return readonly_fields + ("photo_verbose",)


class DraftInline(PhotoOwnerMixin, admin.StackedInline):
    extra = 0
    can_delete = False
    exclude = ("language_levels", "photo")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ClientDraftInline(DraftInline):
    model = models.ClientProfileDraft


class FreelancerDraftInline(LanguageLevelAdminMixin, DraftInline):
    model = models.FreelancerProfileDraft


class AdviserDraftInline(LanguageLevelAdminMixin, DraftInline):
    model = models.AdviserProfileDraft


class LimitModelFormSet(BaseInlineFormSet):
    LIMIT = 100

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _kwargs = {self.fk.name: kwargs["instance"]}
        self.queryset = kwargs["queryset"].filter(**_kwargs)[: self.LIMIT]


class UserEventInline(admin.StackedInline):
    model = UserEvent
    readonly_fields = [
        "body",
        "event_type",
        "needs_admin_attention",
        "created_at",
    ]
    ordering = ["-created_at"]
    formset = LimitModelFormSet

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.User)
class UserModelAdmin(admin.ModelAdmin):
    exclude = ("password", "last_refresh_token", "login_as_token")
    list_display = (
        "email",
        "profile_type",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
        "last_login",
    )
    readonly_fields = ("profile_type", "date_joined", "last_login", "company")

    inlines = [
        ClientDraftInline,
        FreelancerDraftInline,
        AdviserDraftInline,
        UserEventInline,
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(
            clientprofile=None, freelancerprofile=None, adviserprofile=None
        )


def mark_has_comet_chat_account_false(modeladmin, request, queryset):
    queryset.update(has_comet_chat_account=False)


mark_has_comet_chat_account_false.short_description = (
    "Mark has comet chat account false"
)


class ProfileBaseModelAdmin(PhotoOwnerMixin, admin.ModelAdmin):
    exclude = ("photo", "is_profile_completed") + UserModelAdmin.exclude
    readonly_fields = UserModelAdmin.readonly_fields + (
        "is_reviewed",
        "is_email_confirmed",
    )
    list_display = (
        "email",
        "profile_type",
        "is_reviewed",
        "is_active",
        "has_comet_chat_account",
        "is_staff",
        "is_superuser",
        "disable_emails",
        "date_joined",
        "login_as_custom",
    )
    search_fields = ["email", "first_name", "last_name"]

    actions = [
        mark_has_comet_chat_account_false,
    ]

    change_form_template = "admin/profileconfirm_changeform.html"

    inlines = [UserEventInline]

    def login_as_custom(self, obj):
        if not obj.is_reviewed:
            return "(not reviewed)"
        if not obj.is_active:
            return "(not active)"

        model_name = self.model._meta.model_name
        url = reverse(f"admin:auth_{model_name}_login_as", args=[obj.id])
        return format_html(
            f'<a class="button" href="{url}" '
            f"onclick=\"return confirm('Are you sure you want to login as "
            f"{obj.email} ?')\">Login as {obj.email}</a>"
        )

    login_as_custom.short_description = "Login As"

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            wrapper.model_admin = self
            return update_wrapper(wrapper, view)

        urls = super().get_urls()
        model_name = self.model._meta.model_name
        custom_urls = [
            re_path(
                r"confirm/(\d+)$",
                wrap(self.confirm),
                name="auth_{}_confirm".format(model_name),
            ),
            re_path(
                r"email-review/(\d+)$",
                wrap(self.email_review),
                name="auth_{}_email_review".format(model_name),
            ),
            re_path(
                r"login-as/(\d+)$",
                wrap(self.login_as),
                name="auth_{}_login_as".format(model_name),
            ),
        ]
        return urls + custom_urls

    def render_change_form(self, request, context, *args, **kwargs):
        model_name = self.model._meta.model_name
        context["obj"] = kwargs["obj"]
        context[
            "email_review_url_pattern_name"
        ] = f"admin:auth_{model_name}_email_review"
        context["confirm_url_pattern_name"] = f"admin:auth_{model_name}_confirm"
        return super().render_change_form(request, context, *args, **kwargs)

    @method_decorator(staff_member_required)
    def confirm(self, request, object_id):
        obj: models.ProfileBase = self.get_object(request, object_id)
        if obj.is_reviewed:
            messages.error(request, "This profile is already reviewed")
        else:
            obj.confirm_review()
            mailchimp_id = subscribe_to_mailchimp(obj)
            if mailchimp_id:
                obj.mailchimp_id = mailchimp_id
                obj.save()

        messages.info(request, "Profile has been marked as reviewed")

        return redirect(
            "admin:auth_{}_change".format(self.model._meta.model_name),
            object_id=object_id,
        )

    @method_decorator(staff_member_required)
    def email_review(self, request, object_id):
        model_name = self.get_object(request, object_id)._meta.model_name
        obj: models.ProfileBase = self.get_object(request, object_id)
        if obj.is_reviewed:
            messages.error(request, "This profile is already reviewed")
        elif obj.review_comments:
            obj.send_review_email()
        else:
            messages.error(request, "Cannot send email, review comments is empty")
        return redirect(
            "admin:auth_{}_change".format(model_name), object_id=object_id
        )

    @method_decorator(staff_member_required)
    def login_as(self, request, object_id):
        obj: models.User = self.get_object(request, object_id)
        token = obj.generate_login_as_token()
        return redirect(s.LOGIN_WITH_TOKEN_LINK.format(token))


class TiersClientAdmin(admin.TabularInline):
    model = TierClient


@admin.register(models.ClientProfile)
class ClientProfileModelAdmin(ProfileBaseModelAdmin):
    inlines = [
        TiersClientAdmin,
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        readonly_fields.remove("company")
        return readonly_fields

    def save_model(self, request, obj, form, change):
        if not any(
            [
                obj.is_ideal_enabled,
                obj.is_credit_card_enabled,
                obj.is_offline_invoice_enabled,
            ]
        ):
            messages.set_level(request, messages.ERROR)
            messages.error(request, "At least 1 Payment Method must be enabled.")
            return
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.FreelancerProfile)
class FreelancerProfileModelAdmin(ProfileBaseModelAdmin, LanguageLevelAdminMixin):
    exclude = ("language_levels", "company", *UserModelAdmin.exclude)
    readonly_fields = ("uuid",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.AdviserProfile)
class AdviserProfileModelAdmin(ProfileBaseModelAdmin, LanguageLevelAdminMixin):
    exclude = ("language_levels", "company", *UserModelAdmin.exclude)


@admin.register(models.BlackListedEmailDomain)
class BlackListedEmailDomainModelAdmin(admin.ModelAdmin):
    list_display = ("domain",)


@admin.register(models.ReferredSite)
class ReferredSiteListModelAdmin(admin.ModelAdmin):
    list_display = ("name",)
