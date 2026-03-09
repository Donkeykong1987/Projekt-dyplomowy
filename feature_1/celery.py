from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# ustawienia Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "registration_system.settings")

# utworzenie instancji Celery
app = Celery("registration_system")

# pobranie ustawień z Django
app.config_from_object("django.conf:settings", namespace="CELERY")

# automatyczne wykrywanie tasków w aplikacjach
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f"Task: {self.request!r}")