from django.contrib import admin
from django.forms import ModelForm, SelectDateWidget
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.template.response import TemplateResponse
from django.utils.timezone import localtime, make_aware, get_default_timezone, now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_datetime
from datetime import datetime, date, timedelta
from .models import Klient, Wizyta
from schedule.models import Calendar
from django import forms
import pytz
import openpyxl
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors


class BlockDateRangeForm(forms.Form):
    data_od = forms.DateField(label="Data od", widget=forms.SelectDateWidget)
    data_do = forms.DateField(label="Data do", widget=forms.SelectDateWidget)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("data_do") < cleaned.get("data_od"):
            raise forms.ValidationError("Data do nie może być wcześniejsza niż data od.")
        return cleaned

class KlientAdminForm(ModelForm):
    class Meta:
        model = Klient
        fields = "__all__"
        widgets = {
            "data_urodzenia": SelectDateWidget(years=range(1920, date.today().year + 1)),
        }

class WizytaAdminForm(ModelForm):
    start_date = forms.DateField(
        widget=SelectDateWidget(years=range(2026, 2070)),
        label="Data wizyty"
    )
    start_hour = forms.ChoiceField(
        choices=[(h, f"{h:02d}") for h in range(8, 20)],
        label="Godzina"
    )

    class Meta:
        model = Wizyta
        fields = ("klient", "title", "description", "status", "zalacznik", "wizyta_oplacona", "kwota")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = False
        if self.instance.pk and self.instance.start:
            start = localtime(self.instance.start)
            self.fields["start_date"].initial = start.date()
            self.fields["start_hour"].initial = start.hour

    def clean(self):
        cleaned_data = super().clean()
        date_val = cleaned_data.get("start_date")
        hour = int(cleaned_data.get("start_hour", 8))
        duration = 50

        if not date_val:
            raise forms.ValidationError("Wybierz datę wizyty.")

        start_naive = datetime.combine(date_val, datetime.min.time()) + timedelta(hours=hour)
        from django.utils import timezone
        start = timezone.make_aware(start_naive) if timezone.is_naive(start_naive) else start_naive
        end = start + timedelta(minutes=duration)

        # blokujemy tylko tworzenie NOWEJ wizyty w przeszłości
        if start < timezone.now() and not self.instance.pk:
            raise forms.ValidationError("Nie można umawiać wizyt z datą wsteczną.")
        # blokujemy umówienie wizyty w weekend
        if start.weekday() >= 5:
            raise forms.ValidationError("Nie można umawiać wizyt w weekendy.")

        calendar = Calendar.objects.first()
        if not calendar:
            raise forms.ValidationError("Nie znaleziono kalendarza!")

        overlapping = Wizyta.objects.filter(calendar=calendar, start__lt=end, end__gt=start)
        if self.instance.pk:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if overlapping.exists():
            raise forms.ValidationError("Ten termin jest już zajęty.")

        self.instance.start = start
        self.instance.end = end
        self.instance.calendar = calendar

        return cleaned_data


@admin.action(description="🔒 Zablokuj wybrane terminy")
def blokuj_sloty(modeladmin, request, queryset):
    for obj in queryset:
        obj.status = "zablokowana"
        obj.color_event = obj.STATUS_KOLORY["zablokowana"]
        obj.save()

# Eksport
def export_wizyty_xlsx(modeladmin, request, queryset):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Wizyty"
    ws.append(["Klient", "Data", "Status", "Opłacona", "Kwota"])
    for w in queryset:
        ws.append([str(w.klient), w.start.strftime("%Y-%m-%d"), w.status, "TAK" if w.wizyta_oplacona else "NIE", w.kwota])
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="wizyty.xlsx"'
    wb.save(response)
    return response
export_wizyty_xlsx.short_description = "📊 Eksport do Excela (XLSX)"

def export_wizyty_pdf(modeladmin, request, queryset):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="wizyty.pdf"'
    doc = SimpleDocTemplate(response, pagesize=A4)
    elements = []
    data = [["Klient", "Data", "Godzina", "Status", "Opłacona"]]
    for w in queryset:
        data.append([str(w.klient), w.start.strftime("%Y-%m-%d"), w.start.strftime("%H:%M"), w.status, "TAK" if w.wizyta_oplacona else "NIE"])
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

# Admin Klient
@admin.register(Klient)
class KlientAdmin(admin.ModelAdmin):
    list_display = ('nazwisko', 'imie', 'email', 'numer_telefonu', 'data_urodzenia')
    search_fields = ('nazwisko', 'imie')
    form = KlientAdminForm

# Admin Wizyta
@admin.register(Wizyta)
class WizytaAdmin(admin.ModelAdmin):
    form = WizytaAdminForm
    actions = [blokuj_sloty, export_wizyty_xlsx, export_wizyty_pdf]
    list_display = ("klient", "start_local", "status", "zalacznik_pokaz", "wizyta_oplacona", "kwota")
    list_filter = ("status", "start")
    search_fields = ("klient__imie", "klient__nazwisko", "title")
    ordering = ("start",)
    change_list_template = "admin/wizyta_changelist.html"

    def start_local(self, obj):
        return localtime(obj.start).strftime("%Y-%m-%d %H:%M")
    start_local.admin_order_field = "start"
    start_local.short_description = "Data i godzina"

    def zalacznik_pokaz(self, obj):
        return bool(obj.zalacznik)
    zalacznik_pokaz.boolean = True
    zalacznik_pokaz.short_description = "Załącznik?"

    def add_view(self, request, form_url='', extra_context=None):
        start_param = request.GET.get("start")
        if start_param:
            dt = parse_datetime(start_param)
            if dt:
                if dt.tzinfo is None:
                    dt = make_aware(dt, get_default_timezone())
                request._prepopulated_start = dt
        return super().add_view(request, form_url, extra_context)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not obj and hasattr(request, "_prepopulated_start"):
            initial = kwargs.get('initial', {})
            dt = request._prepopulated_start
            initial["start_date"] = dt.date()
            initial["start_hour"] = dt.hour
            kwargs['initial'] = initial
        return form

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        start_param = request.GET.get("start")
        if start_param:
            dt = parse_datetime(start_param)
            if dt:
                if dt.tzinfo is None:
                    dt = make_aware(dt, get_default_timezone())
                dt_local = localtime(dt)
                initial["start_date"] = dt_local.date()
                initial["start_hour"] = dt_local.hour
        return initial

    # Custom URLs (kalendarz i blokowanie)
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("kalendarz/", self.admin_site.admin_view(self.calendar_view), name="wizyta_kalendarz"),
            path("kalendarz/events/", self.admin_site.admin_view(self.calendar_events), name="wizyta_kalendarz_events"),
            path("kalendarz/update/", self.admin_site.admin_view(self.calendar_update), name="wizyta_kalendarz_update"),
            path("blokuj-daty/", self.admin_site.admin_view(self.block_date_range_view), name="wizyta_blokuj_daty"),
        ]
        return custom_urls + urls

    # Widok blokowania zakresu dat

    from django.template.response import TemplateResponse

    def block_date_range_view(self, request):
        if request.method == "POST":
            form = BlockDateRangeForm(request.POST)
            if form.is_valid():
                data_od = form.cleaned_data["data_od"]
                data_do = form.cleaned_data["data_do"]

                import pytz
                from datetime import datetime, timedelta

                warsaw = pytz.timezone("Europe/Warsaw")
                calendar = Calendar.objects.first()
                if not calendar:
                    self.message_user(request, "Brak kalendarza w systemie!", level="error")
                    return HttpResponseRedirect(request.get_full_path())

                start_local = datetime.combine(data_od, datetime.min.time()).replace(hour=8)
                start_local = warsaw.localize(start_local)

                end_local = datetime.combine(data_do, datetime.min.time()).replace(hour=20)
                end_local = warsaw.localize(end_local)

                start_utc = start_local.astimezone(pytz.UTC)
                end_utc = end_local.astimezone(pytz.UTC)

                conflict = Wizyta.objects.filter(
                    start__lt=end_utc,
                    end__gt=start_utc
                ).exclude(status="anulowana")

                if conflict.exists():
                    self.message_user(request, "Wybrany zakres koliduje z istniejącymi wizytami!", level="error")
                else:
                    Wizyta.objects.create(
                        klient=None,
                        title=f"Blokada: {data_od} – {data_do}",
                        start=start_utc,
                        end=end_utc,
                        status="zablokowana",
                        calendar=calendar
                    )
                    self.message_user(request, "Zakres został zablokowany.")

                return HttpResponseRedirect(request.get_full_path())
        else:
            form = BlockDateRangeForm()

        context = dict(self.admin_site.each_context(request), form=form, title="Blokuj zakres dat")
        return TemplateResponse(request, "admin/block_date_range.html", context)

    # Kalendarz
    def calendar_view(self, request):
        context = dict(self.admin_site.each_context(request), title="Kalendarz wizyt")
        return TemplateResponse(request, "admin/kalendarz_wizyt.html", context)

    def calendar_events(self, request):
        events = []

        for w in Wizyta.objects.all():
            if w.start and w.end:

                color = w.STATUS_KOLORY.get(w.status, "#3498db")

                if w.status == "zablokowana":
                    title = "Zablokowany termin"
                elif w.status == "anulowana":
                    title = f"Anulowana - {w.klient}"
                elif w.status == "odbyta":
                    title = f"Odbyta - {w.klient}"
                else:
                    title = f"Potwierdzona - {w.klient}"

                events.append({
                    "id": w.id,
                    "title": title,
                    "start": localtime(w.start).strftime("%Y-%m-%dT%H:%M"),
                    "end": localtime(w.end).strftime("%Y-%m-%dT%H:%M"),
                    "color": color,
                    "extendedProps": {
                        "edit_url": f"/admin/system_rejestracji/wizyta/{w.id}/change/",
                    },
                })

        return JsonResponse(events, safe=False)

    @csrf_exempt
    @require_POST
    def calendar_update(self, request):
        import json
        data = json.loads(request.body)
        wizyta_id = data.get("id")
        start_dt = parse_datetime(data.get("start"))
        end_dt = parse_datetime(data.get("end"))

        tz = get_default_timezone()
        if start_dt.tzinfo is None:
            start_dt = make_aware(start_dt, tz)
        if end_dt.tzinfo is None:
            end_dt = make_aware(end_dt, tz)

        wizyta = Wizyta.objects.get(pk=wizyta_id)
        wizyta.start = start_dt
        wizyta.end = end_dt
        wizyta.save()
        return JsonResponse({"status": "ok"})
