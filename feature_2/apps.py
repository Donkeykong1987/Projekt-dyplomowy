from django.apps import AppConfig


class SystemRejestracjiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'system_rejestracji'
    def ready(self):
        import system_rejestracji.signals