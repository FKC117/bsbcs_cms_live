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


class CorporateAccountRequestForm(forms.ModelForm):
    class Meta:
        model = CorporateAccountRequest
        fields = [
            'company_name',
            'contact_name',
            'contact_designation',
            'email',
            'phone',
            'note',
        ]
        widgets = {
            'note': forms.Textarea(attrs={'rows': 4}),
        }





# Participant Reregistration form START------------------------------------------------------------------------------------#

from django import forms
from .models import Participant

class RegistrationForm(forms.ModelForm):
    department_name = forms.CharField(label='Department', max_length=50)

    class Meta:
        model = Participant
        fields = ('name', 'degree', 'email', 'phone', 'year_of_graduation', 
                  'department_name', 'organization', 'country', 'BMDC_registration_number')
        widgets = {
            'organization': forms.TextInput(attrs={'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)  # Pass event instance
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.department_id:
            self.fields['department_name'].initial = self.instance.department.name
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')

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

    def clean_department_name(self):
        department_name = (self.cleaned_data.get('department_name') or '').strip()
        if not department_name:
            raise forms.ValidationError("Department is required.")
        return department_name[:50]

    def save(self, commit=True):
        participant = super().save(commit=False)
        department_name = self.cleaned_data.get('department_name')
        if not self.event:
            raise forms.ValidationError("Event context is missing.")
        department, _ = Department.objects.get_or_create(
            event=self.event,
            name=department_name,
        )
        participant.department = department
        if commit:
            participant.save()
            self.save_m2m()
        return participant

# Participant Reregistration form END------------------------------------------------------------------------------------#


# Abstract Submission form START------------------------------------------------------------------------------------#
class AbstractSubmissionForm(forms.ModelForm):
    class Meta:
        model = AbstractSubmission
        fields = ('title', 'authors', 'institution', 'introduction', 'methods', 'results', 'conclusion', 'image')

        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'authors': forms.TextInput(attrs={'class': 'form-input'}),
            'institution': forms.TextInput(attrs={'class': 'form-input'}),
            'introduction': forms.Textarea(attrs={'class': 'form-input abstract-word-field', 'rows': 5}),
            'methods': forms.Textarea(attrs={'class': 'form-input abstract-word-field', 'rows': 5}),
            'results': forms.Textarea(attrs={'class': 'form-input abstract-word-field', 'rows': 5}),
            'conclusion': forms.Textarea(attrs={'class': 'form-input abstract-word-field', 'rows': 5}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        introduction = cleaned_data.get("introduction", "")
        methods = cleaned_data.get("methods", "")
        results = cleaned_data.get("results", "")
        conclusion = cleaned_data.get("conclusion", "")

        total_words = len((introduction + " " + methods + " " + results + " " + conclusion).split())
        if total_words > 600:
            raise forms.ValidationError("The total word count for Introduction, Methods, Results, and Conclusion should not exceed 600 words.")
        return cleaned_data

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


class ProgramSessionBuilderForm(forms.ModelForm):
    chairpersons = forms.ModelMultipleChoiceField(
        queryset=ProgramPerson.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'workflow-select', 'size': 5}),
    )
    moderators = forms.ModelMultipleChoiceField(
        queryset=ProgramPerson.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'workflow-select', 'size': 5}),
    )
    panelists = forms.ModelMultipleChoiceField(
        queryset=ProgramPerson.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'workflow-select', 'size': 5}),
    )

    class Meta:
        model = ProgramSession
        fields = ('event', 'time_slot', 'program_day', 'hall_room', 'title', 'start_time', 'end_time', 'description', 'order')
        widgets = {
            'event': forms.Select(attrs={'class': 'workflow-input'}),
            'time_slot': forms.Select(attrs={'class': 'workflow-input'}),
            'program_day': forms.Select(attrs={'class': 'workflow-input'}),
            'hall_room': forms.Select(attrs={'class': 'workflow-input'}),
            'title': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Session title'}),
            'start_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
            'description': forms.Textarea(attrs={'class': 'workflow-input', 'rows': 3, 'placeholder': 'Optional session note'}),
            'order': forms.NumberInput(attrs={'class': 'workflow-input'}),
        }

    def __init__(self, *args, **kwargs):
        event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.order_by('-year', 'name')
        self.fields['time_slot'].required = bool(event)
        if event:
            self.fields['time_slot'].queryset = TimeSlot.objects.filter(event=event).select_related('program_day', 'hall_room').order_by('program_day__date', 'start_time')
            self.fields['program_day'].queryset = ProgramDay.objects.filter(event=event).order_by('date', 'name')
            self.fields['hall_room'].queryset = HallRoom.objects.filter(event=event).order_by('name')
        else:
            self.fields['time_slot'].queryset = TimeSlot.objects.none()
            self.fields['program_day'].queryset = ProgramDay.objects.none()
            self.fields['hall_room'].queryset = HallRoom.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        event = cleaned_data.get('event')
        time_slot = cleaned_data.get('time_slot')
        program_day = cleaned_data.get('program_day')
        hall_room = cleaned_data.get('hall_room')
        if event and time_slot and time_slot.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('time_slot', 'Time slot must belong to the selected event.')
        if event and program_day and program_day.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('program_day', 'Program day must belong to the selected event.')
        if event and hall_room and hall_room.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('hall_room', 'Hall room must belong to the selected event.')
        return cleaned_data


