from django import forms

from .models import Enrollment


class ReserveForm(forms.Form):
    cohort = forms.IntegerField(min_value=1)
    plan = forms.ChoiceField(choices=Enrollment.Plan.choices)


class WaitlistForm(forms.Form):
    email = forms.EmailField(label="Your email")
    # Invisible to people; bots fill it in.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def is_bot(self):
        return bool(self.cleaned_data.get("website"))
