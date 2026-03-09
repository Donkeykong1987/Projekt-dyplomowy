from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Klient

@receiver(post_delete, sender=Klient)
def delete_user_when_client_deleted(sender, instance, **kwargs):
    """
    Usuwa powiązanego Usera, gdy usuwany jest Klient.
    """
    if instance.user:
        instance.user.delete()
