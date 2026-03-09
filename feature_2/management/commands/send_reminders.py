from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.core.mail import send_mail
from datetime import timedelta

from system_rejestracji.models import Wizyta


class Command(BaseCommand):

    def handle(self, *args, **kwargs):

        target = now() + timedelta(hours=24)

        visits = Wizyta.objects.filter(
            start__range=(target - timedelta(minutes=30),
                           target + timedelta(minutes=30)),
            status="potwierdzona"
        )

        for v in visits:

            email = v.klient.email

            if not email:
                continue

            send_mail(
                subject="Przypomnienie o wizycie",
                message=(
                    f"Przypomnienie o wizycie:\n"
                    f"{v.start.strftime('%d.%m.%Y %H:%M')}"
                ),
                from_email=None,
                recipient_list=[email],
            )

            self.stdout.write(f"Wysłano do {email}")