class ProgramDayQuickCreateForm(forms.ModelForm):
    class Meta:
        model = ProgramDay
        fields = ('name', 'date')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Day 1'}),
            'date': forms.DateInput(attrs={'class': 'workflow-input', 'type': 'date'}),
        }


class HallRoomQuickCreateForm(forms.ModelForm):
    class Meta:
        model = HallRoom
        fields = ('name',)
        widgets = {
            'name': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Main Auditorium'}),
        }


class TimeSlotQuickCreateForm(forms.ModelForm):
    class Meta:
        model = TimeSlot
        fields = ('program_day', 'hall_room', 'start_time', 'end_time')
        widgets = {
            'program_day': forms.Select(attrs={'class': 'workflow-input'}),
            'hall_room': forms.Select(attrs={'class': 'workflow-input'}),
            'start_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        if self.event:
            self.fields['program_day'].queryset = ProgramDay.objects.filter(event=self.event).order_by('date', 'name')
            self.fields['hall_room'].queryset = HallRoom.objects.filter(event=self.event).order_by('name')
        else:
            self.fields['program_day'].queryset = ProgramDay.objects.none()
            self.fields['hall_room'].queryset = HallRoom.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        program_day = cleaned_data.get('program_day')
        hall_room = cleaned_data.get('hall_room')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if self.event and program_day and program_day.event_id != self.event.id:  # type: ignore[attr-defined]
            self.add_error('program_day', 'Program day must belong to the selected event.')
        if self.event and hall_room and hall_room.event_id != self.event.id:  # type: ignore[attr-defined]
            self.add_error('hall_room', 'Hall room must belong to the selected event.')
        if start_time and end_time and start_time >= end_time:
            self.add_error('end_time', 'End time must be after start time.')
        return cleaned_data


class ProgramSessionItemBuilderForm(forms.Form):
    order = forms.IntegerField(required=False, min_value=0, widget=forms.NumberInput(attrs={'class': 'workflow-input'}))
    start_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    end_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    title = forms.CharField(
        required=False,
        max_length=400,
        widget=forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Text title if this is not an abstract'}),
    )
    abstract_submission = forms.ModelChoiceField(
        queryset=AbstractSubmission.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'workflow-input'}),
    )
    speakers = forms.ModelMultipleChoiceField(
        queryset=ProgramPerson.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'workflow-select', 'size': 4}),
    )
    presenters = forms.ModelMultipleChoiceField(
        queryset=ProgramPerson.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'workflow-select', 'size': 4}),
    )

    def __init__(self, *args, **kwargs):
        event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        abstracts = AbstractSubmission.objects.filter(
            Q(approved_for_presentation=True) | Q(approved_for_poster=True)
        ).order_by('title')
        if event:
            abstracts = abstracts.filter(event=event)
        else:
            abstracts = AbstractSubmission.objects.none()
        self.fields['abstract_submission'].queryset = abstracts

    def clean(self):
        cleaned_data = super().clean()
        has_any_value = any([
            cleaned_data.get('order') is not None,
            cleaned_data.get('start_time'),
            cleaned_data.get('end_time'),
            cleaned_data.get('title'),
            cleaned_data.get('abstract_submission'),
            cleaned_data.get('speakers'),
            cleaned_data.get('presenters'),
        ])
        if has_any_value and not cleaned_data.get('title') and not cleaned_data.get('abstract_submission'):
            raise forms.ValidationError('Each program item needs either an approved abstract or a text-based title.')
        return cleaned_data


ProgramSessionItemBuilderFormSet = forms.formset_factory(
    ProgramSessionItemBuilderForm,
    extra=8,
    max_num=20,
    validate_max=False,
)


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
