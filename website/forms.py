from django import forms
from .models import Member, Speciality, ResearchInterestArea
from registration.models import UserProfile


class MembershipForm(forms.ModelForm):
    """Form for submitting/editing member information.
    
    This form creates or updates a Member record and links it to the logged-in user's UserProfile.
    User data (name, email, phone) comes from UserProfile, not duplicated in Member.
    """
    
    specialties = forms.ModelMultipleChoiceField(
        queryset=Speciality.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select one or more specialties"
    )
    
    research_interest_areas = forms.ModelMultipleChoiceField(
        queryset=ResearchInterestArea.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select one or more research interest areas"
    )
    
    class Meta:
        model = Member
        fields = [
            'institution',
            'position',
            'profile_description',
            'image',
            'specialties',
            'research_interest_areas',
        ]
        widgets = {
            'institution': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Institution/Organization Name',
            }),
            'position': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Job Title/Position',
            }),
            'profile_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Tell us about yourself, your experience, and interests...',
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        # Add custom validation if needed
        return cleaned_data
