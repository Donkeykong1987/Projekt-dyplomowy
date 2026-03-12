from django import forms
from django.contrib.auth.models import User
from .models import Klient, Wizyta
from django.forms.widgets import SelectDateWidget

class RegisterForm(forms.Form):
    username = forms.CharField(label="Nazwa użytkownika")
    email = forms.EmailField(label="E-mail")
    password = forms.CharField(widget=forms.PasswordInput, label="Hasło")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Powtórz hasło")
    imie = forms.CharField(label="Imię")
    nazwisko = forms.CharField(label="Nazwisko")

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Użytkownik z takim loginem już istnieje")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if Klient.objects.filter(email=email).exists():
            raise forms.ValidationError("Klient z takim e-mailem już istnieje")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password2"):
            raise forms.ValidationError("Hasła nie są takie same")

        imie = cleaned.get("imie")
        nazwisko = cleaned.get("nazwisko")
        if imie and nazwisko:
            if Klient.objects.filter(imie=imie, nazwisko=nazwisko).exists():
                raise forms.ValidationError("Klient z takim imieniem i nazwiskiem już istnieje")
        return cleaned


class KlientUpdateForm(forms.ModelForm):
    class Meta:
        model = Klient
        fields = [
            "numer_telefonu",
            "adres",
            "data_urodzenia",
            "bliska_osoba_do_kontaktu",
            "numer_osoby_do_kontaktu",
        ]
        widgets = {
            "data_urodzenia": SelectDateWidget(years=range(1920, 2030))
        }
