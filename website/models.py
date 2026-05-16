from django.db import models
from django.utils import timezone


class SiteSettings(models.Model):
    site_name = models.CharField(max_length=255, default='BSBCS')
    abbreviation = models.CharField(max_length=50, blank=True, null=True)
    tag_line = models.CharField(max_length=255, blank=True, null=True)
    logo = models.ImageField(upload_to='site_settings/', blank=True, null=True)
    favicon = models.ImageField(upload_to='site_settings/', blank=True, null=True)
    footer_content = models.TextField(blank=True, null=True)
    contact_mail = models.EmailField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    footer_copyright = models.CharField(max_length=255, blank=True, null=True)
    facebook_url = models.URLField(blank=True, null=True)
    twitter_url = models.URLField(blank=True, null=True)
    instagram_url = models.URLField(blank=True, null=True)
    youtube_url = models.URLField(blank=True, null=True)
    linkedin_url = models.URLField(blank=True, null=True)
    
    # Membership Subscription Settings
    membership_subscription_enabled = models.BooleanField(default=False, help_text="Enable/Disable membership subscription system")
    membership_yearly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Default yearly membership fee (deprecated if types are used)")
    membership_facilities = models.TextField(blank=True, null=True, help_text="List of facilities/benefits for members")
    membership_invoice_logo = models.ImageField(upload_to='site_settings/invoices/', blank=True, null=True, help_text="Logo specifically for membership invoices")

    def __str__(self):
        return self.site_name

class MembershipType(models.Model):
    name = models.CharField(max_length=100) # e.g. Annual, Lifetime
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    duration_years = models.PositiveIntegerField(default=1, help_text="Default duration in years. For lifetime, this can be 100.")
    is_lifetime = models.BooleanField(default=False, help_text="Mark this as a lifetime membership to disable duration selection in UI")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.name} - BDT {self.amount}"

    class Meta:
        ordering = ['order']



class NavigationLink(models.Model):
    label = models.CharField(max_length=100)
    url_name = models.CharField(max_length=100)  # Django URL name or external URL
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    is_dropdown = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    class Meta:
        ordering = ['order']


class HeroSection(models.Model):
    PAGE_CHOICES = [
        ('homepage', 'Homepage'),
        ('about', 'About'),
        ('knowledge_center', 'Knowledge Center'),
        ('member_directory', 'Member Directory'),
        ('news_and_updates', 'News and Updates'),
        ('research_and_publications', 'Research and Publications'),
        ('webinars', 'Webinars'),
    ]

    page = models.CharField(max_length=50, choices=PAGE_CHOICES)
    title = models.CharField(max_length=255)
    subtitle = models.TextField(blank=True, null=True)
    background_image = models.ImageField(upload_to='images/hero/', blank=True, null=True)  # SVG content or path reference

    def __str__(self):
        return f"{self.page} Hero - {self.title}"


class CarouselItem(models.Model):
    hero_section = models.ForeignKey(HeroSection, on_delete=models.CASCADE, related_name='carousel_items')
    title = models.CharField(max_length=255)
    subtitle = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    image_url = models.ImageField(upload_to='images/carousel/', blank=True, null=True)
    badge_text = models.CharField(max_length=50, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order']


class NewsTickerItem(models.Model):
    text = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.text

    class Meta:
        ordering = ['order']


class QuickAccessCard(models.Model):
    PAGE_CHOICES = HeroSection.PAGE_CHOICES

    page = models.CharField(max_length=50, choices=PAGE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    link_url = models.URLField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.page} QuickAccess - {self.title}"

    class Meta:
        ordering = ['order']


class StatisticCounter(models.Model):
    PAGE_CHOICES = HeroSection.PAGE_CHOICES

    page = models.CharField(max_length=50, choices=PAGE_CHOICES)
    title = models.CharField(max_length=255)
    count_text = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.page} StatisticCounter - {self.title}"

    class Meta:
        ordering = ['order']

