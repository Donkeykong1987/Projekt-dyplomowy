from django.db import models
from schedule.models import Event
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from datetime import timedelta, datetime
from schedule.models import Calendar

def get_default_calendar():
    #pobiera pierwszy istniejący kalendarz
    calendar = Calendar.objects.first()
    if not calendar:
        raise ValueError("Nie znaleziono żadnego kalendarza! Utwórz go w adminie.")
    return calendar

class Klient(models.Model):
    imie = models.CharField("Imię", max_length=100)
    nazwisko = models.CharField("Nazwisko", max_length=100, blank=True)
    email = models.EmailField(max_length=254, unique=True)
    numer_telefonu = models.CharField(max_length=20, blank=True, null=True, help_text="Np. 123 456 789")
    adres = models.CharField("Adres", max_length=200, blank=True, null=True)
    data_urodzenia = models.DateField("Data urodzenia", blank=True, null=True, help_text="DD-M-RRRR")
    bliska_osoba_do_kontaktu = models.CharField("Bliska osoba do kontaktu", max_length=100, blank=True, null=True)
    numer_osoby_do_kontaktu = models.CharField("Numer osoby do kontaktu", max_length=20, blank=True, null=True, help_text="Np. 123 456 789")
    plik = models.FileField("Plik", upload_to='files', null=True, blank=True)

    def __str__(self):
        return f"{self.imie} {self.nazwisko}"
    
    class Meta:
        verbose_name = "Klient"
        verbose_name_plural = "Klienci"

class Wizyta(Event):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wizyty"
    )
    klient = models.ForeignKey("Klient", on_delete=models.CASCADE, related_name="wizyty")
    status = models.CharField(
        max_length=20,
        choices=[
            ("potwierdzona", "Potwierdzona"),
            ("odbyta", "Odbyta"),
            ("anulowana", "Anulowana"),
        ],
        default="potwierdzona"
    )
    wizyta_oplacona = models.BooleanField("Wizyta opłacona", default=False)
    zalacznik = models.FileField(upload_to="wizyty/", blank=True, null=True)
    kwota = models.CharField("Kwota", max_length=10, blank=True, null=True)

    STATUS_KOLORY = {
        "potwierdzona": "#3498db",
        "odbyta": "#2ecc71",
        "anulowana": "#e74c3c",
    }

    TRWANIE_WIZYTY = timedelta(minutes=50)

    def clean(self):
        #pozostawione do ewentualnego dodatkowego walidowania poza kolizjami
        super().clean()

    def save(self, *args, **kwargs):
        
        #jeśli end nie ustawione, dodaj domyślny czas trwania
        if not self.pk and self.start and not self.end:
            self.end = self.start + (self.TRWANIE_WIZYTY if hasattr(self, 'TRWANIE_WIZYTY') else timedelta(minutes=50))

        #automatyczne przypisanie calendar
        if not self.pk and not self.calendar_id:
            self.calendar = Calendar.objects.first()
            if not self.calendar:
                raise ValueError("Nie znaleziono żadnego kalendarza! Utwórz go w adminie.")

        #sprawdzenie kolizji w tym kalendarzu
        if self.start and self.end and self.calendar_id:
            overlapping = Wizyta.objects.filter(
                calendar=self.calendar,
                start__lt=self.end,
                end__gt=self.start
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            if overlapping.exists():
                raise ValidationError("Ten termin jest już zajęty.")

        self.color_event = self.STATUS_KOLORY.get(self.status, "#3498db")

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Wizyta"
        verbose_name_plural = "Wizyty"

    def __str__(self):
        return f"{self.title} | {self.start:%Y-%m-%d %H:%M}"