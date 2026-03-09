from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(
        template_name="system_rejestracji/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register_view, name="register"),
    path("moje-wizyty/", views.my_visits, name="my_visits"),
    path("wizyta/anuluj/<int:visit_id>/", views.cancel_visit, name="cancel_visit"),
    path("wizyta/umow/", views.book_visit, name="book_visit"),
    path("kalendarz/", views.user_calendar, name="calendar"),
    path("profil/", views.profile_view, name="profile"),
    path("profil/update/", views.update_profile_field, name="update_profile_field"),
    path("calendar/events/", views.calendar_events, name="calendar_events"),
    path("api/calendar/book/", views.book_visit, name="calendar_book_visit"),
]
