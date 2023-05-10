from auth.models import User
from rest_framework.permissions import BasePermission


class PermissionMixin:
    def has_permission(self, request, view):
        permission = super().has_permission(request, view)
        try:
            user = request.user.fetch()
        except (User.DoesNotExist, AttributeError):
            # AttributeError: 'AnonymousUser' object has no attribute 'fetch'
            return False

        return permission and user.is_reviewed


class ProfileTypePermission(BasePermission):
    profile_type = None

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.profile_type == self.profile_type
        )


class AdminPermission(ProfileTypePermission):
    profile_type = ""

    def has_permission(self, request, view):
        from django.contrib.auth import get_user

        user = get_user(request)
        if not user:
            return False

        return (
            user.is_authenticated
            and user.profile_type == self.profile_type
            and user.is_reviewed
            and user.is_staff
            and user.is_active
        )


class ClientPermission(ProfileTypePermission):
    profile_type = "client"


class ClientPermissionReviewed(PermissionMixin, ClientPermission):
    pass


class FreelancerPermission(ProfileTypePermission):
    profile_type = "freelancer"


class FreelancerPermissionReviewed(PermissionMixin, FreelancerPermission):
    pass


class AdviserPermission(ProfileTypePermission):
    profile_type = "adviser"


class AdviserOrFreelancerPermission(ProfileTypePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.profile_type in ("adviser", "freelancer")
        )


class IsReviewedPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        # check that user is valid
        try:
            user = request.user.fetch()
            return user.is_reviewed
        except User.DoesNotExist:
            return False
