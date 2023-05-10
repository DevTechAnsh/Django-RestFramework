import sys
import csv

from django.core.management.base import BaseCommand

from auth.models import User, ClientProfile, FreelancerProfile, AdviserProfile


def gen_user_data():
    known_emails = set()

    for profile_cls in [ClientProfile, FreelancerProfile, AdviserProfile]:
        for profile in profile_cls.objects.all():
            known_emails.add(profile.email)
            yield (profile.email, profile.profile_type, profile.first_name,
                   profile.last_name, profile.phone)

    for user in User.objects.all():
        if user.email not in known_emails:
            yield (user.email, user.profile_type, '', '', '')


class Command(BaseCommand):
    help = 'Generate a CSV with users'

    def handle(self, *args, **kwargs):
        writer = csv.writer(
            sys.stdout, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        for line in gen_user_data():
            writer.writerow(line)
