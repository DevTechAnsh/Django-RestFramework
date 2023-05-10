from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from auth.models import User


class Command(BaseCommand):
    help = 'Remove stripe customer token of the users'

    def handle(self, *args, **kwargs):
        all_users = User.objects.all()
        for user in all_users:
            if user.stripe_customer_token is not None:
                user.stripe_customer_token = None
                user.save()

        self.stdout.write("Removed the stripe customer token of the users")