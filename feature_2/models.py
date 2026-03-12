from django.db import models
from schedule.models import Event, Calendar
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.timezone import now, is_naive, make_aware
from datetime import timedelta
import holidays
import pytz
from django.utils import timezone
from pytz import timezone as pytz_timezone
from django.core.exceptions import NON_FIELD_ERRORS
from django.core.mail import send_mail
from system_rejestracji.tasks import send_admin_email


utc = pytz.UTC

def to_utc(dt, local_tz='Europe/Warsaw'):
   
    warsaw = pytz_timezone(local_tz)
 
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, warsaw)
    
    dt_utc = dt.astimezone(pytz_timezone('UTC'))
    return dt_utc


class Klient(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="klient"
    )

    imie = models.CharField("Imię", max_length=100)
    nazwisko = models.CharField("Nazwisko", max_length=100, blank=True)
    email = models.EmailField(unique=True)

    numer_telefonu = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    adres = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    data_urodzenia = models.DateField(
        blank=True,
        null=True
    )

    bliska_osoba_do_kontaktu = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    numer_osoby_do_kontaktu = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    plik = models.FileField(
        upload_to="files/",
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.imie} {self.nazwisko}"

    class Meta:
        verbose_name = "Klient"
        verbose_name_plural = "Klienci"


class Wizyta(Event):

    klient = models.ForeignKey(
        Klient,
        on_delete=models.CASCADE,
        related_name="wizyty",
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ("potwierdzona", "Potwierdzona"),
            ("odbyta", "Odbyta"),
            ("anulowana", "Anulowana"),
            ("zablokowana", "Zablokowana"),
        ],
        default="potwierdzona"
    )

    wizyta_oplacona = models.BooleanField(default=False)

    zalacznik = models.FileField(
        upload_to="wizyty/",
        blank=True,
        null=True
    )

    kwota = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )

    TRWANIE = timedelta(minutes=50)

    STATUS_KOLORY = {
        "potwierdzona": "#3498db",
        "odbyta": "#2ecc71",
        "anulowana": "#e74c3c",
        "zablokowana": "#34495e",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._previous_status = self.status

    def clean(self):

       
        # 0. Jeśli to BLOKADA — pomijamy walidację wizyt
        
        if self.status == "zablokowana":
            return
        
        # 1. Dotychczasowa walidacja wizyt (bez zmian)

        if not self.start or not self.end:
            return

        errors = {}
        warsaw = pytz_timezone('Europe/Warsaw')

        start = self.start
        end = self.end
        if timezone.is_naive(start):
            start = timezone.make_aware(start, warsaw)
        if timezone.is_naive(end):
            end = timezone.make_aware(end, warsaw)

        start_local = start.astimezone(warsaw)
        end_local = end.astimezone(warsaw)
        teraz = timezone.localtime(timezone.now(), warsaw)

        # 1. start < end
        if start_local >= end_local:
            errors["end"] = "Data zakończenia musi być po dacie rozpoczęcia."

        # 2. przeszłość – tylko dla nowych wizyt
        if start_local < teraz and not self.pk:
            errors[NON_FIELD_ERRORS] = "Nie można umawiać wizyty w przeszłości."

        # 3. weekend
        if start_local.weekday() >= 5:
            errors[NON_FIELD_ERRORS] = "Nie można umawiać wizyt w weekendy."

        # 4. święta
        pl_holidays = holidays.country_holidays("PL", years=start_local.year)
        if start_local.date() in pl_holidays:
            errors[NON_FIELD_ERRORS] = "Nie można umawiać wizyt w święta."

        # 5. godziny pracy 8–20
        if start_local.hour < 8 or start_local.hour > 19:
            errors[NON_FIELD_ERRORS] = "Wizyty można umawiać tylko między 8:00 a 20:00."

        # 6. najwcześniejszy termin = kolejny dzień roboczy
        kiedy_najwczesniej = teraz + timedelta(hours=24)
        if start_local < kiedy_najwczesniej and not self.pk:
            errors[NON_FIELD_ERRORS] = "Wizyta musi być umówiona co najmniej 24 godziny wcześniej."

        # 7. konflikt terminów
        overlapping = Wizyta.objects.filter(
            calendar=self.calendar,
            start__lt=end,
            end__gt=start,
        ).exclude(status__in=["anulowana", "zablokowana"])

        if self.pk:
            overlapping = overlapping.exclude(pk=self.pk)

        if overlapping.exists():
            errors[NON_FIELD_ERRORS] = "Ten termin jest już zajęty."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):

        warsaw = pytz.timezone('Europe/Warsaw')

        
        # 1. NORMALNE PRZETWARZANIE DAT
        
        if self.start:
            self.start = self.start.replace(minute=0, second=0, microsecond=0)

            if is_naive(self.start):
                self.start = make_aware(self.start, warsaw).astimezone(pytz.UTC)
            else:
                self.start = self.start.astimezone(pytz.UTC)

        if self.end:
            if is_naive(self.end):
                self.end = make_aware(self.end, warsaw).astimezone(pytz.UTC)
            else:
                self.end = self.end.astimezone(pytz.UTC)

        if self.start and not self.end:
            self.end = self.start + self.TRWANIE

        # 2. TYTUŁ WIZYTY / BLOKADY
        if self.status == "zablokowana":
            self.title = "Termin niedostępny"

        elif not self.title and self.klient:
            self.title = f"Wizyta - {self.klient.imie} {self.klient.nazwisko}"

        elif not self.title:
            self.title = "Wizyta"

        # 3. KALENDARZ
        if not self.calendar_id:
            calendar = Calendar.objects.first()
            if not calendar:
                raise ValidationError("Brak kalendarza w systemie.")
            self.calendar = calendar

        # 4. KOLOR
        self.color_event = self.STATUS_KOLORY.get(self.status, "#3498db")

        # 5. WALIDACJA:
        #    BLOKADY → POMIJAMY
        #    WIZYTY → WALIDUJEMY NORMALNIE
        if self.status != "zablokowana":
            self.full_clean()

        # 6. ZAPIS
        is_new = self.pk is None
        previous_status = None

        if not is_new:
            previous = Wizyta.objects.get(pk=self.pk)
            previous_status = previous.status

        super().save(*args, **kwargs)

        # POWIADOMIENIA MAILOWE 
        from system_rejestracji.tasks import send_admin_email
        warsaw = pytz.timezone("Europe/Warsaw")
        start_local = self.start.astimezone(warsaw)
        # ustal poprzedni status (z __init__)
        previous_status = getattr(self, "_previous_status", None)
        # 1. Powiadomienie o NOWEJ WIZYCIE — jeśli status zmienił się na "potwierdzona"
        if previous_status != "potwierdzona" and self.status == "potwierdzona":
            send_admin_email.delay(
                subject="Nowa wizyta została umówiona",
                message=(
                    "Nowa wizyta:\n\n"
                    f"Pacjent: {self.klient}\n"
                    f"Data: {start_local.strftime('%d.%m.%Y %H:%M')}\n"
                )
            )
        # Powiadomienie o ANULOWANIU WIZYTY — jeśli status zmienił się na "anulowana"
        if previous_status != "anulowana" and self.status == "anulowana":
            msg = (
                "Wizyta anulowana:\n\n"
                f"Pacjent: {self.klient}\n"
                f"Data: {start_local.strftime('%d.%m.%Y %H:%M')}\n"
            )
            send_admin_email.delay(
                subject="Wizyta została anulowana",
                message=msg
            )
        # 3. zapisz aktualny status jako poprzedni dla kolejnych zmian
        self._previous_status = self.status


    def __str__(self):
        return f"{self.klient} | {self.start:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Wizyta"
        verbose_name_plural = "Wizyty"
        ordering = ["start"]
    
    
