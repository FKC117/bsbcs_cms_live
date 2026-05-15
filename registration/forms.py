from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit

from django.contrib.auth.models import User
from .models import *
from django import forms
from django.contrib.auth.models import User
from .models import UserProfile

class UserProfileForm(forms.ModelForm):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    name = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=20)
    country = forms.CharField(max_length=100)

    class Meta:
        model = UserProfile
        fields = ['phone', 'country', 'name', 'email']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if UserProfile.objects.filter(phone=phone).exists():
            raise forms.ValidationError("A user with this phone number already exists.")
        return phone

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            email=self.cleaned_data['email']
        )
        user_profile = super().save(commit=False)
        user_profile.user = user
        user_profile.name = self.cleaned_data['name']
        if commit:
            user_profile.save()
        return user_profile





# Participant Reregistration form START------------------------------------------------------------------------------------#

from django import forms
from .models import Participant

class RegistrationForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ('name', 'degree', 'email', 'phone', 'year_of_graduation', 
                  'department', 'organization', 'country', 'BMDC_registration_number')

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)  # Pass event instance
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if Participant.objects.filter(email=email, event=self.event).exists():
            raise forms.ValidationError("A participant with this email already exists for this event.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if Participant.objects.filter(phone=phone, event=self.event).exists():
            raise forms.ValidationError("A participant with this phone number already exists for this event.")
        return phone

# Participant Reregistration form END------------------------------------------------------------------------------------#


# Abstract Submission form START------------------------------------------------------------------------------------#
class AbstractSubmissionForm(forms.ModelForm):
    class Meta:
        model = AbstractSubmission
        fields = ('title', 'authors', 'institution', 'introduction', 'methods', 'results', 'conclusion', 'image')
    def clean(self):
        cleaned_data = super().clean()
        methods = cleaned_data.get("methods", "")
        results = cleaned_data.get("results", "")

        total_words = len((methods + " " + results).split())
        if total_words > 400:
            raise forms.ValidationError("The total word count for Methods and Results should not exceed 400 words.")

# Abstract Submission form END------------------------------------------------------------------------------------


# Program Schedule form START------------------------------------------------------------------------------------#

from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
class ProgramScheduleForm(forms.ModelForm):
    class Meta:
        model = ProgramSchedule
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # If editing an existing schedule, filter time slots to exclude those assigned to other schedules
            self.fields['abstract_submission'].queryset = AbstractSubmission.objects.filter(pk=self.instance.abstract_submission.pk)
            self.fields['abstract_submission'].disabled = True
            self.fields['time_slots'].queryset = TimeSlot.objects.exclude(schedules__isnull=False).union(self.instance.time_slots.all())

        else:
            self.fields['abstract_submission'].queryset = AbstractSubmission.objects.filter(
                Q(approved_for_presentation=True) | Q(approved_for_poster=True)
            ).exclude(programschedule__isnull=False)
            self.fields['time_slots'].queryset = TimeSlot.objects.exclude(schedules__isnull=False)

        # Automatically set the authors as presenter

    def clean(self):
        cleaned_data = super().clean()
        abstract_submission = cleaned_data.get("abstract_submission")
        time_slots = cleaned_data.get("time_slots")

        if abstract_submission:
            duplicates = ProgramSchedule.objects.filter(abstract_submission=abstract_submission)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise ValidationError("A program schedule with this abstract already exists.")

        if time_slots:
            overlapping_schedules = ProgramSchedule.objects.filter(time_slots__in=time_slots).exclude(pk=self.instance.pk)
            if overlapping_schedules.exists():
                overlapping_titles = ', '.join(overlapping_schedules.values_list('abstract_submission__title', flat=True))
                raise ValidationError(f"Warning: The schedule overlaps with existing schedules: {overlapping_titles}")

        return cleaned_data


# Program Schedule form END------------------------------------------------------------------------------------


# Bulk Email form START------------------------------------------------------------------------------------#
import csv
from django import forms
from .models import BulkEmail
from django import forms
from .models import BulkEmail

class BulkEmailAdminForm(forms.ModelForm):
    class Meta:
        model = BulkEmail
        fields = ['subject', 'body', 'attachment']
    

# Bulk Email form END------------------------------------------------------------------------------------
