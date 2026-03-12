from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

@shared_task
def send_admin_email(subject, message):
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.ADMIN_EMAIL],
        fail_silently=False,
    )
    
@shared_task
def send_visit_reminder_email(email, username, visit_date, visit_time):

    subject = "Przypomnienie o wizycie"

    message = (
        f"Dzień dobry {username},\n\n"
        f"Przypominamy o wizycie zaplanowanej na:\n"
        f"Data: {visit_date}\n"
        f"Godzina: {visit_time}\n\n"
        "W razie potrzeby możesz anulować wizytę w systemie."
    )

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )