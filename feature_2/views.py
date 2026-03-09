from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.http import JsonResponse
from django.utils.timezone import make_aware, is_naive, now, localtime
from datetime import date, timedelta
from django.utils.dateparse import parse_datetime
from datetime import datetime, timedelta, time
import json
from django.utils import timezone
import holidays
from django.contrib.auth.models import User
from .forms import RegisterForm
from .models import Wizyta, Klient, to_utc
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from schedule.models import Calendar
from pytz import timezone as pytz_timezone
import pytz
from .tasks import send_admin_email
from .tasks import send_visit_reminder_email

def to_utc(dt, local_tz='Europe/Warsaw'):
    """
    Konwertuje naive lub lokalny aware datetime na UTC.
    """
    warsaw = pytz.timezone(local_tz)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, warsaw)
    return dt.astimezone(pytz.UTC)
# REJESTRACJA


def register_view(request):

    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():

            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
                email=form.cleaned_data["email"]
            )

            Klient.objects.create(
                user=user,
                imie=form.cleaned_data["imie"],
                nazwisko=form.cleaned_data["nazwisko"],
                email=form.cleaned_data["email"]
            )

            login(request, user)

            return redirect("my_visits")

    else:
        form = RegisterForm()

    return render(
        request,
        "system_rejestracji/register.html",
        {"form": form}
    )


# PROFIL

@login_required
def profile_view(request):
    klient, created = Klient.objects.get_or_create(user=request.user, defaults={
        "imie": request.user.first_name,
        "nazwisko": request.user.last_name,
        "email": request.user.email
    })

    profile_fields = [
        {"field": "email", "label": "Email", "value": klient.email, "type": "email"},
        {"field": "numer_telefonu", "label": "Telefon", "value": klient.numer_telefonu, "type": "text"},
        {"field": "bliska_osoba_do_kontaktu", "label": "Osoba kontaktowa", "value": klient.bliska_osoba_do_kontaktu, "type": "text"},
        {"field": "numer_osoby_do_kontaktu", "label": "Nr osoby kontaktowej", "value": klient.numer_osoby_do_kontaktu, "type": "text"},
        {"field": "adres", "label": "Adres", "value": klient.adres, "type": "text"},
        {"field": "data_urodzenia", "label": "Data urodzenia", "value": klient.data_urodzenia, "type": "date"},
    ]

    return render(request, "system_rejestracji/profile.html", {
        "klient": klient,
        "user": request.user,
        "profile_fields": profile_fields
    })


@login_required
def update_profile_field(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)

    field = request.POST.get("field")
    value = request.POST.get("value")

    klient = Klient.objects.get(user=request.user)

    allowed_fields = [
        "email",
        "numer_telefonu",
        "bliska_osoba_do_kontaktu",
        "numer_osoby_do_kontaktu",
        "adres",
        "data_urodzenia",
    ]

    if field not in allowed_fields:
        return JsonResponse({"error": "Field not allowed"}, status=403)

    # obsługa daty
    if field == "data_urodzenia":
        if value == "":
            setattr(klient, field, None)
        else:
            try:
                from datetime import datetime
                setattr(klient, field, datetime.strptime(value, "%Y-%m-%d").date())
            except ValueError:
                return JsonResponse({"error": "Niepoprawny format daty"}, status=400)
    else:
        setattr(klient, field, value)

    klient.save()
    return JsonResponse({"success": True})


@login_required
@csrf_exempt
def update_visit(request, visit_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)

    import json
    from datetime import datetime, timedelta

    try:
        data = json.loads(request.body)
        start_local = datetime.fromisoformat(data["start"])
        end_local = datetime.fromisoformat(data["end"])

        start = to_utc(start_local)
        end = to_utc(end_local)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    klient = Klient.objects.get(user=request.user)
    wizyta = get_object_or_404(Wizyta, id=visit_id, klient=klient)

    conflict = Wizyta.objects.exclude(status="anulowana").filter(
        start__lt=end,
        end__gt=start
    ).exclude(id=wizyta.id)

    wizyta.start = start
    wizyta.end = end
    try:
        wizyta.save()
    except ValidationError as e:
        return JsonResponse({"error": e.message_dict}, status=400)

    return JsonResponse({"status": "ok"})

# MOJE WIZYTY
@login_required
def my_visits(request):
    klient, created = Klient.objects.get_or_create(user=request.user)

    # aktualizacja statusów przeszłych wizyt
    for w in Wizyta.objects.filter(klient=klient, status="potwierdzona", end__lt=timezone.now()):
        w.status = "odbyta"
        w.save()

    wizyty = Wizyta.objects.filter(
        klient=klient
    ).exclude(status="zablokowana").order_by("-start")

    # konwertujemy daty na czas lokalny
    for w in wizyty:
        w.start_local = timezone.localtime(w.start)
        w.end_local = timezone.localtime(w.end)

    # grupowanie po statusach
    grouped = {
        "potwierdzone": [w for w in wizyty if w.status == "potwierdzona"],
        "odbyte": [w for w in wizyty if w.status == "odbyta"],
        "anulowane": [w for w in wizyty if w.status == "anulowana"],
    }

    return render(request, "system_rejestracji/my_visits.html", {
        "grouped": grouped
    })


# KALENDARZ

@login_required
def user_calendar(request):
    klient = get_object_or_404(Klient, user=request.user)
    warsaw = pytz.timezone('Europe/Warsaw')

    wizyty = Wizyta.objects.exclude(status="anulowana")
    events = []
    available_hours = {}

    min_booking = timezone.now() + timedelta(hours=24)
    today = timezone.localdate()
    max_date = today + timedelta(days=90)
    pl_holidays = holidays.PL()

    # Tworzymy pełną listę godzin 8–19 dla następnych 90 dni
    for single_day in (today + timedelta(days=n) for n in range(91)):
        day_str = single_day.isoformat()
        hours_list = []

        for h in range(8, 20):
            naive_dt = datetime.combine(single_day, time(hour=h))
            dt = warsaw.localize(naive_dt)

            if single_day.weekday() >= 5:
                available = False  # weekend
            elif single_day in pl_holidays:         # <- blokada świąt
                available = False
            elif dt < min_booking:
                available = False  # mniej niż 24h
            else:
                available = True

            hours_list.append({
                "hour": h,
                "available": available
            })

        available_hours[day_str] = hours_list

    # Przetwarzamy wizyty i blokady w jednej pętli
    for w in wizyty:
        start_local = timezone.localtime(w.start, warsaw)
        end_local = timezone.localtime(w.end, warsaw)

        # Ustal tytuł i kolor dla eventów do kalendarza
        if w.status == "zablokowana":
            color = "#808080"
            editable = False
        elif w.klient == klient and w.status == "potwierdzona":
            color = "#0d6efd"
            editable = False
        elif w.klient == klient and w.status in ["anulowana", "odbyta"]:
            continue  # nie pokazujemy
        else:
            color = "#cccccc"
            editable = False

        # Iterujemy po godzinach wizyty/blokady
        current_time = start_local
        while current_time < end_local:
            day_str = current_time.date().isoformat()
            hour = current_time.hour

            # ---------------------------
            # blokujemy godziny w available_hours
            # ---------------------------
            if day_str in available_hours:
                for hour_entry in available_hours[day_str]:
                    if hour_entry["hour"] == hour:
                        hour_entry["available"] = False

            # ---------------------------
            # dodajemy pełnodniowy event dla zablokowanej wizyty/admina
            # tylko raz dziennie
            # ---------------------------
            if w.status == "zablokowana" and hour == 8:
                events.append({
                    "id": f"{w.id}-{day_str}",
                    "title": "Termin niedostępny",
                    "start": datetime.combine(current_time.date(), time(hour=8)).isoformat(),
                    "end": datetime.combine(current_time.date(), time(hour=20)).isoformat(),
                    "status": w.status,
                    "color": color,
                    "editable": editable,
                })

            # dodajemy własne lub cudze wizyty do kalendarza (tylko 1 event dziennie, jeśli dotyczy pojedynczego slotu)
            if w.status == "potwierdzona" and w.klient == klient and hour == start_local.hour:
                events.append({
                    "id": w.id,
                    "title": f"Twoja wizyta {start_local.strftime('%H:%M')}",
                    "start": start_local.isoformat(),
                    "end": end_local.isoformat(),
                    "status": w.status,
                    "color": color,
                    "editable": editable,
                })
            elif w.status == "potwierdzona" and w.klient != klient and hour == start_local.hour:
                events.append({
                    "id": w.id,
                    "title": f"Termin zajęty {start_local.strftime('%H:%M')}",
                    "start": start_local.isoformat(),
                    "end": end_local.isoformat(),
                    "status": w.status,
                    "color": "#cccccc",
                    "editable": False,
                })

            current_time += timedelta(hours=1)

    return render(request, "system_rejestracji/calendar.html", {
        "events": json.dumps(events),
        "available_hours": json.dumps(available_hours),
        "today": today.isoformat(),
        "max_date": max_date.isoformat()
    })

# --------------------------------------------------

