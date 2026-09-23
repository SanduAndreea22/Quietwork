from django import forms

from .models import Enrollment


class ReserveForm(forms.Form):
    cohort = forms.IntegerField(min_value=1)
    plan = forms.ChoiceField(choices=Enrollment.Plan.choices)
