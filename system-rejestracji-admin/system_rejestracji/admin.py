from django.contrib import admin
from django.forms import ModelForm, SelectDateWidget
from datetime import date, timedelta, datetime
from .models import Klient, Wizyta
from schedule.models import Calendar
from django import forms
import openpyxl
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from django.http import HttpResponse
from django.urls import path
from django.template.response import TemplateResponse
from django.http import JsonResponse
from django.utils.timezone import make_aware, get_default_timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import localtime
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_datetime
from django.http import HttpResponseRedirect

def export_wizyty_xlsx(modeladmin, request, queryset):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Wizyty"

    headers = [
        "Klient",
        "Data",
        "Status",
        "Opłacona",
        "Kwota"
    ]
    ws.append(headers)

    for w in queryset:
        ws.append([
            str(w.klient),
            w.start.strftime("%Y-%m-%d"), #string format time
            w.status,
            "TAK" if w.wizyta_oplacona else "NIE",
            w.kwota,
        ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="wizyty.xlsx"'

    wb.save(response)
    return response

export_wizyty_xlsx.short_description = "📊 Eksport do Excela (XLSX)"

def export_wizyty_pdf(modeladmin, request, queryset):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="wizyty.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    elements = []

    data = [["Klient", "Data", "Status", "Opłacona"]]

    for w in queryset:
        data.append([
            str(w.klient),
            w.start.strftime("%Y-%m-%d"),
            w.start.strftime("%H:%M"),
            w.status,
            "TAK" if w.wizyta_oplacona else "NIE",
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]))

    elements.append(table)
    doc.build(elements)

    return response

export_wizyty_pdf.short_description = "📄 Eksport do PDF"

class KlientAdminForm(ModelForm):
    class Meta:
        model = Klient
        fields = "__all__"
        widgets = {
            "data_urodzenia": SelectDateWidget( #widget do rozwijanych list przy ustawieniu daty
                years=range(1920, date.today().year + 1)
            ),
        }

@admin.register(Klient)
class KlientAdmin(admin.ModelAdmin):
    list_display = ('nazwisko', 'imie', 'email', 'numer_telefonu', 'data_urodzenia',)
    search_fields = ('nazwisko', 'imie')
    form = KlientAdminForm

    def plik_dodany(self, obj):
        return bool(obj.plik)

    plik_dodany.boolean = True
    plik_dodany.short_description = "Plik załączony"

@method_decorator(csrf_exempt, name="dispatch")
@require_POST #akceptacja tylko i wyłącznie POST, dla GET, PUL, DELETE wywali błąd, jest to rodzaj zabezpieczenia
def calendar_update(self, request):
    import json

    data = json.loads(request.body)

    wizyta = Wizyta.objects.get(pk=data["id"])
    wizyta.start = make_aware(datetime.fromisoformat(data["start"])) #makeaware dla ustawienia strefy czasowej
    wizyta.end = make_aware(datetime.fromisoformat(data["end"]))
    wizyta.save()

    return JsonResponse({"status": "ok"})

class WizytaAdminForm(ModelForm):
    start_date = forms.DateField(
        widget=SelectDateWidget(years=range(2026, 2070)),
        label="Data wizyty"
    )
    start_hour = forms.ChoiceField(
        choices=[(h, f"{h:02d}") for h in range(7, 22)],
        label="Godzina"
    )
    start_minute = forms.ChoiceField(
        choices=[(m, f"{m:02d}") for m in range(0, 60, 5)],
        label="Minuta"
    )
    czas_trwania = forms.ChoiceField(
        choices=[(50, "50 minut"), (55, "55 minut")],
        label="Czas trwania",
        initial=50
    )

    class Meta:
        model = Wizyta
        fields = ("klient", "title", "description", "status", "zalacznik", "wizyta_oplacona", "kwota")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.start:
            start = self.instance.start
            start = localtime(start)  # konwertujemy na lokalny czas
            self.fields["start_date"].initial = start.date()
            self.fields["start_hour"].initial = start.hour
            self.fields["start_minute"].initial = start.minute
            if self.instance.end:
                duration = int((self.instance.end - self.instance.start).total_seconds() / 60)
                self.fields["czas_trwania"].initial = duration

    def clean(self): #walidacja kalendarza: ułożenie dat i godzin z kalendarza, liczy ile trwa wizyta, sprawdzenie kolizji
        cleaned_data = super().clean()
        date = cleaned_data.get("start_date")
        hour = int(cleaned_data.get("start_hour", 0))
        minute = int(cleaned_data.get("start_minute", 0))
        duration = int(cleaned_data.get("czas_trwania", 50))

        if date is None:
            raise forms.ValidationError("Wybierz datę wizyty.")

        start = datetime.combine(date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
        end = start + timedelta(minutes=duration)

        calendar = Calendar.objects.first() #pobranie jedynego kalendarza
        if not calendar:
            raise forms.ValidationError("Nie znaleziono kalendarza!")

        overlapping = Wizyta.objects.filter( #zabezpieczenie przed wpisaniem więcej niż jedenj wizyty w tym samym czasie
            calendar=calendar,
            start__lt=end,
            end__gt=start
        )
        if self.instance.pk:
            overlapping = overlapping.exclude(pk=self.instance.pk)

        if overlapping.exists():
            raise forms.ValidationError("Ten termin jest już zajęty.")

        # zapisujemy do instancji
        self.instance.start = make_aware(start)
        self.instance.end = make_aware(end)
        self.instance.calendar = calendar

        return cleaned_data

@admin.register(Wizyta)
class WizytaAdmin(admin.ModelAdmin):
    form = WizytaAdminForm
    list_display = ("klient", "start_local", "status", "zalacznik_pokaz", "wizyta_oplacona", "kwota")
    list_filter = ("status", "start")
    search_fields = ("klient__imie", "klient__nazwisko", "title")
    ordering = ("start",)
    change_list_template = "admin/wizyta_changelist.html"
    actions = [export_wizyty_xlsx, export_wizyty_pdf]
    
    def start_local(self, obj): #tworzy czytelnie sformatowaną kolumne z datą i godziną
        return localtime(obj.start).strftime("%Y-%m-%d %H:%M")
    start_local.admin_order_field = "start"
    start_local.short_description = "Data i godzina"

    def save_model(self, request, obj, form, change): #automatycznie przypisuje użytkownika przy tworzeniu obiektu
        if not obj.pk and not obj.user_id:
            obj.user = request.user
        super().save_model(request, obj, form, change)

    def zalacznik_pokaz(self, obj): #zarządzanie załącznikiem
        return bool(obj.zalacznik)
    zalacznik_pokaz.boolean = True
    zalacznik_pokaz.short_description = "Załącznik?"

    def get_urls(self): #pobranie standardowych URLi, dodanie URLi odpowiadajacych za: widok kalendarza, pobranie wydarzeń oraz aktualizację wydarzeń
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path("kalendarz/", self.admin_site.admin_view(self.calendar_view), name="wizyta_kalendarz"),
            path("kalendarz/events/", self.admin_site.admin_view(self.calendar_events), name="wizyta_kalendarz_events"),
            path("kalendarz/update/", self.admin_site.admin_view(self.calendar_update), name="wizyta_kalendarz_update"),
        ]
        return custom_urls + urls

    def calendar_view(self, request): #odpowiada za główną stronę kalendarza w Admin
        from django.template.response import TemplateResponse
        context = dict(
            self.admin_site.each_context(request),
            title="Kalendarz wizyt",
        )
        return TemplateResponse(request, "admin/kalendarz_wizyt.html", context)

    def calendar_events(self, request): #pobranie wszystkich wizyt z bazy i wysłanie ich do front endu
        events = []
        for w in Wizyta.objects.all():
            if w.start and w.end:
                events.append({
                    "id": w.id,
                    "title": str(w.klient),
                    "start": localtime(w.start).strftime("%Y-%m-%dT%H:%M"),
                    "end": localtime(w.end).strftime("%Y-%m-%dT%H:%M"),
                    "color": w.color_event,
                    "extendedProps": {
                        "tooltip": f"{w.klient}\n{localtime(w.start):%H:%M}–{localtime(w.end):%H:%M}\n{w.get_status_display()}",
                        "edit_url": f"/admin/system_rejestracji/wizyta/{w.id}/change/",
                    },
                })
        return JsonResponse(events, safe=False)

    @csrf_exempt
    def calendar_update(self, request): #użyte do drag&drop w kalendarzu
        import json
        if request.method != "POST":
            return JsonResponse({"error": "Invalid method"}, status=400)

        data = json.loads(request.body)
        wizyta_id = data.get("id")
        start_str = data.get("start")
        end_str = data.get("end")

        wizyta = Wizyta.objects.get(pk=wizyta_id)

        start_dt = parse_datetime(start_str) #konwersja ISO string na obiekt datetime
        end_dt = parse_datetime(end_str)

        tz = get_default_timezone()
        if start_dt.tzinfo is None:
            start_dt = make_aware(start_dt, tz)
        if end_dt.tzinfo is None:
            end_dt = make_aware(end_dt, tz)

        wizyta.start = start_dt
        wizyta.end = end_dt
        wizyta.save()

        return JsonResponse({"status": "ok"})

    def get_changeform_initial_data(self, request): #pozwala dodać wizytę z poziomu front endowego kalendarza
        initial = super().get_changeform_initial_data(request)
        start_param = request.GET.get("start")
        if start_param:
            dt = parse_datetime(start_param)
            tz = get_default_timezone()
            if dt.tzinfo is None:
                dt = make_aware(dt, tz)
            dt = localtime(dt)
            initial["start_date"] = dt.date()
            initial["start_hour"] = dt.hour
            initial["start_minute"] = dt.minute
        return initial
    
    def response_post_save_change(self, request, obj): #po zmianie wizyty z poziomu kalendarza, wraca do kalendarza a nie do listy wizyt
        next_url = request.GET.get("next")
        if next_url:
            return HttpResponseRedirect(next_url)
        return super().response_post_save_change(request, obj)

   
    def response_post_save_add(self, request, obj, post_url_continue=None): #po dodani wizyty z poziomu kalendarza, wraca do kalendarza a nie do listy wizyt
        if "_continue" in request.POST or "_addanother" in request.POST:
            return super().response_post_save_add(request, obj, post_url_continue)
        
        from django.urls import reverse
        url = reverse("admin:system_rejestracji_wizyta_changelist")
        return HttpResponseRedirect(url)