@login_required
def calendar_events(request):
    from pytz import timezone as pytz_timezone
    warsaw = pytz_timezone('Europe/Warsaw')

    events = []
    wszystkie_wizyty = Wizyta.objects.all()

    for w in wszystkie_wizyty:

        local_start = timezone.localtime(w.start, warsaw)
        local_end = timezone.localtime(w.end, warsaw)

        # 🔹 KOLOR z modelu
        color = w.STATUS_KOLORY.get(w.status, "#3498db")

        # 🔹 BLOKADA
        if w.status == "zablokowana":
            title = "Termin niedostępny"
            editable = False

        # 🔹 WIZYTA ZALOGOWANEGO PACJENTA
        elif w.klient and w.klient.user == request.user:
            title = f"Wizyta ({w.get_status_display()})"
            editable = False

        # 🔹 CUDZA WIZYTA – tylko informacja że zajęte
        else:
            title = "Termin zajęty"
            editable = False

        events.append({
            "id": w.id,
            "title": title,
            "start": local_start.isoformat(),
            "end": local_end.isoformat(),
            "status": w.status,
            "color": color,
            "editable": editable,
        })

    return JsonResponse(events, safe=False)

# BOOKING API
@login_required
def book_visit(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)

    klient = get_object_or_404(Klient, user=request.user)
    day = request.POST.get("day")
    hour = request.POST.get("hour")

    # rozpoznanie: czy to formularz HTML czy AJAX
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not day or not hour:
        if is_ajax:
            return JsonResponse({"error": "Brak daty lub godziny"}, status=400)
        return redirect("my_visits")

    try:
        hour = int(hour)
        warsaw = pytz.timezone("Europe/Warsaw")
        naive_start = datetime.strptime(f"{day} {hour:02d}:00", "%Y-%m-%d %H:%M")
        start_local = warsaw.localize(naive_start)
        end_local = start_local + Wizyta.TRWANIE
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        # minimalny czas rezerwacji: teraz + 24h
        min_start = timezone.now() + timedelta(hours=24)
        if start_local < min_start:
            if is_ajax:
                return JsonResponse({"error": "Nie można umawiać wizyty wcześniej niż 24 godziny od teraz"}, status=400)
            return redirect("my_visits")

    except Exception as e:
        if is_ajax:
            return JsonResponse({"error": f"Błąd parsowania daty: {str(e)}"}, status=400)
        return redirect("my_visits")

    # sprawdzanie konfliktów
    conflict = Wizyta.objects.filter(
        start__lt=end_utc,
        end__gt=start_utc
    ).exclude(status="anulowana")

    if conflict.exists():
        if is_ajax:
            return JsonResponse({"error": "Termin niedostępny"}, status=400)
        return redirect("my_visits")

    calendar = Calendar.objects.first()
    if not calendar:
        if is_ajax:
            return JsonResponse({"error": "Brak kalendarza w systemie"}, status=400)
        return redirect("my_visits")

    wizyta = Wizyta(
        klient=klient,
        title=f"Wizyta - {klient.user.username}",
        start=start_utc,
        end=end_utc,
        status="potwierdzona",
        calendar=calendar
    )
    wizyta.full_clean()
    wizyta.save()

    reminder_time = start_utc - timedelta(hours=24)

    now = timezone.now()

    # jeśli reminder jest w przyszłości
    if reminder_time > now:

        countdown = (reminder_time - now).total_seconds()

        send_visit_reminder_email.apply_async(
            args=[
                klient.user.email,
                klient.user.username,
                start_local.strftime("%Y-%m-%d"),
                start_local.strftime("%H:%M"),
            ],
            countdown=countdown
        )

    subject = "Nowa wizyta w systemie rejestracji"

    message = (
        f"Pacjent: {klient.user.username}\n"
        f"Data: {start_local.strftime('%Y-%m-%d')}\n"
        f"Godzina: {start_local.strftime('%H:%M')}\n"
    )

    send_admin_email.delay(subject, message)
    # -------------------------------
    # WAŻNE: jeśli to AJAX -> JSON
    # jeśli formularz -> przekierowanie
    # -------------------------------
    if is_ajax:
        return JsonResponse({"success": True})

    return redirect("my_visits")


# --------------------------------------------------
# ANULOWANIE

@login_required
def cancel_visit(request, visit_id):
    klient = get_object_or_404(Klient, user=request.user)
    wizyta = get_object_or_404(Wizyta, id=visit_id, klient=klient)
    if wizyta.status == "potwierdzona":
        wizyta.status = "anulowana"
        wizyta.save()
    
    subject = "Wizyta została anulowana"

    message = (
        f"Pacjent: {request.user.username}\n"
        f"Data: {timezone.localtime(wizyta.start).strftime('%Y-%m-%d')}\n"
        f"Godzina: {timezone.localtime(wizyta.start).strftime('%H:%M')}\n"
    )

    send_admin_email.delay(subject, message)

    return redirect("my_visits")

