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


class ReflectionForm(forms.Form):
    text = forms.CharField(
        label="Your reflection", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "What stayed with you? One line is enough."}),
    )
