from django.contrib import admin

from . import models


@admin.register(models.Membership)
class MembershipModelAdmin(admin.ModelAdmin):

    list_display = ["name", "profile_type"]
