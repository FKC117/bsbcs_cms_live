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





class DashboardEventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'name',
            'slogan',
            'year',
            'start_date',
            'end_date',
            'location',
            'event_status',
            'registration',
            'registration_audience',
            'payment_required',
            'amount',
            'member_registration_enabled',
            'member_registration_fee',
            'show_publication_tab',
            'event_logo',
            'event_hero_image',
            'modal_image',
            'description',
            'keywords',
            'author',
            'og_image',
            'email_subject',
            'email_body',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Event name'}),
            'slogan': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Short public tagline'}),
            'year': forms.NumberInput(attrs={'class': 'workflow-input', 'min': 2020}),
            'start_date': forms.DateInput(attrs={'class': 'workflow-input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'workflow-input', 'type': 'date'}),
            'location': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Venue or city'}),
            'event_status': forms.Select(attrs={'class': 'workflow-input'}),
            'registration': forms.Select(attrs={'class': 'workflow-input'}),
            'registration_audience': forms.Select(attrs={'class': 'workflow-input'}),
            'amount': forms.NumberInput(attrs={'class': 'workflow-input', 'min': 0, 'step': '0.01', 'placeholder': '0.00'}),
            'member_registration_fee': forms.NumberInput(attrs={'class': 'workflow-input', 'min': 0, 'step': '0.01', 'placeholder': 'Leave blank or 0 for free'}),
            'event_logo': forms.ClearableFileInput(attrs={'class': 'workflow-file'}),
            'event_hero_image': forms.ClearableFileInput(attrs={'class': 'workflow-file'}),
            'modal_image': forms.ClearableFileInput(attrs={'class': 'workflow-file'}),
            'description': forms.Textarea(attrs={'class': 'workflow-input', 'rows': 4, 'placeholder': 'Short event overview for the event page'}),
            'keywords': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Comma separated SEO keywords'}),
            'author': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Author or organizer'}),
            'og_image': forms.ClearableFileInput(attrs={'class': 'workflow-file'}),
            'email_subject': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Optional thank-you email subject'}),
            'email_body': forms.Textarea(attrs={'class': 'workflow-input', 'rows': 4, 'placeholder': 'Optional thank-you email body'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('payment_required', 'member_registration_enabled', 'show_publication_tab'):
            self.fields[field_name].widget.attrs.setdefault(
                'class',
                'h-5 w-5 rounded border-line text-bsbcs-blue focus:ring-bsbcs-blue/20',
            )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        payment_required = cleaned_data.get('payment_required')
        amount = cleaned_data.get('amount')
        member_registration_enabled = cleaned_data.get('member_registration_enabled')
        member_registration_fee = cleaned_data.get('member_registration_fee')

        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be before the start date.')

        if payment_required and amount in (None, ''):
            self.add_error('amount', 'Add the regular registration fee, or turn payment required off.')

        if amount is not None and amount < 0:
            self.add_error('amount', 'Regular registration fee cannot be negative.')

        if member_registration_fee is not None and member_registration_fee < 0:
            self.add_error('member_registration_fee', 'Member registration fee cannot be negative.')

        if not member_registration_enabled:
            cleaned_data['member_registration_fee'] = None

        return cleaned_data


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


class DashboardParticipantCreateForm(forms.ModelForm):
    event = forms.ModelChoiceField(
        queryset=Event.objects.none(),
        widget=forms.Select(attrs={'class': 'workflow-input'}),
    )
    department_name = forms.CharField(
        label='Department',
        max_length=50,
        required=False,
        help_text='Optional for staff-added registrations.',
        widget=forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Department or specialty'}),
    )
    approval_state = forms.ChoiceField(
        label='Starting status',
        choices=[
            ('pending', 'Pending approval'),
            ('approved', 'Approve now'),
        ],
        initial='pending',
        widget=forms.Select(attrs={'class': 'workflow-input'}),
        help_text='Approve now creates the payment row and queues the appropriate confirmation email.',
    )

    class Meta:
        model = Participant
        fields = (
            'event',
            'registration_type',
            'name',
            'email',
            'phone',
            'degree',
            'year_of_graduation',
            'department_name',
            'organization',
            'country',
            'BMDC_registration_number',
        )
        widgets = {
            'registration_type': forms.Select(attrs={'class': 'workflow-input'}),
            'name': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Participant name'}),
            'email': forms.EmailInput(attrs={'class': 'workflow-input', 'placeholder': 'Email address'}),
            'phone': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Phone number'}),
            'degree': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Degree / qualification'}),
            'year_of_graduation': forms.NumberInput(attrs={'class': 'workflow-input', 'min': 0, 'placeholder': 'Year'}),
            'organization': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Institution / organization'}),
            'country': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Country'}),
            'BMDC_registration_number': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Optional BMDC number'}),
        }

    def __init__(self, *args, **kwargs):
        selected_event = kwargs.pop('selected_event', None)
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.order_by('-year', 'name')
        optional_fields = ('degree', 'year_of_graduation', 'organization', 'BMDC_registration_number')
        for field_name in optional_fields:
            self.fields[field_name].required = False
            self.fields[field_name].help_text = 'Optional for staff-added registrations.'
        if selected_event:
            self.fields['event'].initial = selected_event

    def clean(self):
        cleaned_data = super().clean()
        event = cleaned_data.get('event')
        email = (cleaned_data.get('email') or '').strip()
        phone = (cleaned_data.get('phone') or '').strip()
        if event and email and Participant.objects.filter(event=event, email__iexact=email).exists():
            self.add_error('email', 'This email is already registered for the selected event.')
        if event and phone and Participant.objects.filter(event=event, phone=phone).exists():
            self.add_error('phone', 'This phone number is already registered for the selected event.')
        matched_user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first() if email else None
        if email and UserProfile.objects.filter(email__iexact=email).exclude(user=matched_user).exists():
            self.add_error('email', 'This email is already linked to another website profile.')
        if phone and UserProfile.objects.filter(phone=phone).exclude(user=matched_user).exists():
            self.add_error('phone', 'This phone number is already linked to another website profile.')
        return cleaned_data

    def save(self, commit=True):
        participant = super().save(commit=False)
        event = self.cleaned_data['event']
        participant.degree = (self.cleaned_data.get('degree') or 'Not provided').strip()
        participant.year_of_graduation = self.cleaned_data.get('year_of_graduation') or 0
        participant.organization = (self.cleaned_data.get('organization') or 'Not provided').strip()
        department_name = (self.cleaned_data.get('department_name') or 'Not specified').strip()[:50]
        department, _ = Department.objects.get_or_create(
            event=event,
            name=department_name,
        )
        participant.event = event
        participant.department = department
        if commit:
            participant.save()
        return participant


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


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        profile_name = getattr(getattr(obj, 'userprofile', None), 'name', '') or obj.get_full_name()
        email = obj.email or obj.username
        if profile_name:
            return f"{profile_name} - {email}"
        return email


class DashboardAbstractSubmissionForm(AbstractSubmissionForm):
    event = forms.ModelChoiceField(
        queryset=Event.objects.none(),
        widget=forms.Select(attrs={
            'class': 'workflow-input',
            'data-searchable-select': '',
            'data-search-placeholder': 'Search event name or year',
        }),
    )
    user = UserChoiceField(
        label='Submitter',
        queryset=User.objects.none(),
        widget=forms.Select(attrs={
            'class': 'workflow-input',
            'data-searchable-select': '',
            'data-search-placeholder': 'Search submitter name or email',
        }),
        help_text='Select the existing website user who owns this abstract.',
    )

    class Meta(AbstractSubmissionForm.Meta):
        model = AbstractSubmission
        fields = (
            'event',
            'user',
            'title',
            'authors',
            'institution',
            'introduction',
            'methods',
            'results',
            'conclusion',
            'image',
            'presentation_file',
        )
        widgets = {
            **AbstractSubmissionForm.Meta.widgets,
            'presentation_file': forms.ClearableFileInput(attrs={'class': 'workflow-input'}),
        }

    def __init__(self, *args, **kwargs):
        selected_event = kwargs.pop('selected_event', None)
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.order_by('-year', 'name')
        self.fields['user'].queryset = User.objects.select_related('userprofile').order_by('email', 'username')
        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '')
            if 'workflow-input' not in existing_class:
                field.widget.attrs['class'] = f"{existing_class} workflow-input".strip()
        if selected_event:
            self.fields['event'].initial = selected_event


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
            self.fields['time_slot'].queryset = TimeSlot.objects.filter(
                event=event,
                slot_type=TimeSlot.SLOT_SESSION,
            ).select_related('program_day', 'hall_room').order_by('program_day__date', 'start_time')
            self.fields['program_day'].queryset = ProgramDay.objects.filter(event=event).order_by('date', 'name')
            self.fields['hall_room'].queryset = HallRoom.objects.filter(event=event).order_by('name')
            event_people = ProgramPerson.objects.filter(events=event)
            if self.instance and self.instance.pk:
                event_people = ProgramPerson.objects.filter(
                    Q(events=event)
                    | Q(session_roles__session=self.instance)
                )
            event_people = event_people.distinct().order_by('name')
            for field_name in ('chairpersons', 'moderators', 'panelists'):
                self.fields[field_name].queryset = event_people
        else:
            self.fields['time_slot'].queryset = TimeSlot.objects.none()
            self.fields['program_day'].queryset = ProgramDay.objects.none()
            self.fields['hall_room'].queryset = HallRoom.objects.none()
            for field_name in ('chairpersons', 'moderators', 'panelists'):
                self.fields[field_name].queryset = ProgramPerson.objects.none()

        if self.instance and self.instance.pk:
            self.fields['chairpersons'].initial = ProgramPerson.objects.filter(
                session_roles__session=self.instance,
                session_roles__role=ProgramSessionFaculty.ROLE_CHAIRPERSON
            )
            self.fields['moderators'].initial = ProgramPerson.objects.filter(
                session_roles__session=self.instance,
                session_roles__role=ProgramSessionFaculty.ROLE_MODERATOR
            )
            self.fields['panelists'].initial = ProgramPerson.objects.filter(
                session_roles__session=self.instance,
                session_roles__role=ProgramSessionFaculty.ROLE_PANELIST
            )

    def clean(self):
        cleaned_data = super().clean()
        event = cleaned_data.get('event')
        time_slot = cleaned_data.get('time_slot')
        program_day = cleaned_data.get('program_day')
        hall_room = cleaned_data.get('hall_room')
        if event and time_slot and time_slot.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('time_slot', 'Time slot must belong to the selected event.')
        if time_slot and time_slot.slot_type != TimeSlot.SLOT_SESSION:
            self.add_error('time_slot', 'Choose a session slot. Break and meal blocks cannot hold sessions.')
        if event and program_day and program_day.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('program_day', 'Program day must belong to the selected event.')
        if event and hall_room and hall_room.event_id != event.id:  # type: ignore[attr-defined]
            self.add_error('hall_room', 'Hall room must belong to the selected event.')
        session_role_people = {}
        for field_name in ('chairpersons', 'moderators', 'panelists'):
            for person in cleaned_data.get(field_name) or []:
                previous_role = session_role_people.get(person.id)
                if previous_role:
                    self.add_error(
                        field_name,
                        f'{person.name} is already selected as {previous_role}. Use each person once across chairpersons, moderators, and panelists.',
                    )
                else:
                    session_role_people[person.id] = field_name.rstrip('s')
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
        fields = ('program_day', 'hall_room', 'start_time', 'end_time', 'slot_type', 'label')
        widgets = {
            'program_day': forms.Select(attrs={'class': 'workflow-input'}),
            'hall_room': forms.Select(attrs={'class': 'workflow-input'}),
            'start_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}),
            'slot_type': forms.Select(attrs={'class': 'workflow-input'}),
            'label': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Optional label, e.g. Tea Break'}),
        }

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        if self.event:
            # ModelForm runs TimeSlot.clean() during is_valid(), before the view saves.
            # Attach the scoped event now so day/room validation sees a complete slot.
            if not self.instance.event_id:
                self.instance.event = self.event
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


class TimeSlotGeneratorForm(forms.Form):
    program_day = forms.ModelChoiceField(
        queryset=ProgramDay.objects.none(),
        widget=forms.Select(attrs={'class': 'workflow-input'}),
    )
    hall_room = forms.ModelChoiceField(
        queryset=HallRoom.objects.none(),
        widget=forms.Select(attrs={'class': 'workflow-input'}),
    )
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    slot_minutes = forms.IntegerField(
        min_value=5,
        max_value=240,
        initial=120,
        widget=forms.NumberInput(attrs={'class': 'workflow-input', 'min': 5, 'max': 240, 'step': 5}),
    )
    talk_slot_minutes = forms.IntegerField(
        min_value=5,
        max_value=120,
        initial=20,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'workflow-input', 'min': 5, 'max': 120, 'step': 5}),
        help_text='Optional internal talk block duration for each generated session slot.',
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        if self.event:
            self.fields['program_day'].queryset = ProgramDay.objects.filter(event=self.event).order_by('date', 'name')
            self.fields['hall_room'].queryset = HallRoom.objects.filter(event=self.event).order_by('name')

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


class GeneratedTimeSlotPreviewForm(forms.Form):
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'workflow-input', 'type': 'time'}))
    slot_type = forms.ChoiceField(
        choices=TimeSlot.SLOT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'workflow-input'}),
    )
    label = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Optional block label'}),
    )
    talk_slot_minutes = forms.IntegerField(
        required=False,
        min_value=5,
        max_value=120,
        widget=forms.NumberInput(attrs={'class': 'workflow-input', 'min': 5, 'max': 120, 'step': 5, 'placeholder': '20'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if start_time and end_time and start_time >= end_time:
            self.add_error('end_time', 'End time must be after start time.')
        return cleaned_data


class BaseGeneratedTimeSlotPreviewFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        active_slots = []
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            start_time = form.cleaned_data.get('start_time')
            end_time = form.cleaned_data.get('end_time')
            if not start_time or not end_time:
                continue
            active_slots.append((start_time, end_time, form))

        active_slots.sort(key=lambda row: row[0])
        for (_, previous_end, previous_form), (current_start, _, current_form) in zip(active_slots, active_slots[1:]):
            if current_start < previous_end:
                previous_form.add_error('end_time', 'This preview overlaps the next generated block.')
                current_form.add_error('start_time', 'This preview overlaps the previous generated block.')


GeneratedTimeSlotPreviewFormSet = forms.formset_factory(
    GeneratedTimeSlotPreviewForm,
    formset=BaseGeneratedTimeSlotPreviewFormSet,
    extra=0,
    can_delete=True,
    max_num=240,
    validate_max=True,
)


class ProgramPersonQuickCreateForm(forms.ModelForm):
    class Meta:
        model = ProgramPerson
        fields = ('name', 'degree', 'designation', 'institution', 'email', 'phone', 'country')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Full name'}),
            'degree': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Degree / qualification'}),
            'designation': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Designation'}),
            'institution': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Institution'}),
            'email': forms.EmailInput(attrs={'class': 'workflow-input', 'placeholder': 'Email'}),
            'phone': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Phone'}),
            'country': forms.TextInput(attrs={'class': 'workflow-input', 'placeholder': 'Country'}),
        }


class ProgramSessionItemBuilderForm(forms.Form):
    order = forms.IntegerField(required=False, min_value=0, widget=forms.NumberInput(attrs={'class': 'workflow-input'}))
    talk_slot = forms.ModelChoiceField(
        queryset=ProgramTalkSlot.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'workflow-input talk-slot-select'}),
    )
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
            self.fields['talk_slot'].queryset = ProgramTalkSlot.objects.filter(
                time_slot__event=event,
            ).select_related('time_slot').order_by('time_slot__program_day__date', 'time_slot__start_time', 'order', 'start_time')
        else:
            abstracts = AbstractSubmission.objects.none()
            self.fields['talk_slot'].queryset = ProgramTalkSlot.objects.none()
        self.fields['abstract_submission'].queryset = abstracts

    def clean(self):
        cleaned_data = super().clean()
        has_any_value = any([
            cleaned_data.get('order') is not None,
            cleaned_data.get('talk_slot'),
            cleaned_data.get('start_time'),
            cleaned_data.get('end_time'),
            cleaned_data.get('title'),
            cleaned_data.get('abstract_submission'),
            cleaned_data.get('speakers'),
            cleaned_data.get('presenters'),
        ])
        if has_any_value and not cleaned_data.get('title') and not cleaned_data.get('abstract_submission'):
            raise forms.ValidationError('Each program item needs either an approved abstract or a text-based title.')
        talk_slot = cleaned_data.get('talk_slot')
        if talk_slot:
            cleaned_data['start_time'] = talk_slot.start_time
            cleaned_data['end_time'] = talk_slot.end_time
        return cleaned_data


class BaseProgramSessionItemBuilderFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        used_slots = {}
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            talk_slot = form.cleaned_data.get('talk_slot')
            if not talk_slot:
                continue
            if talk_slot.pk in used_slots:
                form.add_error('talk_slot', 'This talk slot is already selected by another talk item.')
                used_slots[talk_slot.pk].add_error('talk_slot', 'This talk slot is already selected by another talk item.')
            else:
                used_slots[talk_slot.pk] = form


ProgramSessionItemBuilderFormSet = forms.formset_factory(
    ProgramSessionItemBuilderForm,
    formset=BaseProgramSessionItemBuilderFormSet,
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