class ResearchInterestArea(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return self.name
class Speciality(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return self.name

class MemberSpotlight(models.Model):
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    image_url = models.ImageField(upload_to='images/members/', blank=True, null=True)
    profile_url = models.URLField(blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']


class ResearchHighlight(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    published_date = models.DateField(blank=True, null=True)
    lead_researcher_name = models.CharField(max_length=255, blank=True, null=True)
    lead_researcher_image_url = models.ImageField(upload_to='images/researchers/', blank=True, null=True)
    journal_name = models.CharField(max_length=255, blank=True, null=True)
    journal_link = models.URLField(blank=True, null=True)    
    highlight = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order']

class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ('conference', 'Conference'),
        ('workshop', 'Workshop'),
        ('webinar', 'Webinar'),
        ('meeting', 'Meeting'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=255)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPE_CHOICES)
    date = models.DateField()
    location = models.CharField(max_length=255, blank=True, null=True)
    time = models.TimeField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    registration_url = models.URLField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title} ({self.date})"

    class Meta:
        ordering = ['order', 'date']



class PastEvent(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    year = models.PositiveIntegerField()
    date_text = models.CharField(max_length=255, help_text="e.g. 11 November 2022")
    location = models.CharField(max_length=255, blank=True, null=True)
    venue = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. Pan Pacific Sonargaon, Dhaka")
    slogan = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='past_events/logos/', blank=True, null=True)
    hero_image = models.ImageField(upload_to='past_events/hero/', blank=True, null=True)
    about_image = models.ImageField(upload_to='past_events/about/', blank=True, null=True, help_text="Image for the 'About' section")
    organizer = models.CharField(max_length=255, default="Bangladesh Society for Breast Cancer Study (BSBCS)")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(f"{self.title} {self.year}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.year})"

    class Meta:
        ordering = ['-year', 'order']


class PastEventSpeaker(models.Model):
    event = models.ForeignKey(PastEvent, on_delete=models.CASCADE, related_name='speakers')
    name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='past_events/speakers/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} - {self.event.title}"

    class Meta:
        ordering = ['order']


class PastEventSession(models.Model):
    event = models.ForeignKey(PastEvent, on_delete=models.CASCADE, related_name='sessions')
    day_name = models.CharField(max_length=100, help_text="e.g. Day 1 or Nov 10")
    session_name = models.CharField(max_length=255, help_text="e.g. Radiation Oncology")
    time_range = models.CharField(max_length=100, help_text="e.g. 09:00 AM – 09:40 AM")
    chairmen = models.TextField(blank=True, null=True, help_text="Comma separated names")
    moderators = models.TextField(blank=True, null=True, help_text="Comma separated names")
    panelists = models.TextField(blank=True, null=True, help_text="Comma separated names")
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.day_name} - {self.session_name}"

    class Meta:
        ordering = ['order']


class PastEventActivity(models.Model):
    event = models.ForeignKey(PastEvent, on_delete=models.CASCADE, related_name='all_activities', null=True, blank=True)
    session = models.ForeignKey(PastEventSession, on_delete=models.CASCADE, related_name='activities')
    time = models.CharField(max_length=100, blank=True, null=True)
    topic = models.CharField(max_length=255)
    speaker_name = models.CharField(max_length=255, blank=True, null=True)
    chairmen = models.TextField(blank=True, null=True, help_text="Comma separated names")
    moderators = models.TextField(blank=True, null=True, help_text="Comma separated names")
    panelists = models.TextField(blank=True, null=True, help_text="Comma separated names")
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.topic

    class Meta:
        ordering = ['order']


class PastEventSponsor(models.Model):
    event = models.ForeignKey(PastEvent, on_delete=models.CASCADE, related_name='sponsors')
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. Platinum, Golden")
    logo = models.ImageField(upload_to='past_events/sponsors/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} ({self.category})"

    class Meta:
        ordering = ['order']


class CallToAction(models.Model):
    PAGE_CHOICES = HeroSection.PAGE_CHOICES

    page = models.CharField(max_length=50, choices=PAGE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    primary_button_text = models.CharField(max_length=100, blank=True, null=True)
    secondary_button_text = models.CharField(max_length=100, blank=True, null=True)
    primary_button_url = models.URLField(blank=True, null=True)
    secondary_button_url = models.URLField(blank=True, null=True)
    background_svg = models.ImageField(upload_to='images/backgrounds/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.page} CTA - {self.title}"

    class Meta:
        ordering = ['order']


class BoardMember(models.Model):
    ROLE_CHOICES = [
        ('president', 'President'),
        ('vice_president', 'Vice President'),
        ('secretary', 'Secretary'),
        ('treasurer', 'Treasurer'),
        ('board_member', 'Board Member'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    qualifications = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    image_url = models.ImageField(upload_to='images/board/', blank=True, null=True)
    social_links = models.JSONField(blank=True, null=True)  # Example: {"linkedin": "url", "twitter": "url"}
    order = models.PositiveIntegerField(default=0)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='board_member')

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"  # type: ignore

    class Meta:
        ordering = ['order']


class Committee(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    member_count = models.PositiveIntegerField(default=0)
    link_to_members = models.URLField(blank=True, null=True)
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']


class Partnership(models.Model):
    name = models.CharField(max_length=255)
    logo = models.ImageField(upload_to='images/partnership/', blank=True, null=True)
    link_url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']


class Award(models.Model):
    title = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255)
    year = models.PositiveIntegerField()
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title} ({self.year})"

    class Meta:
        ordering = ['order', '-year']


class AnnualReport(models.Model):
    year = models.PositiveIntegerField()
    description = models.TextField(blank=True, null=True)
    file_upload = models.FileField(upload_to='files/annual_reports/', blank=True, null=True)
    file_size = models.CharField(max_length=50, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Annual Report {self.year}"

    class Meta:
        ordering = ['-year']


class ResourceCategory(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']


class ResourceItem(models.Model):
    RESOURCE_TYPE_CHOICES = [
        ('guideline', 'Guideline'),
        ('research_publication', 'Research Publication'),
        ('educational_material', 'Educational Material'),
        ('tool', 'Tool'),
        ('webinar', 'Webinar'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(ResourceCategory, on_delete=models.SET_NULL, null=True, related_name='resources')
    resource_type = models.CharField(max_length=50, choices=RESOURCE_TYPE_CHOICES)
    updated_date = models.DateField(blank=True, null=True)
    file_upload = models.FileField(upload_to='files/resources/', blank=True, null=True)
    external_link = models.URLField(blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order']


class Panelist(models.Model):
    """A panelist or moderator for webinars and events."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)  # Job title/role
    image = models.ImageField(upload_to='images/panelists/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
   
    def __str__(self):
        return self.name




class Webinar(models.Model):
    TYPE_CHOICES = [
        ('perceptorship', 'Percepetoship'),
        ('webinar', 'Webinar'),
        ('gci', 'GCI'),
        ('other', 'Other'),
    ]
    type = models.CharField(max_length=50, choices=TYPE_CHOICES, default='webinar')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    presenter_name = models.CharField(max_length=255, blank=True, null=True)
    presenter_image = models.ImageField(upload_to='images/presenters/', blank=True, null=True)
    recorded_date = models.DateField(blank=True, null=True)
    duration = models.DurationField(blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    slides_url = models.URLField(blank=True, null=True)
    international_panel = models.ManyToManyField(Panelist, blank=True, related_name='international_panel_webinars')
    national_panel = models.ManyToManyField(Panelist, blank=True, related_name='national_panel_webinars')
    moderators = models.ManyToManyField(Panelist, blank=True, related_name='moderated_webinars')
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order']


class Member(models.Model):
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # Link to registration.UserProfile instead of duplicating user data
    user_profile = models.OneToOneField(
        'registration.UserProfile',
        on_delete=models.CASCADE,
        related_name='member',
        null=True,
        blank=True
    )

    # Membership-specific fields
    institution = models.CharField(max_length=255, blank=True, null=True)
    position = models.CharField(max_length=255, blank=True, null=True)
    profile_description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='images/members/', blank=True, null=True)
    specialties = models.ManyToManyField(Speciality, blank=True, related_name='members_specialties')
    research_interest_areas = models.ManyToManyField(ResearchInterestArea, blank=True, related_name='members')
    
    # Approval workflow fields
    approval_status = models.CharField(
        max_length=10,
        choices=APPROVAL_STATUS_CHOICES,
        default='pending'
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    # Subscription status fields
    membership_type = models.ForeignKey(MembershipType, on_delete=models.SET_NULL, null=True, blank=True)
    is_active_member = models.BooleanField(default=False, help_text="Designates whether this member has an active subscription")
    subscription_start_date = models.DateField(blank=True, null=True)
    subscription_expiry_date = models.DateField(blank=True, null=True)
    
    # Metadata
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_profile.name} ({self.get_approval_status_display()})"  # type: ignore

    class Meta:
        ordering = ['order']


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class OrganizationalValue(models.Model):
    VALUE_TYPE_CHOICES = [
        ('mission', 'Mission'),
        ('vision', 'Vision'),
        ('value', 'Value'),
    ]

    value_type = models.CharField(max_length=20, choices=VALUE_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField()
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.get_value_type_display()} - {self.title}"  # type: ignore

    class Meta:
        ordering = ['value_type', 'order']
        verbose_name_plural = "Organizational Values"


class TimelineSection(models.Model):
    """A header section for the About page timeline.

    Contains an optional intro and icon; `TimelineItem` children represent
    individual timeline events ordered for display.
    """

    title = models.CharField(max_length=255)
    intro = models.TextField(blank=True, null=True)
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order']


class TimelineItem(models.Model):
    section = models.ForeignKey(TimelineSection, on_delete=models.CASCADE, related_name='items')
    event_date = models.DateField(blank=True, null=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    icon_svg = models.ImageField(upload_to='images/icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.section.title} - {self.title}"

    class Meta:
        ordering = ['order']


class Media(models.Model):
    MEDIA_TYPE_CHOICES = [
        ('image', 'Photo'),
        ('video', 'Video'),
    ]
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default='image')
    file = models.ImageField(upload_to='images/gallery/', blank=True, null=True)
    video_url = models.URLField(blank=True, null=True, help_text="YouTube or Vimeo URL")
    
    # Event selection options
    registration_event = models.ForeignKey(
        'registration.Event', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        limit_choices_to={'event_status': 'closed'},
        related_name='website_media'
    )
    custom_event_name = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="Enter event name if it's not in the registration app"
    )
    
    caption = models.CharField(max_length=255, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        event_name = self.custom_event_name or (self.registration_event.name if self.registration_event else 'General')
        return f"{self.get_media_type_display()} - {event_name} - {self.caption[:30] if self.caption else 'No Caption'}"

    class Meta:
        ordering = ['order', '-created_at']
        verbose_name_plural = "Media Gallery"


class MembershipPayment(models.Model):
    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    user_profile = models.ForeignKey(
        'registration.UserProfile', 
        on_delete=models.CASCADE, 
        related_name='membership_payments'
    )
    membership_type = models.ForeignKey(MembershipType, on_delete=models.SET_NULL, null=True)
    duration_years = models.PositiveIntegerField(default=1)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)  # bKash Payment ID
    merchant_invoice_number = models.CharField(max_length=255, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    trxID = models.CharField(max_length=255, blank=True, null=True)  # bKash Transaction ID
    invoice = models.FileField(upload_to='membership_invoices/', blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_profile.name} - {self.amount} - {self.status}"

    class Meta:
        ordering = ['-created_at']


class MembershipBenefitModal(models.Model):
    title = models.CharField(max_length=180, default="Become a BSBCS Member")
    subtitle = models.CharField(max_length=220, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(
        upload_to='membership/benefits/',
        blank=True,
        null=True,
        help_text=(
            'Optional image-only modal. Recommended size: 1200x800 px, 3:2 ratio. '
            'If uploaded, this image is shown instead of text benefits.'
        )
    )
    primary_button_text = models.CharField(max_length=80, default="Apply for Membership")
    secondary_button_text = models.CharField(max_length=80, default="Maybe Later")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            MembershipBenefitModal.objects.exclude(pk=self.pk).update(is_active=False)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Membership Benefit Modal"
        verbose_name_plural = "Membership Benefit Modal"


class MembershipBenefitItem(models.Model):
    modal = models.ForeignKey(MembershipBenefitModal, on_delete=models.CASCADE, related_name='benefit_items')
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    icon = models.ImageField(upload_to='membership/benefit_icons/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['order', 'id']

