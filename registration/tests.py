from datetime import date, time
import io
import os
import tempfile
import zipfile
from urllib.parse import urlencode
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core import mail
from registration.models import (
    Event, Department, Participant, PaymentStatus, ProgramDay, HallRoom, TimeSlot, ProgramPerson, ProgramPersonEmailLog, UserProfile,
    ProgramSession, ProgramSessionFaculty, ProgramSessionItem, ProgramTalkSlot,
    ProgramItemFaculty, AbstractSubmission, RegistrationKit,
    CorporateAccountRequest, CorporateAccount, CorporateEventRegistration, CorporateEventAttendee, CorporatePayment,
    BulkEmail, BulkEmailRecipient, SpeakerOutreachCoordination, SpeakerOutreachEmailLog, SpeakerOutreachTemplate,
    SpeakerOutreachTemplatePreset,
)
from registration.forms import DashboardParticipantCreateForm, ProgramSessionBuilderForm, RegistrationForm, UserProfileForm, normalize_phone_number
from registration.phone_audit import apply_phone_fixes, build_phone_fix_report, run_phone_audit
from registration.bulk_email_services import _send_bulk_email_recipient_direct
from registration.email_rendering import render_rich_email_html
from registration.tasks import send_speaker_outreach_email_task
from registration.pdf_utils import generate_invoice
from registration.qr_utils import registration_qr_payload
from website.models import Member, MembershipPayment, MembershipType

class ProgramSessionBuilderTests(TestCase):

    def setUp(self):
        # Create standard user and staff user
        self.user = User.objects.create_user(username='user', password='password', email='user@test.com')
        self.staff_user = User.objects.create_user(username='staff', password='password', email='staff@test.com', is_staff=True)

        # Create active event
        self.event = Event.objects.create(
            name="BCS Conference 2026",
            slogan="Innovation in Cardiology",
            year=2026,
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 23),
            location="Dhaka",
            event_status="active",
            registration="Open"
        )

        # Create program day, hall room and time slot
        self.day = ProgramDay.objects.create(
            event=self.event,
            name="Day 1",
            date=date(2026, 5, 21)
        )
        self.room = HallRoom.objects.create(
            event=self.event,
            name="Main Auditorium",
            location="Ground Floor"
        )
        self.department = Department.objects.create(
            event=self.event,
            name="General"
        )
        self.time_slot = TimeSlot.objects.create(
            event=self.event,
            program_day=self.day,
            hall_room=self.room,
            start_time=time(9, 0),
            end_time=time(10, 0),
            slot_type=TimeSlot.SLOT_SESSION,
            label="Session Slot 1"
        )

        # Create some program people (faculty)
        self.person1 = ProgramPerson.objects.create(
            name="Dr. John Doe",
            degree="MD, FACC",
            designation="Professor",
            institution="National Heart Foundation",
            email="john@doe.com",
            phone="123456",
            country="Bangladesh"
        )
        self.person2 = ProgramPerson.objects.create(
            name="Dr. Jane Smith",
            degree="MBBS, PhD",
            designation="Associate Professor",
            institution="Labaid Cardiac Hospital",
            email="jane@smith.com",
            phone="654321",
            country="Bangladesh"
        )
        self.person1.events.add(self.event)
        self.person2.events.add(self.event)

        # Create abstract submission
        self.abstract = AbstractSubmission.objects.create(
            user=self.user,
            event=self.event,
            title="Novel Biomarkers in Heart Failure",
            authors="John Doe, Jane Smith",
            institution="National Heart Foundation",
            introduction="Intro text",
            methods="Methods text",
            results="Results text",
            conclusion="Conclusion text",
            approved_for_presentation=True
        )

    def test_dashboard_requires_staff_authenticated(self):
        url = reverse('dashboard_program_session_builder')
        
        # Unauthenticated user should be redirected to login
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

        # Authenticated non-staff user should also be redirected or denied
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Authenticated staff user should get 200 OK
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_with_event_selected(self):
        self.client.force_login(self.staff_user)
        url = f"{reverse('dashboard_program_session_builder')}?event={self.event.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schedule Board")
        self.assertContains(response, "Day 1")
        self.assertContains(response, "Main Auditorium")

    def test_global_dashboard_shows_action_center_shortcuts(self):
        pending_participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Pending Queue Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='queue-participant@example.com',
            phone='01700000021',
            country='Bangladesh',
        )
        approved_participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Queue Payment Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='queue-payment@example.com',
            phone='01700000022',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=approved_participant,
            event=self.event,
            merchant_invoice_number='REG-QUEUE',
            amount='500.00',
            status='unpaid',
        )
        pending_abstract = AbstractSubmission.objects.create(
            user=self.user,
            event=self.event,
            title='Queue Abstract Needs Review',
            authors='Queue Author',
            institution='Queue Institution',
            introduction='Intro',
            methods='Methods',
            results='Results',
            conclusion='Conclusion',
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('global_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow lanes")
        self.assertContains(response, "What needs action now")
        self.assertContains(response, "Participants management")
        self.assertContains(response, "Payments Management")
        self.assertContains(response, "Issue Kit")
        self.assertContains(response, "Abstracts approval")
        self.assertNotContains(response, "Guided workflows")
        self.assertContains(
            response,
            f"{reverse('dashboard_participant_center')}?{urlencode({'event': self.event.id, 'status': 'pending', 'q': pending_participant.email}).replace('&', '&amp;')}",
        )
        self.assertContains(
            response,
            f"{reverse('dashboard_payment_center')}?{urlencode({'source': 'event', 'status': 'unpaid', 'event': self.event.id, 'q': approved_participant.email}).replace('&', '&amp;')}",
        )
        self.assertContains(
            response,
            f"{reverse('dashboard_abstract_center')}?{urlencode({'event': self.event.id, 'status': 'pending', 'q': pending_abstract.title}).replace('&', '&amp;')}",
        )

    def test_global_dashboard_registers_executive_members_with_completed_payment_and_invoice(self):
        profile = UserProfile.objects.create(
            user=self.user,
            name='Executive Member',
            email='user@test.com',
            phone='01700000099',
            country='Bangladesh',
        )
        member = Member.objects.create(
            user_profile=profile,
            institution='BSBCS',
            position='Secretary',
            approval_status='approved',
            is_active_member=True,
            is_executive_member=True,
        )

        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)
        response = self.client.post(
            f"{reverse('global_dashboard')}?event={self.event.id}",
            {'dashboard_action': 'register_executive_members'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        participant = Participant.objects.get(event=self.event, email='user@test.com')
        self.assertTrue(participant.approved)
        self.assertEqual(participant.registration_type, 'member')
        self.assertEqual(participant.organization, 'BSBCS')

        payment_status = PaymentStatus.objects.get(participant=participant, event=self.event)
        self.assertEqual(payment_status.status, 'completed')
        self.assertEqual(float(payment_status.amount or 0), 0.0)
        self.assertTrue(payment_status.merchant_invoice_number.startswith(f'EC-FREE-{self.event.id}-{participant.id}-'))
        self.assertTrue(bool(payment_status.invoice))
        self.assertTrue(bool(payment_status.qr_token))
        self.assertTrue(bool(payment_status.qr_code))
        self.assertTrue(RegistrationKit.objects.filter(event=self.event, payment_status=payment_status).exists())

        original_invoice_number = payment_status.merchant_invoice_number
        original_qr_token = payment_status.qr_token

        second_response = self.client.post(
            f"{reverse('global_dashboard')}?event={self.event.id}",
            {'dashboard_action': 'register_executive_members'},
            follow=True,
        )
        self.assertEqual(second_response.status_code, 200)
        payment_status.refresh_from_db()
        self.assertEqual(payment_status.merchant_invoice_number, original_invoice_number)
        self.assertEqual(payment_status.qr_token, original_qr_token)
        self.assertEqual(Participant.objects.filter(event=self.event, email='user@test.com').count(), 1)

    def test_global_dashboard_registers_executive_members_with_unpaid_ec_fee(self):
        self.event.member_registration_enabled = True
        self.event.executive_member_registration_fee = '750.00'
        self.event.save(update_fields=['member_registration_enabled', 'executive_member_registration_fee'])

        profile = UserProfile.objects.create(
            user=self.user,
            name='Executive Member Paid',
            email='user@test.com',
            phone='01700000123',
            country='Bangladesh',
        )
        Member.objects.create(
            user_profile=profile,
            institution='BSBCS',
            position='Treasurer',
            approval_status='approved',
            is_active_member=True,
            is_executive_member=True,
        )

        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)
        response = self.client.post(
            f"{reverse('global_dashboard')}?event={self.event.id}",
            {'dashboard_action': 'register_executive_members'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        participant = Participant.objects.get(event=self.event, email='user@test.com')
        self.assertTrue(participant.approved)
        self.assertEqual(participant.registration_type, 'member')

        payment_status = PaymentStatus.objects.get(participant=participant, event=self.event)
        self.assertEqual(payment_status.status, 'unpaid')
        self.assertEqual(str(payment_status.amount), '750.00')
        self.assertTrue(payment_status.merchant_invoice_number.startswith(f'EC-{self.event.id}-{participant.id}-'))
        self.assertFalse(bool(payment_status.invoice))
        self.assertFalse(bool(payment_status.qr_token))
        self.assertFalse(bool(payment_status.qr_code))
        self.assertFalse(RegistrationKit.objects.filter(event=self.event, payment_status=payment_status).exists())

        second_response = self.client.post(
            f"{reverse('global_dashboard')}?event={self.event.id}",
            {'dashboard_action': 'register_executive_members'},
            follow=True,
        )
        self.assertEqual(second_response.status_code, 200)
        payment_status.refresh_from_db()
        self.assertEqual(payment_status.status, 'unpaid')
        self.assertEqual(str(payment_status.amount), '750.00')
        self.assertEqual(Participant.objects.filter(event=self.event, email='user@test.com').count(), 1)

    def test_bulk_email_center_renders_dashboard_workflow(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_bulk_email_center'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bulk email center")
        self.assertContains(response, "Create campaign")
        self.assertContains(response, "Prepare recipients")
        self.assertContains(response, "Review recipient rows")

    def test_render_rich_email_html_supports_button_and_link_markup(self):
        html = render_rich_email_html(
            'Campaign subject',
            'Hello there\n\nRead more: [Event details](https://example.com/details)',
            button_text='Register now',
            button_url='https://example.com/register',
        )
        self.assertIn('Register now', html)
        self.assertIn('https://example.com/register', html)
        self.assertIn('Event details', html)
        self.assertIn('<a href="https://example.com/details"', html)
        self.assertNotIn('This email was sent from the BSBCS dashboard.', html)
        self.assertIn('line-height:1.55', html)
        self.assertIn('padding:28px', html)

    def test_render_rich_email_html_filters_none_lines(self):
        html = render_rich_email_html('Speaker note', 'Dear Speaker\n\nNone\n\nWarm regards')
        self.assertNotIn('>None<', html)
        self.assertIn('Dear Speaker', html)
        self.assertIn('Warm regards', html)

    def test_render_rich_email_html_renders_bullet_support_block(self):
        html = render_rich_email_html(
            'Speaker note',
            'Dear Speaker\n\nSupport details:\n- Return airfare will be arranged.\n- Hotel accommodation will be arranged.\n\nWarm regards'
        )
        self.assertIn('Support for your participation', html)
        self.assertIn('background:#ffffff;border:1px solid #d7e5f6', html)
        self.assertIn('Return airfare will be arranged.', html)
        self.assertIn('Hotel accommodation will be arranged.', html)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_bulk_email_sender_attaches_html_button_version(self):
        campaign = BulkEmail.objects.create(
            subject='Join us',
            body='Dear participant',
            button_text='Complete registration',
            button_url='https://example.com/pay',
            audience_type=BulkEmail.AUDIENCE_MANUAL,
            created_by=self.staff_user,
        )
        recipient = BulkEmailRecipient.objects.create(
            bulk_email=campaign,
            email='recipient@example.com',
            name='Recipient',
        )

        sent = _send_bulk_email_recipient_direct(campaign, recipient, sent_by=self.staff_user)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['recipient@example.com'])
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        self.assertIn('Complete registration', mail.outbox[0].alternatives[0][0])
        self.assertIn('https://example.com/pay', mail.outbox[0].alternatives[0][0])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_speaker_outreach_email_task_marks_coordination_sent(self):
        self.person1.events.add(self.event)
        coordination = SpeakerOutreachCoordination.objects.create(
            event=self.event,
            person=self.person1,
            offer_airfare=True,
            offer_hotel=True,
        )
        log = SpeakerOutreachEmailLog.objects.create(
            coordination=coordination,
            event=self.event,
            person=self.person1,
            email=self.person1.email,
            subject='Speaker invitation',
            body='Dear speaker\n\nPlease join us.',
            offer_airfare=True,
            offer_hotel=True,
            sent_by=self.staff_user,
        )

        result = send_speaker_outreach_email_task.run(log.id)

        self.assertEqual(result['status'], 'sent')
        self.assertEqual(len(mail.outbox), 1)
        coordination.refresh_from_db()
        log.refresh_from_db()
        self.assertEqual(coordination.status, SpeakerOutreachCoordination.STATUS_SENT)
        self.assertEqual(coordination.send_count, 1)
        self.assertEqual(log.status, SpeakerOutreachEmailLog.STATUS_SENT)
        self.assertIn('Please join us.', mail.outbox[0].body)

    def test_speaker_outreach_center_renders_for_staff(self):
        self.person1.events.add(self.event)
        ProgramItemFaculty.objects.create(
            item=ProgramSessionItem.objects.create(session=ProgramSession.objects.create(event=self.event, title='Session A'), title='Talk A'),
            person=self.person1,
            role=ProgramItemFaculty.ROLE_SPEAKER,
        )

        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)
        response = self.client.get(f"{reverse('dashboard_speaker_outreach_center')}?event={self.event.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Speaker outreach center')
        self.assertContains(response, self.person1.name)

    def test_speaker_outreach_center_adds_event_prospect_without_duplicate(self):
        existing_person = ProgramPerson.objects.create(
            name='Dr. Existing Prospect',
            institution='Delta Hospital',
            email='existing-prospect@example.com',
        )
        existing_person.events.add(self.event)

        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_speaker_outreach_center'), {
            'event': self.event.id,
            'speaker_action': 'add_person',
            'name': 'Dr. Existing Prospect',
            'degree': 'MD',
            'designation': 'Professor',
            'institution': 'Delta Hospital',
            'email': 'existing-prospect@example.com',
            'phone': '01710000000',
            'country': 'Bangladesh',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProgramPerson.objects.filter(events=self.event, email='existing-prospect@example.com').count(), 1)
        existing_person.refresh_from_db()
        self.assertEqual(existing_person.degree, 'MD')
        self.assertEqual(existing_person.designation, 'Professor')
        self.assertEqual(existing_person.phone, '01710000000')

    def test_speaker_outreach_center_adds_selected_library_people_to_event(self):
        library_person = ProgramPerson.objects.create(
            name='Dr. Library Prospect',
            institution='Shared Hospital',
            email='library-prospect@example.com',
        )

        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_speaker_outreach_center'), {
            'event': self.event.id,
            'speaker_action': 'add_selected_library_to_event',
            'selected_library_person_ids': [str(library_person.id)],
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(library_person.events.filter(pk=self.event.pk).exists())

    def test_speaker_outreach_center_saves_template_preset(self):
        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_speaker_outreach_center'), {
            'event': self.event.id,
            'speaker_action': 'save_template_preset',
            'preset_name': 'International keynote invitation',
            'subject': 'Invitation to join BCS Conference 2026 as a speaker',
            'intro_body': 'We would be honored to invite you.',
            'closing_body': 'Warm regards',
            'airfare_body': 'Return airfare support is available.',
            'hotel_body': '',
            'allowance_body': '',
            'local_transport_body': '',
            'special_support_body': '',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(SpeakerOutreachTemplatePreset.objects.filter(name='International keynote invitation').exists())

    def test_speaker_outreach_center_updates_template_preset(self):
        preset = SpeakerOutreachTemplatePreset.objects.create(
            name='Old pattern',
            subject='Old subject',
            intro_body='Old intro',
        )
        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_speaker_outreach_center'), {
            'event': self.event.id,
            'speaker_action': 'update_template_preset',
            'preset_id': preset.id,
            'preset_name': 'Updated pattern',
            'subject': 'Updated subject',
            'intro_body': 'Updated intro',
            'closing_body': 'Updated closing',
            'airfare_body': 'Airfare available',
            'hotel_body': '',
            'allowance_body': '',
            'local_transport_body': '',
            'special_support_body': '',
        })

        self.assertEqual(response.status_code, 302)
        preset.refresh_from_db()
        self.assertEqual(preset.name, 'Updated pattern')
        self.assertEqual(preset.subject, 'Updated subject')
        self.assertEqual(preset.intro_body, 'Updated intro')
        self.assertEqual(preset.closing_body, 'Updated closing')

    def test_event_builder_requires_staff_and_renders_workflow(self):
        url = reverse('dashboard_event_builder')

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create the event shell')
        self.assertContains(response, 'Status and registration rules')
        self.assertContains(response, 'Save and Build Program')

    def test_event_builder_creates_event_and_can_continue_to_program_builder(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_event_builder'), {
            'name': 'Focused Oncology Summit',
            'slogan': 'Focused learning',
            'year': 2026,
            'start_date': '2026-08-01',
            'end_date': '2026-08-02',
            'location': 'Dhaka',
            'event_status': 'upcoming',
            'registration': 'Starting Soon',
            'registration_audience': 'members_only',
            'payment_required': 'on',
            'amount': '1500.00',
            'member_registration_enabled': 'on',
            'member_registration_fee': '500.00',
            'executive_member_registration_fee': '250.00',
            'description': 'A focused oncology event.',
            'next_action': 'program',
        })

        event = Event.objects.get(name='Focused Oncology Summit')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('dashboard_program_session_builder')}?event={event.id}")
        self.assertEqual(event.registration_audience, 'members_only')
        self.assertTrue(event.payment_required)
        self.assertTrue(event.member_registration_enabled)
        self.assertEqual(str(event.amount), '1500.00')
        self.assertEqual(str(event.member_registration_fee), '500.00')
        self.assertEqual(str(event.executive_member_registration_fee), '250.00')

    def test_event_builder_rejects_end_date_before_start_date(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_event_builder'), {
            'name': 'Invalid Date Event',
            'slogan': 'Invalid',
            'year': 2026,
            'start_date': '2026-08-02',
            'end_date': '2026-08-01',
            'location': 'Dhaka',
            'event_status': 'upcoming',
            'registration': 'Starting Soon',
            'registration_audience': 'all',
            'payment_required': 'on',
            'amount': '100.00',
            'next_action': 'stay',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End date cannot be before the start date.')
        self.assertFalse(Event.objects.filter(name='Invalid Date Event').exists())

    def test_abstract_center_requires_staff_and_renders_review_queue(self):
        self.abstract.approved_for_presentation = False
        self.abstract.save(update_fields=['approved_for_presentation', 'updated_at'])
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_abstract_center'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Abstract center')
        self.assertContains(response, 'Submitted abstracts')
        self.assertContains(response, self.abstract.title)
        self.assertContains(response, 'Approve Presentation')

    def test_abstract_center_filters_by_event_and_search(self):
        self.abstract.approved_for_presentation = False
        self.abstract.save(update_fields=['approved_for_presentation', 'updated_at'])
        self.client.force_login(self.staff_user)
        other_event = Event.objects.create(
            name='Other Abstract Event',
            slogan='Other',
            year=2026,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        AbstractSubmission.objects.create(
            user=self.user,
            event=other_event,
            title='Different Abstract',
            authors='Other Author',
            institution='Other Institute',
            introduction='Intro',
            methods='Methods',
            results='Results',
            conclusion='Conclusion',
        )

        response = self.client.get(reverse('dashboard_abstract_center'), {
            'event': self.event.id,
            'q': 'Biomarkers',
            'status': 'pending',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.abstract.title)
        self.assertNotContains(response, 'Different Abstract')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_abstract_center_approves_presentation_and_sends_email(self):
        self.abstract.approved_for_presentation = False
        self.abstract.save(update_fields=['approved_for_presentation', 'updated_at'])
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_abstract_center'), {
            'abstract_action': 'approve_presentation',
            'abstract_ids': [self.abstract.id],
            'event': self.event.id,
            'status': 'pending',
        })

        self.assertEqual(response.status_code, 302)
        self.abstract.refresh_from_db()
        self.assertTrue(self.abstract.approved_for_presentation)
        self.assertFalse(self.abstract.approved_for_poster)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Abstract Approved for Presentation', mail.outbox[0].subject)

    def test_abstract_center_admin_can_create_abstract(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_abstract_center'), {
            'abstract_action': 'create_abstract',
            'abstract-event': self.event.id,
            'abstract-user': self.user.id,
            'abstract-title': 'Admin Entered Abstract',
            'abstract-authors': 'Admin Author',
            'abstract-institution': 'Admin Institute',
            'abstract-introduction': 'Introduction',
            'abstract-methods': 'Methods',
            'abstract-results': 'Results',
            'abstract-conclusion': 'Conclusion',
        })

        self.assertEqual(response.status_code, 302)
        abstract = AbstractSubmission.objects.get(title='Admin Entered Abstract')
        self.assertEqual(abstract.event, self.event)
        self.assertEqual(abstract.user, self.user)
        self.assertFalse(abstract.approved_for_presentation)
        self.assertFalse(abstract.approved_for_poster)

    def test_participant_center_requires_staff_and_renders_queue(self):
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Pending Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='pending@example.com',
            phone='01700000001',
            country='Bangladesh',
        )

        response = self.client.get(reverse('dashboard_participant_center'))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_participant_center'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Participant center')
        self.assertContains(response, participant.name)
        self.assertContains(response, 'Approved unpaid')

    def test_participant_center_filters_approved_unpaid(self):
        unpaid_participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Approved Unpaid',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='approvedunpaid@example.com',
            phone='01700000002',
            country='Bangladesh',
            approved=True,
        )
        paid_participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Paid Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='paid@example.com',
            phone='01700000003',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=unpaid_participant,
            event=self.event,
            merchant_invoice_number='REG-UNPAID',
            amount='500.00',
            status='unpaid',
        )
        PaymentStatus.objects.create(
            participant=paid_participant,
            event=self.event,
            merchant_invoice_number='REG-PAID',
            amount='500.00',
            status='completed',
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_participant_center'), {'status': 'approved_unpaid'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, unpaid_participant.name)
        self.assertNotContains(response, paid_participant.name)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_participant_center_staff_can_add_pending_participant(self):
        self.client.force_login(self.staff_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('dashboard_participant_center'), {
                'participant_action': 'create_participant',
                'participant_lookup_completed': '1',
                'participant_lookup_email': 'manual.request@example.com',
                'participant-event': self.event.id,
                'participant-registration_type': 'regular',
                'participant-name': 'Manual Request',
                'participant-email': 'manual.request@example.com',
                'participant-phone': '01700000011',
                'participant-degree': 'MBBS',
                'participant-year_of_graduation': 2021,
                'participant-department_name': 'Clinical Oncology',
                'participant-organization': 'Request Hospital',
                'participant-country': 'Bangladesh',
                'participant-BMDC_registration_number': 'A-12345',
                'participant-approval_state': 'pending',
            })

        self.assertEqual(response.status_code, 302)
        participant = Participant.objects.get(email='manual.request@example.com', event=self.event)
        self.assertFalse(participant.approved)
        self.assertFalse(participant.denied)
        self.assertTrue(participant.user.has_usable_password())
        profile = UserProfile.objects.get(user=participant.user)
        self.assertEqual(profile.name, participant.name)
        self.assertEqual(profile.phone, participant.phone)
        self.assertFalse(PaymentStatus.objects.filter(participant=participant).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('profile and login account', mail.outbox[0].subject)

    def test_participant_center_email_lookup_loads_existing_profile(self):
        profile = UserProfile.objects.create(
            user=self.user,
            name='Existing Website User',
            email=self.user.email,
            phone='01700000014',
            country='Bangladesh',
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_participant_lookup'), {
            'email': profile.email,
            'event': self.event.id,
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['account_found'])
        self.assertTrue(payload['profile_found'])
        self.assertFalse(payload['already_registered'])
        self.assertEqual(payload['profile']['name'], profile.name)
        self.assertEqual(payload['profile']['phone'], profile.phone)

    def test_participant_center_live_lookup_matches_partial_name_or_email(self):
        profile = UserProfile.objects.create(
            user=self.user,
            name='Dynamic Search Person',
            email=self.user.email,
            phone='01700000016',
            country='Bangladesh',
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_participant_lookup'), {
            'q': 'dynamic sea',
            'event': self.event.id,
        })

        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(results[0]['email'], profile.email)
        self.assertEqual(results[0]['profile']['name'], profile.name)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_participant_center_staff_can_add_with_only_essential_details(self):
        self.client.force_login(self.staff_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('dashboard_participant_center'), {
                'participant_action': 'create_participant',
                'participant_lookup_completed': '1',
                'participant_lookup_email': 'essentials.only@example.com',
                'participant-event': self.event.id,
                'participant-registration_type': 'regular',
                'participant-name': 'Essentials Only',
                'participant-email': 'essentials.only@example.com',
                'participant-phone': '01700000017',
                'participant-degree': '',
                'participant-year_of_graduation': '',
                'participant-department_name': '',
                'participant-organization': '',
                'participant-country': 'Bangladesh',
                'participant-BMDC_registration_number': '',
                'participant-approval_state': 'pending',
            })

        self.assertEqual(response.status_code, 302)
        participant = Participant.objects.get(email='essentials.only@example.com')
        self.assertEqual(participant.degree, 'Not provided')
        self.assertEqual(participant.year_of_graduation, 0)
        self.assertEqual(participant.organization, 'Not provided')
        self.assertEqual(participant.department.name, 'Not specified')

    def test_participant_center_rejects_manual_creation_without_email_lookup(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_participant_center'), {
            'participant_action': 'create_participant',
            'participant-event': self.event.id,
            'participant-registration_type': 'regular',
            'participant-name': 'Unchecked Email',
            'participant-email': 'unchecked@example.com',
            'participant-phone': '01700000015',
            'participant-degree': 'MBBS',
            'participant-year_of_graduation': 2021,
            'participant-department_name': 'Clinical Oncology',
            'participant-organization': 'Request Hospital',
            'participant-country': 'Bangladesh',
            'participant-BMDC_registration_number': '',
            'participant-approval_state': 'pending',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check this email address before adding the participant.')
        self.assertFalse(Participant.objects.filter(email='unchecked@example.com').exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_participant_center_repairs_existing_user_without_profile(self):
        existing_user = User.objects.create_user(
            username='existing.profileless@example.com',
            email='existing.profileless@example.com',
            password='existing-password',
        )
        self.client.force_login(self.staff_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('dashboard_participant_center'), {
                'participant_action': 'create_participant',
                'participant_lookup_completed': '1',
                'participant_lookup_email': existing_user.email,
                'participant-event': self.event.id,
                'participant-registration_type': 'regular',
                'participant-name': 'Existing Profileless User',
                'participant-email': existing_user.email,
                'participant-phone': '01700000013',
                'participant-degree': 'MBBS',
                'participant-year_of_graduation': 2022,
                'participant-department_name': 'Medical Oncology',
                'participant-organization': 'Existing Hospital',
                'participant-country': 'Bangladesh',
                'participant-BMDC_registration_number': '',
                'participant-approval_state': 'pending',
            })

        self.assertEqual(response.status_code, 302)
        participant = Participant.objects.get(email=existing_user.email, event=self.event)
        self.assertEqual(participant.user, existing_user)
        self.assertTrue(UserProfile.objects.filter(user=existing_user).exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_participant_center_staff_can_add_and_approve_participant(self):
        self.event.amount = '500.00'
        self.event.save(update_fields=['amount'])
        self.client.force_login(self.staff_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('dashboard_participant_center'), {
                'participant_action': 'create_participant',
                'participant_lookup_completed': '1',
                'participant_lookup_email': 'immediate.approval@example.com',
                'participant-event': self.event.id,
                'participant-registration_type': 'regular',
                'participant-name': 'Immediate Approval',
                'participant-email': 'immediate.approval@example.com',
                'participant-phone': '01700000012',
                'participant-degree': 'MBBS',
                'participant-year_of_graduation': 2021,
                'participant-department_name': 'Clinical Oncology',
                'participant-organization': 'Request Hospital',
                'participant-country': 'Bangladesh',
                'participant-BMDC_registration_number': '',
                'participant-approval_state': 'approved',
            })

        self.assertEqual(response.status_code, 302)
        participant = Participant.objects.get(email='immediate.approval@example.com', event=self.event)
        self.assertTrue(participant.approved)
        self.assertTrue(participant.user.has_usable_password())
        payment_status = PaymentStatus.objects.get(participant=participant)
        self.assertEqual(payment_status.status, 'unpaid')
        self.assertEqual(str(payment_status.amount), '500.00')
        self.assertTrue(UserProfile.objects.filter(user=participant.user).exists())
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_participant_center_approves_and_creates_payment_status(self):
        self.event.payment_required = True
        self.event.amount = '500.00'
        self.event.save(update_fields=['payment_required', 'amount'])
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Approval Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='candidate@example.com',
            phone='01700000004',
            country='Bangladesh',
        )

        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_participant_center'), {
            'participant_action': 'approve',
            'participant_ids': [participant.id],
            'status': 'pending',
        })

        self.assertEqual(response.status_code, 302)
        participant.refresh_from_db()
        self.assertTrue(participant.approved)
        self.assertFalse(participant.denied)
        payment_status = PaymentStatus.objects.get(participant=participant, event=self.event)
        self.assertEqual(payment_status.status, 'unpaid')
        self.assertEqual(str(payment_status.amount), '500.00')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Approved', mail.outbox[0].subject)

    def test_payment_center_requires_staff_and_renders_event_and_membership_payments(self):
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Payment Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='payment@example.com',
            phone='01700000101',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=participant,
            event=self.event,
            merchant_invoice_number='REG-PAYMENT-CENTER',
            amount='500.00',
            status='unpaid',
        )
        profile = UserProfile.objects.create(
            user=self.user,
            name='Member Payment Candidate',
            email='memberpay@example.com',
            phone='01700000102',
            country='Bangladesh',
        )
        membership_type = MembershipType.objects.create(
            name='Annual',
            slug='annual-test',
            amount='1000.00',
            duration_years=1,
            is_active=True,
        )
        MembershipPayment.objects.create(
            user_profile=profile,
            membership_type=membership_type,
            merchant_invoice_number='MEM-PAYMENT-CENTER',
            amount='1000.00',
            status='pending',
        )

        response = self.client.get(reverse('dashboard_payment_center'))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_payment_center'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment center')
        self.assertContains(response, 'Payment Candidate')
        self.assertContains(response, 'Member Payment Candidate')

    def test_payment_center_updates_event_payment_without_emailing_invoice(self):
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Manual Payment',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='manualpayment@example.com',
            phone='01700000103',
            country='Bangladesh',
            approved=True,
        )
        payment = PaymentStatus.objects.create(
            participant=participant,
            event=self.event,
            merchant_invoice_number='REG-MANUAL',
            amount='500.00',
            status='unpaid',
        )

        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_payment_center'), {
            'payment_source': 'event',
            'payment_id': payment.id,
            'payment_action': 'update',
            'manual_status': 'completed',
            'manual_amount': '700.00',
            'manual_invoice_number': 'REG-MANUAL-UPDATED',
            'manual_transaction_id': 'PAY-123',
            'manual_trx_id': 'TRX-123',
            'source': 'event',
            'status': 'open',
        })

        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(str(payment.amount), '700.00')
        self.assertEqual(payment.merchant_invoice_number, 'REG-MANUAL-UPDATED')
        self.assertEqual(payment.transaction_id, 'PAY-123')
        self.assertEqual(payment.trxID, 'TRX-123')
        self.assertFalse(payment.email_sent)

    def test_corporate_center_renders_account_registration_and_attendee_workflow(self):
        access_request = CorporateAccountRequest.objects.create(
            company_name='Corporate Care Ltd',
            contact_name='Corporate Manager',
            contact_designation='Coordinator',
            email='corporate-care@example.com',
            phone='01700000120',
            note='Need group registration support.',
        )
        corporate_user = User.objects.create_user(
            username='corporate-care@example.com',
            email='corporate-care@example.com',
            password='password',
        )
        corporate_account = CorporateAccount.objects.create(
            user=corporate_user,
            source_request=access_request,
            company_name='Corporate Care Ltd',
            contact_name='Corporate Manager',
            contact_designation='Coordinator',
            email='corporate-care@example.com',
            phone='01700000120',
        )
        corporate_registration = CorporateEventRegistration.objects.create(
            corporate_account=corporate_account,
            event=self.event,
            total_attendees=1,
        )
        CorporateEventAttendee.objects.create(
            registration=corporate_registration,
            name='Corporate Attendee',
            email='corporate-attendee@example.com',
            phone='01700000121',
            organization='Corporate Care Ltd',
        )

        response = self.client.get(reverse('dashboard_corporate_center'))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_corporate_center'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Corporate Management')
        self.assertContains(response, 'Corporate account approval')
        self.assertContains(response, 'Corporate Care Ltd')
        self.assertContains(response, 'Corporate Attendee')
        self.assertContains(response, 'Create invoice for selected')

    def test_payment_center_renders_and_updates_corporate_payments(self):
        corporate_user = User.objects.create_user(
            username='corporate-pay@example.com',
            email='corporate-pay@example.com',
            password='password',
        )
        corporate_account = CorporateAccount.objects.create(
            user=corporate_user,
            company_name='Corporate Payment Ltd',
            contact_name='Payment Manager',
            email='corporate-pay@example.com',
            phone='01700000122',
        )
        corporate_registration = CorporateEventRegistration.objects.create(
            corporate_account=corporate_account,
            event=self.event,
            total_attendees=1,
            status='approved',
        )
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Corporate Paid Attendee',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Corporate Payment Ltd',
            email='corporate-paid-attendee@example.com',
            phone='01700000123',
            country='Bangladesh',
            approved=True,
        )
        attendee = CorporateEventAttendee.objects.create(
            registration=corporate_registration,
            participant=participant,
            matched_user=self.user,
            name=participant.name,
            email=participant.email,
            phone=participant.phone,
            organization=participant.organization,
            review_status='approved',
        )
        participant_payment = PaymentStatus.objects.create(
            participant=participant,
            event=self.event,
            merchant_invoice_number='CORP-PARTICIPANT-PAY',
            amount='500.00',
            status='unpaid',
        )
        corporate_payment = CorporatePayment.objects.create(
            corporate_registration=corporate_registration,
            corporate_account=corporate_account,
            event=self.event,
            amount='500.00',
            status='unpaid',
            merchant_invoice_number='CORP-DASH-PAY',
        )
        corporate_payment.attendees.add(attendee)

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_payment_center'), {'source': 'corporate', 'status': 'open'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Corporate Payment Ltd')
        self.assertContains(response, 'CORP-DASH-PAY')
        self.assertContains(response, 'Corporate payments')

        response = self.client.post(reverse('dashboard_payment_center'), {
            'payment_source': 'corporate',
            'payment_id': corporate_payment.id,
            'payment_action': 'update',
            'manual_status': 'completed',
            'manual_amount': '500.00',
            'manual_invoice_number': 'CORP-DASH-PAY-COMPLETE',
            'manual_transaction_id': 'CORP-TXN-1',
            'manual_trx_id': 'CORP-TRX-1',
            'source': 'corporate',
            'status': 'open',
        })

        self.assertEqual(response.status_code, 302)
        corporate_payment.refresh_from_db()
        participant_payment.refresh_from_db()
        self.assertEqual(corporate_payment.status, 'completed')
        self.assertEqual(corporate_payment.merchant_invoice_number, 'CORP-DASH-PAY-COMPLETE')
        self.assertEqual(corporate_payment.transaction_id, 'CORP-TXN-1')
        self.assertEqual(corporate_payment.trxID, 'CORP-TRX-1')
        self.assertEqual(participant_payment.status, 'completed')
        self.assertEqual(participant_payment.transaction_id, 'CORP-TXN-1')
        self.assertEqual(participant_payment.trxID, 'CORP-TRX-1')

    def test_registration_kit_center_issues_only_completed_approved_participants(self):
        completed_participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Completed Kit Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='kitcompleted@example.com',
            phone='01700000104',
            country='Bangladesh',
            approved=True,
        )
        completed_payment = PaymentStatus.objects.create(
            participant=completed_participant,
            event=self.event,
            merchant_invoice_number='KIT-COMPLETED',
            amount='500.00',
            status='completed',
        )
        unpaid_participant = Participant.objects.create(
            user=self.staff_user,
            event=self.event,
            name='Unpaid Kit Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='kitunpaid@example.com',
            phone='01700000105',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=unpaid_participant,
            event=self.event,
            merchant_invoice_number='KIT-UNPAID',
            amount='500.00',
            status='unpaid',
        )
        legacy_paid_participant = Participant.objects.create(
            user=self.staff_user,
            event=self.event,
            name='Legacy Paid Kit Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='kitpaidlegacy@example.com',
            phone='01700000106',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=legacy_paid_participant,
            event=self.event,
            merchant_invoice_number='KIT-LEGACY-PAID',
            amount='500.00',
            status='paid',
        )

        response = self.client.get(reverse('dashboard_registration_kit_center'))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('dashboard_registration_kit_center'), {'event': self.event.id, 'kit_status': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Completed Kit Candidate')
        self.assertNotContains(response, 'Unpaid Kit Candidate')
        self.assertNotContains(response, 'Legacy Paid Kit Candidate')
        self.assertContains(response, 'Scan QR')

        response = self.client.post(reverse('dashboard_registration_kit_center'), {
            'event': self.event.id,
            'kit_status': 'all',
            'payment_id': completed_payment.id,
            'kit_action': 'issue',
        })
        self.assertEqual(response.status_code, 302)
        kit = RegistrationKit.objects.get(payment_status=completed_payment)
        self.assertEqual(kit.status, 'issued')
        self.assertIsNotNone(kit.issued_at)

        kit.status = 'not_issued'
        kit.issued_at = None
        kit.save(update_fields=['status', 'issued_at'])
        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root, SITE_URL='https://beta.bsbcs.info'):
                invoice_path = generate_invoice(completed_participant, self.event, completed_payment)
                completed_payment.refresh_from_db()
                self.assertTrue(os.path.exists(invoice_path))
                self.assertTrue(os.path.exists(completed_payment.qr_code.path))
                self.assertIn('completed-kit-candidate', completed_payment.qr_code.name)
                self.assertIn('kitcompleted-at-example-com', completed_payment.qr_code.name)
                self.assertIn(str(completed_payment.qr_token), registration_qr_payload(completed_payment))

                response = self.client.post(reverse('dashboard_registration_kit_center'), {
                    'event': self.event.id,
                    'kit_status': 'all',
                    'scan_code': registration_qr_payload(completed_payment),
                    'kit_action': 'scan_issue',
                })
                self.assertEqual(response.status_code, 302)
                kit.refresh_from_db()
                self.assertEqual(kit.status, 'issued')
                self.assertIsNotNone(kit.issued_at)

    def test_registration_kit_center_downloads_selected_qr_codes(self):
        participant = Participant.objects.create(
            user=self.user,
            event=self.event,
            name='QR Download Candidate',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='qrdownload@example.com',
            phone='01700000114',
            country='Bangladesh',
            approved=True,
        )
        payment = PaymentStatus.objects.create(
            participant=participant,
            event=self.event,
            merchant_invoice_number='QR-DOWNLOAD-1',
            amount='500.00',
            status='completed',
        )
        second_participant = Participant.objects.create(
            user=self.staff_user,
            event=self.event,
            name='Second QR Candidate',
            degree='MBBS',
            year_of_graduation=2021,
            department=self.department,
            organization='Second Hospital',
            email='secondqr@example.com',
            phone='01700000115',
            country='Bangladesh',
            approved=True,
        )
        PaymentStatus.objects.create(
            participant=second_participant,
            event=self.event,
            merchant_invoice_number='QR-DOWNLOAD-2',
            amount='500.00',
            status='completed',
        )

        self.client.force_login(self.staff_user)
        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root, SITE_URL='https://beta.bsbcs.info'):
                response = self.client.post(reverse('dashboard_registration_kit_center'), {
                    'event': self.event.id,
                    'kit_status': 'all',
                    'qr_action': 'download_selected',
                    'qr_payment_ids': [payment.id],
                })

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'application/zip')
                payment.refresh_from_db()
                self.assertTrue(payment.qr_code)
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    names = archive.namelist()
                self.assertEqual(len(names), 1)
                self.assertIn('qr-download-candidate', names[0])
                self.assertIn('qrdownload-at-example-com', names[0])

                response = self.client.post(reverse('dashboard_registration_kit_center'), {
                    'event': self.event.id,
                    'kit_status': 'all',
                    'qr_action': 'download_selected',
                    'selection_scope': 'all_filtered',
                    'qr_payment_ids': [payment.id],
                })
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    names = archive.namelist()
                self.assertEqual(len(names), 2)

    def test_add_setup_actions(self):
        self.client.force_login(self.staff_user)
        url = reverse('dashboard_program_session_builder')

        # Add Day action
        post_data = {
            'event': self.event.id,
            'setup_action': 'add_day',
            'name': 'Day 2',
            'date': '2026-05-22',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProgramDay.objects.filter(name='Day 2').exists())

        # Add Room action
        post_data = {
            'event': self.event.id,
            'setup_action': 'add_room',
            'name': 'Seminar Room 1',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(HallRoom.objects.filter(name='Seminar Room 1').exists())

        # Add Slot action
        post_data = {
            'event': self.event.id,
            'setup_action': 'add_slot',
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '10:00',
            'end_time': '11:00',
            'slot_type': 'session',
            'label': 'Session Slot 2',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TimeSlot.objects.filter(label='Session Slot 2').exists())

        # Add Person action
        post_data = {
            'event': self.event.id,
            'setup_action': 'add_person',
            'name': 'Dr. Robert Brown',
            'degree': 'MD',
            'designation': 'Consultant',
            'institution': 'Apollo Hospital',
            'email': 'robert@brown.com',
            'phone': '999999',
            'country': 'Bangladesh',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        added_person = ProgramPerson.objects.get(name='Dr. Robert Brown')
        self.assertTrue(added_person.events.filter(pk=self.event.id).exists())

    def test_builder_can_add_program_person_from_user_profile(self):
        self.client.force_login(self.staff_user)
        profile = UserProfile.objects.create(
            user=self.user,
            name='Dr. Existing Profile',
            email='existing-profile@test.com',
            phone='01700000000',
            country='Bangladesh',
        )
        url = reverse('dashboard_program_session_builder')

        search_response = self.client.get(f'{url}?event={self.event.id}&profile_query=Existing')

        self.assertContains(search_response, 'Find a website user')
        self.assertContains(search_response, profile.name)
        self.assertContains(search_response, profile.email)

        response = self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'add_profile_person',
            'profile_id': profile.id,
        })

        self.assertEqual(response.status_code, 302)
        person = ProgramPerson.objects.get(profile=profile)
        self.assertEqual(person.name, profile.name)
        self.assertEqual(person.email, profile.email)
        self.assertEqual(person.phone, profile.phone)
        self.assertTrue(person.events.filter(pk=self.event.id).exists())

    def test_session_role_selectors_use_people_added_to_selected_event(self):
        outsider = ProgramPerson.objects.create(
            name='Dr. Global Only',
            email='global-only@test.com',
        )

        form = ProgramSessionBuilderForm(event=self.event)

        for field_name in ('chairpersons', 'moderators', 'panelists'):
            self.assertIn(self.person1, form.fields[field_name].queryset)
            self.assertNotIn(outsider, form.fields[field_name].queryset)

    def test_builder_can_remove_program_person_from_selected_event_without_deleting_person(self):
        self.client.force_login(self.staff_user)
        session = ProgramSession.objects.create(
            event=self.event,
            time_slot=self.time_slot,
            program_day=self.day,
            hall_room=self.room,
            title='Event Session',
            start_time=self.time_slot.start_time,
            end_time=self.time_slot.end_time,
        )
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
        )
        item = ProgramSessionItem.objects.create(session=session, title='Talk in event')
        ProgramItemFaculty.objects.create(
            item=item,
            person=self.person1,
            role=ProgramItemFaculty.ROLE_SPEAKER,
        )

        page_response = self.client.get(
            f"{reverse('dashboard_program_session_builder')}?event={self.event.id}"
        )
        self.assertContains(page_response, 'People already in BCS Conference 2026 program')
        self.assertContains(page_response, 'Global library')
        self.assertContains(page_response, self.person1.name)

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'setup_action': 'remove_person',
            'program_person_id': self.person1.id,
        })

        self.assertRedirects(
            response,
            f"{reverse('dashboard_program_session_builder')}?event={self.event.id}&program_person_modal=1",
            fetch_redirect_response=False,
        )
        self.assertTrue(ProgramPerson.objects.filter(pk=self.person1.id).exists())
        self.assertFalse(ProgramSessionFaculty.objects.filter(session=session, person=self.person1).exists())
        self.assertFalse(ProgramItemFaculty.objects.filter(item=item, person=self.person1).exists())

    def test_inline_remove_program_person_stays_event_scoped_and_returns_modal_panel(self):
        self.client.force_login(self.staff_user)
        session = ProgramSession.objects.create(
            event=self.event,
            time_slot=self.time_slot,
            program_day=self.day,
            hall_room=self.room,
            title='Protected Session',
            start_time=self.time_slot.start_time,
            end_time=self.time_slot.end_time,
        )
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
        )
        other_event = Event.objects.create(
            name='Other BCS Program',
            slogan='Other program',
            year=2027,
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 1),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        other_session = ProgramSession.objects.create(
            event=other_event,
            title='Other Event Session',
        )
        ProgramSessionFaculty.objects.create(
            session=other_session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_MODERATOR,
        )

        response = self.client.post(reverse('dashboard_program_person_remove'), {
                'event': self.event.id,
                'program_person_id': self.person1.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'removed from BCS Conference 2026 program roles')
        self.assertContains(response, 'People in this selected event')
        self.assertContains(response, 'id="program-person-remove-panel"')
        self.assertTrue(ProgramPerson.objects.filter(pk=self.person1.id).exists())
        self.assertFalse(ProgramSessionFaculty.objects.filter(session=session, person=self.person1).exists())
        self.assertTrue(ProgramSessionFaculty.objects.filter(session=other_session, person=self.person1).exists())

    def test_program_profile_live_search_matches_profile_name(self):
        self.client.force_login(self.staff_user)
        profile = UserProfile.objects.create(
            user=self.user,
            name='Dr. Live Search Faculty',
            email='live-faculty@test.com',
            phone='01700000001',
            country='Bangladesh',
        )

        short_response = self.client.get(reverse('dashboard_program_profile_search'), {
            'event': self.event.id,
            'profile_query': 'D',
        })
        response = self.client.get(reverse('dashboard_program_profile_search'), {
            'event': self.event.id,
            'profile_query': 'Live Search',
        })

        self.assertNotContains(short_response, profile.name)
        self.assertContains(short_response, 'Type at least two letters')
        self.assertContains(response, profile.name)
        self.assertContains(response, profile.email)
        self.assertContains(response, 'Add from Profile')

    def test_program_profile_live_add_returns_success_without_builder_redirect(self):
        self.client.force_login(self.staff_user)
        profile = UserProfile.objects.create(
            user=self.user,
            name='Dr. Inline Add',
            email='inline-add@test.com',
            phone='01700000002',
            country='Bangladesh',
        )

        response = self.client.post(reverse('dashboard_program_profile_add'), {
            'event': self.event.id,
            'profile_id': profile.id,
            'profile_query': 'Inline',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is added to the program person library for BCS Conference 2026.')
        self.assertContains(response, profile.name)
        self.assertContains(response, 'id="program-event-people-count" hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="program-event-people-panel" hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="program-person-remove-panel" hx-swap-oob="outerHTML"')
        self.assertTrue(ProgramPerson.objects.filter(profile=profile).exists())

    def test_generate_slots_redirects_to_one_time_preview(self):
        self.client.force_login(self.staff_user)
        url = reverse('dashboard_program_session_builder')
        response = self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'generate_slots',
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '10:00',
            'end_time': '11:00',
            'slot_minutes': 30,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{url}?event={self.event.id}")

        preview_response = self.client.get(response.url)
        self.assertContains(preview_response, 'data-open-on-load="true"')
        self.assertContains(preview_response, 'Adjust before saving time slots')

        refreshed_response = self.client.get(response.url)
        self.assertNotContains(refreshed_response, 'id="generated-slot-preview-modal" class="setup-modal" hidden data-open-on-load="true"')

    def test_saved_generated_session_slot_creates_child_talk_slots(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'setup_action': 'save_generated_slots',
            'generated_program_day': self.day.id,
            'generated_hall_room': self.room.id,
            'generated-TOTAL_FORMS': 1,
            'generated-INITIAL_FORMS': 0,
            'generated-MIN_NUM_FORMS': 0,
            'generated-MAX_NUM_FORMS': 240,
            'generated-0-start_time': '10:00',
            'generated-0-end_time': '12:00',
            'generated-0-slot_type': TimeSlot.SLOT_SESSION,
            'generated-0-talk_slot_minutes': 20,
            'generated-0-label': 'Workshop',
        })

        self.assertEqual(response.status_code, 302)
        generated_parent = TimeSlot.objects.get(label='Workshop')
        self.assertEqual(generated_parent.talk_slots.count(), 6)
        self.assertTrue(generated_parent.talk_slots.filter(start_time=time(10, 0), end_time=time(10, 20)).exists())
        self.assertTrue(generated_parent.talk_slots.filter(start_time=time(11, 40), end_time=time(12, 0)).exists())

    def test_setup_day_and_room_can_be_corrected_from_builder(self):
        self.client.force_login(self.staff_user)
        url = reverse('dashboard_program_session_builder')

        response = self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'edit_day',
            'program_day_id': self.day.id,
            'name': 'Opening Day',
            'date': '2026-05-21',
        })
        self.assertEqual(response.status_code, 302)
        self.day.refresh_from_db()
        self.assertEqual(self.day.name, 'Opening Day')

        response = self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'edit_room',
            'hall_room_id': self.room.id,
            'name': 'Ball Room',
        })
        self.assertEqual(response.status_code, 302)
        self.room.refresh_from_db()
        self.assertEqual(self.room.name, 'Ball Room')

        unused_day = ProgramDay.objects.create(event=self.event, name='Unused Day', date=date(2026, 5, 23))
        unused_room = HallRoom.objects.create(event=self.event, name='Unused Room', location='Dhaka')
        self.assertEqual(self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'delete_day',
            'program_day_id': unused_day.id,
        }).status_code, 302)
        self.assertFalse(ProgramDay.objects.filter(pk=unused_day.id).exists())
        self.assertEqual(self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'delete_room',
            'hall_room_id': unused_room.id,
        }).status_code, 302)
        self.assertFalse(HallRoom.objects.filter(pk=unused_room.id).exists())

        self.client.post(url, {
            'event': self.event.id,
            'setup_action': 'delete_day',
            'program_day_id': self.day.id,
        })
        self.assertTrue(ProgramDay.objects.filter(pk=self.day.id).exists())

    def test_create_program_session_success(self):
        self.client.force_login(self.staff_user)
        url = reverse('dashboard_program_session_builder')

        # Form data for session and formset for items
        post_data = {
            'event': self.event.id,
            'title': 'Inaugural Session on Heart Failure',
            'description': 'Keynote session highlighting modern therapeutics.',
            'order': 1,
            'time_slot': self.time_slot.id,
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [self.person1.id],
            'moderators': [self.person2.id],
            'panelists': [],
            
            # Management Form fields
            'items-TOTAL_FORMS': 2,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            
            # Item 1: Linked abstract
            'items-0-order': 1,
            'items-0-start_time': '09:05',
            'items-0-end_time': '09:30',
            'items-0-title': 'Novel Biomarkers in Heart Failure',
            'items-0-abstract_submission': self.abstract.id,
            'items-0-speakers': [self.person1.id],
            'items-0-presenters': [self.person1.id],
            
            # Item 2: Manual text session item
            'items-1-order': 2,
            'items-1-start_time': '09:30',
            'items-1-end_time': '09:55',
            'items-1-title': 'Panel Q&A Discussion',
            'items-1-abstract_submission': '',
            'items-1-speakers': [self.person2.id],
            'items-1-presenters': [],
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Verify session was created
        session = ProgramSession.objects.filter(title='Inaugural Session on Heart Failure').first()
        self.assertIsNotNone(session)
        self.assertEqual(session.description, 'Keynote session highlighting modern therapeutics.')
        
        # Verify faculty assignments
        self.assertTrue(ProgramSessionFaculty.objects.filter(session=session, person=self.person1, role=ProgramSessionFaculty.ROLE_CHAIRPERSON).exists())
        self.assertTrue(ProgramSessionFaculty.objects.filter(session=session, person=self.person2, role=ProgramSessionFaculty.ROLE_MODERATOR).exists())

        # Verify session items
        items = ProgramSessionItem.objects.filter(session=session).order_by('order')
        self.assertEqual(items.count(), 2)
        
        item1 = items[0]
        self.assertEqual(item1.title, 'Novel Biomarkers in Heart Failure')
        self.assertEqual(item1.abstract_submission, self.abstract)
        self.assertTrue(ProgramItemFaculty.objects.filter(item=item1, person=self.person1, role=ProgramItemFaculty.ROLE_SPEAKER).exists())
        
        item2 = items[1]
        self.assertEqual(item2.title, 'Panel Q&A Discussion')
        self.assertIsNone(item2.abstract_submission)
        self.assertTrue(ProgramItemFaculty.objects.filter(item=item2, person=self.person2, role=ProgramItemFaculty.ROLE_SPEAKER).exists())

    def test_program_item_can_use_generated_talk_slot(self):
        self.client.force_login(self.staff_user)
        talk_slot = ProgramTalkSlot.objects.create(
            time_slot=self.time_slot,
            start_time=time(9, 20),
            end_time=time(9, 40),
            order=2,
        )

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'title': 'Talk slot session',
            'description': '',
            'order': 1,
            'time_slot': self.time_slot.id,
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [],
            'moderators': [],
            'panelists': [],
            'items-TOTAL_FORMS': 1,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            'items-0-order': 1,
            'items-0-talk_slot': talk_slot.id,
            'items-0-start_time': '',
            'items-0-end_time': '',
            'items-0-title': 'Generated talk window',
            'items-0-abstract_submission': '',
            'items-0-speakers': [],
            'items-0-presenters': [],
        })

        self.assertEqual(response.status_code, 302)
        item = ProgramSessionItem.objects.get(title='Generated talk window')
        self.assertEqual(item.talk_slot, talk_slot)
        self.assertEqual(item.start_time, time(9, 20))
        self.assertEqual(item.end_time, time(9, 40))

    def test_builder_blocks_people_in_overlapping_parallel_sessions(self):
        self.client.force_login(self.staff_user)
        parallel_room = HallRoom.objects.create(
            event=self.event,
            name='Parallel Hall',
            location='First Floor',
        )
        parallel_slot = TimeSlot.objects.create(
            event=self.event,
            program_day=self.day,
            hall_room=parallel_room,
            start_time=time(9, 0),
            end_time=time(10, 0),
            slot_type=TimeSlot.SLOT_SESSION,
        )
        existing_session = ProgramSession.objects.create(
            event=self.event,
            time_slot=self.time_slot,
            title='Hall A session',
        )
        ProgramSessionFaculty.objects.create(
            session=existing_session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
            order=1,
        )

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'title': 'Hall B session',
            'description': '',
            'order': 1,
            'time_slot': parallel_slot.id,
            'program_day': self.day.id,
            'hall_room': parallel_room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [],
            'moderators': [],
            'panelists': [],
            'items-TOTAL_FORMS': 1,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            'items-0-order': 1,
            'items-0-talk_slot': '',
            'items-0-start_time': '09:20',
            'items-0-end_time': '09:40',
            'items-0-title': 'Conflicting parallel talk',
            'items-0-abstract_submission': '',
            'items-0-speakers': [self.person1.id],
            'items-0-presenters': [],
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scheduling conflict')
        self.assertContains(response, self.person1.name)
        self.assertFalse(ProgramSession.objects.filter(title='Hall B session').exists())

    def test_parallel_sessions_are_marked_on_schedule_board(self):
        self.client.force_login(self.staff_user)
        parallel_room = HallRoom.objects.create(
            event=self.event,
            name='Parallel Hall',
            location='First Floor',
        )
        parallel_slot = TimeSlot.objects.create(
            event=self.event,
            program_day=self.day,
            hall_room=parallel_room,
            start_time=time(9, 30),
            end_time=time(10, 30),
            slot_type=TimeSlot.SLOT_SESSION,
        )
        ProgramSession.objects.create(event=self.event, time_slot=self.time_slot, title='Hall A session')
        ProgramSession.objects.create(event=self.event, time_slot=parallel_slot, title='Hall B session')

        response = self.client.get(f"{reverse('dashboard_program_session_builder')}?event={self.event.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'title="Another hall has an overlapping session in this time window.">Parallel</span>',
            count=2,
            html=False,
        )

    def test_session_roles_do_not_reuse_same_person(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'title': 'Duplicate role session',
            'description': '',
            'order': 1,
            'time_slot': self.time_slot.id,
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [self.person1.id],
            'moderators': [self.person1.id],
            'panelists': [],
            'items-TOTAL_FORMS': 1,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            'items-0-order': '',
            'items-0-talk_slot': '',
            'items-0-start_time': '',
            'items-0-end_time': '',
            'items-0-title': '',
            'items-0-abstract_submission': '',
            'items-0-speakers': [],
            'items-0-presenters': [],
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Use each person once across chairpersons, moderators, and panelists.')
        self.assertContains(response, 'Fix before saving')
        self.assertFalse(ProgramSession.objects.filter(title='Duplicate role session').exists())

    def test_talks_can_reuse_same_person_inside_one_session(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'title': 'Talk reuse session',
            'description': '',
            'order': 1,
            'time_slot': self.time_slot.id,
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [],
            'moderators': [],
            'panelists': [],
            'items-TOTAL_FORMS': 2,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            'items-0-order': 1,
            'items-0-talk_slot': '',
            'items-0-start_time': '09:05',
            'items-0-end_time': '09:25',
            'items-0-title': 'First talk',
            'items-0-abstract_submission': '',
            'items-0-speakers': [self.person1.id],
            'items-0-presenters': [],
            'items-1-order': 2,
            'items-1-talk_slot': '',
            'items-1-start_time': '09:30',
            'items-1-end_time': '09:50',
            'items-1-title': 'Second talk',
            'items-1-abstract_submission': '',
            'items-1-speakers': [self.person1.id],
            'items-1-presenters': [],
        })

        self.assertEqual(response.status_code, 302)
        session = ProgramSession.objects.get(title='Talk reuse session')
        self.assertEqual(
            ProgramItemFaculty.objects.filter(
                item__session=session,
                person=self.person1,
                role=ProgramItemFaculty.ROLE_SPEAKER,
            ).count(),
            2,
        )

    def test_edit_program_session_success(self):
        self.client.force_login(self.staff_user)
        
        # Pre-create a session
        session = ProgramSession.objects.create(
            event=self.event,
            title="Original Session Title",
            time_slot=self.time_slot,
            program_day=self.day,
            hall_room=self.room,
            start_time=time(9, 0),
            end_time=time(10, 0),
            order=1
        )
        # Pre-create a faculty role
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
            order=1
        )
        # Pre-create a session item
        item = ProgramSessionItem.objects.create(
            session=session,
            title="Original Talk Title",
            order=1
        )
        ProgramItemFaculty.objects.create(
            item=item,
            person=self.person1,
            role=ProgramItemFaculty.ROLE_SPEAKER,
            order=1
        )

        url = reverse('dashboard_program_session_builder')

        # Edit session POST data
        post_data = {
            'session_id': session.id,
            'event': self.event.id,
            'title': 'Updated Session Title',
            'description': 'Updated description.',
            'order': 5,
            'time_slot': self.time_slot.id,
            'program_day': self.day.id,
            'hall_room': self.room.id,
            'start_time': '09:00',
            'end_time': '10:00',
            'chairpersons': [self.person2.id],  # Swapped person1 for person2
            'moderators': [],
            'panelists': [],
            
            # Management Form fields
            'items-TOTAL_FORMS': 1,
            'items-INITIAL_FORMS': 0,
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            
            # Item 1 (New set of items replaces old completely)
            'items-0-order': 1,
            'items-0-start_time': '09:10',
            'items-0-end_time': '09:40',
            'items-0-title': 'Updated Talk Title',
            'items-0-abstract_submission': '',
            'items-0-speakers': [self.person2.id],
            'items-0-presenters': [],
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Refresh from DB
        session.refresh_from_db()
        self.assertEqual(session.title, 'Updated Session Title')
        self.assertEqual(session.order, 5)

        # Verify old chairperson role was deleted, and new one created
        self.assertFalse(ProgramSessionFaculty.objects.filter(session=session, person=self.person1, role=ProgramSessionFaculty.ROLE_CHAIRPERSON).exists())
        self.assertTrue(ProgramSessionFaculty.objects.filter(session=session, person=self.person2, role=ProgramSessionFaculty.ROLE_CHAIRPERSON).exists())

        # Verify old item was removed and replaced atomically
        self.assertFalse(ProgramSessionItem.objects.filter(title='Original Talk Title').exists())
        updated_items = ProgramSessionItem.objects.filter(session=session)
        self.assertEqual(updated_items.count(), 1)
        self.assertEqual(updated_items[0].title, 'Updated Talk Title')
        self.assertTrue(ProgramItemFaculty.objects.filter(item=updated_items[0], person=self.person2, role=ProgramItemFaculty.ROLE_SPEAKER).exists())

    def test_delete_program_session_success(self):
        self.client.force_login(self.staff_user)

        # Pre-create session
        session = ProgramSession.objects.create(
            event=self.event,
            title="To Be Deleted Session",
            time_slot=self.time_slot,
            program_day=self.day,
            hall_room=self.room,
            order=1
        )
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON
        )
        item = ProgramSessionItem.objects.create(
            session=session,
            title="To Be Deleted Item",
            order=1
        )

        url = reverse('dashboard_program_session_builder')
        post_data = {
            'event': self.event.id,
            'setup_action': 'delete_session',
            'session_id': session.id
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        # Verify session and dependent details are removed
        self.assertFalse(ProgramSession.objects.filter(id=session.id).exists())
        self.assertFalse(ProgramSessionFaculty.objects.filter(session=session).exists())
        self.assertFalse(ProgramSessionItem.objects.filter(session=session).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_program_person_admin_action_sends_one_assignment_summary_email(self):
        self.staff_user.is_superuser = True
        self.staff_user.save(update_fields=['is_superuser'])
        self.client.force_login(self.staff_user)

        session = ProgramSession.objects.create(
            event=self.event,
            time_slot=self.time_slot,
            title='Opening Scientific Session',
            order=1,
        )
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
            order=1,
        )
        item = ProgramSessionItem.objects.create(
            session=session,
            title='Biomarker Update',
            start_time=time(9, 10),
            end_time=time(9, 30),
            order=1,
        )
        ProgramItemFaculty.objects.create(
            item=item,
            person=self.person1,
            role=ProgramItemFaculty.ROLE_SPEAKER,
            order=1,
        )

        second_slot = TimeSlot.objects.create(
            event=self.event,
            program_day=self.day,
            hall_room=self.room,
            start_time=time(10, 0),
            end_time=time(11, 0),
            slot_type=TimeSlot.SLOT_SESSION,
            label='Session Slot 2',
        )
        second_session = ProgramSession.objects.create(
            event=self.event,
            time_slot=second_slot,
            title='Closing Scientific Session',
            order=2,
        )
        ProgramSessionFaculty.objects.create(
            session=second_session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_MODERATOR,
            order=1,
        )

        response = self.client.post(
            reverse('admin:registration_programperson_changelist'),
            {
                'action': 'send_program_assignment_emails',
                '_selected_action': [self.person1.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.person1.email])
        self.assertIn('Program Participation Details - BCS Conference 2026', mail.outbox[0].subject)
        self.assertIn('2 sessions included', mail.outbox[0].body)
        self.assertIn('Opening Scientific Session', mail.outbox[0].body)
        self.assertIn('Closing Scientific Session', mail.outbox[0].body)
        self.assertIn('Chairperson', mail.outbox[0].body)
        self.assertIn('Speaker', mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_program_builder_sends_selected_event_assignment_email(self):
        self.client.force_login(self.staff_user)
        session = ProgramSession.objects.create(
            event=self.event,
            time_slot=self.time_slot,
            title='Event Scoped Session',
            order=1,
        )
        ProgramSessionFaculty.objects.create(
            session=session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_PANELIST,
            order=1,
        )

        second_event = Event.objects.create(
            name='Other Conference',
            slogan='Other program',
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 1, 1),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        second_day = ProgramDay.objects.create(
            event=second_event,
            name='Day 1',
            date=date(2027, 1, 1),
        )
        second_room = HallRoom.objects.create(
            event=second_event,
            name='Other Hall',
            location='Dhaka',
        )
        second_slot = TimeSlot.objects.create(
            event=second_event,
            program_day=second_day,
            hall_room=second_room,
            start_time=time(12, 0),
            end_time=time(13, 0),
            slot_type=TimeSlot.SLOT_SESSION,
        )
        second_session = ProgramSession.objects.create(
            event=second_event,
            time_slot=second_slot,
            title='Do Not Include Session',
            order=1,
        )
        ProgramSessionFaculty.objects.create(
            session=second_session,
            person=self.person1,
            role=ProgramSessionFaculty.ROLE_CHAIRPERSON,
            order=1,
        )

        builder_url = f"{reverse('dashboard_program_session_builder')}?event={self.event.id}"
        page_response = self.client.get(builder_url)
        self.assertContains(page_response, 'Email Program Details')
        self.assertContains(page_response, 'Event Scoped Session')

        response = self.client.post(reverse('dashboard_program_session_builder'), {
            'event': self.event.id,
            'setup_action': 'send_program_person_emails',
            'program_person_ids': [self.person1.id],
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, builder_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Event Scoped Session', mail.outbox[0].body)
        self.assertIn('Panelist', mail.outbox[0].body)
        self.assertNotIn('Do Not Include Session', mail.outbox[0].body)
        email_log = ProgramPersonEmailLog.objects.get(event=self.event, person=self.person1)
        self.assertEqual(email_log.send_count, 1)
        self.assertEqual(email_log.last_sent_by, self.staff_user)
        self.assertEqual(email_log.last_session_count, 1)
        self.assertEqual(email_log.last_talk_count, 0)

        page_response = self.client.get(builder_url)
        self.assertContains(page_response, 'Already sent')
        self.assertContains(page_response, 'Sent')

    def test_program_builder_event_context_lists_active_events_only(self):
        self.client.force_login(self.staff_user)
        closed_event = Event.objects.create(
            name='Closed Builder Event',
            slogan='Closed program',
            year=2025,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            location='Dhaka',
            event_status='closed',
            registration='Closed',
        )
        upcoming_event = Event.objects.create(
            name='Upcoming Builder Event',
            slogan='Upcoming program',
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 1, 2),
            location='Dhaka',
            event_status='upcoming',
            registration='Open',
        )

        response = self.client.get(reverse('dashboard_program_session_builder'))

        self.assertContains(response, self.event.name)
        self.assertNotContains(response, closed_event.name)
        self.assertNotContains(response, upcoming_event.name)

    def test_program_builder_ignores_inactive_selected_event(self):
        self.client.force_login(self.staff_user)
        closed_event = Event.objects.create(
            name='Closed Selected Event',
            slogan='Closed selected program',
            year=2025,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 2),
            location='Dhaka',
            event_status='closed',
            registration='Closed',
        )

        response = self.client.get(f"{reverse('dashboard_program_session_builder')}?event={closed_event.id}")

        self.assertContains(response, 'Choose an event before building schedule.')
        self.assertNotContains(response, f'Prepare {closed_event.name}')


class PhoneValidationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='phone-user', password='password', email='phone-user@example.com')
        self.event = Event.objects.create(
            name='Phone Validation Event',
            slogan='Phone checks',
            year=2026,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        self.department = Department.objects.create(event=self.event, name='Medicine')

    def test_normalize_phone_number_accepts_bangladesh_local_mobile(self):
        self.assertEqual(normalize_phone_number('01911269258', 'Bangladesh'), '8801911269258')

    def test_user_profile_form_rejects_text_phone_for_bangladesh(self):
        form = UserProfileForm(data={
            'name': 'Invalid Phone User',
            'email': 'invalid-phone@example.com',
            'password': 'secret123',
            'phone': 'abc123',
            'country': 'Bangladesh',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_user_profile_form_normalizes_bangladesh_phone(self):
        form = UserProfileForm(data={
            'name': 'Valid Phone User',
            'email': 'valid-phone@example.com',
            'password': 'secret123',
            'phone': '01911269258',
            'country': 'Bangladesh',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['phone'], '8801911269258')

    def test_registration_form_blocks_duplicate_normalized_phone_per_event(self):
        Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Existing Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Test Hospital',
            email='existing@example.com',
            phone='8801911269258',
            country='Bangladesh',
        )

        form = RegistrationForm(data={
            'name': 'New Participant',
            'degree': 'MBBS',
            'email': 'new@example.com',
            'phone': '01911269258',
            'year_of_graduation': 2021,
            'department_name': 'Medicine',
            'organization': 'Another Hospital',
            'country': 'Bangladesh',
            'BMDC_registration_number': '',
        }, event=self.event)

        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_create_profile_view_does_not_save_invalid_phone(self):
        login_user = User.objects.create_user(username='login-user', password='password', email='login-user@example.com')
        self.client.force_login(login_user)

        response = self.client.post(reverse('create_profile'), {
            'name': 'Login User',
            'email': 'login-user@example.com',
            'phone': 'not-a-phone',
            'country': 'Bangladesh',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserProfile.objects.filter(user=login_user).exists())

    def test_dashboard_participant_form_renders_country_options_and_defaults_to_bangladesh(self):
        form = DashboardParticipantCreateForm(prefix='participant')

        rendered = str(form['country'])

        self.assertIn('Bangladesh', rendered)
        self.assertIn('selected', rendered)
        self.assertIn('value="Bangladesh"', rendered)

    def test_dashboard_participant_form_keeps_profile_country_when_provided(self):
        form = DashboardParticipantCreateForm(prefix='participant', initial={'country': 'Canada'})

        rendered = str(form['country'])

        self.assertIn('value="Canada" selected', rendered)
        self.assertIn('Bangladesh', rendered)


class PhoneAuditTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='audit-user', password='password', email='audit-user@example.com')
        self.event = Event.objects.create(
            name='Audit Event',
            slogan='Audit phones',
            year=2026,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        self.department = Department.objects.create(event=self.event, name='Oncology')

    def test_phone_audit_flags_convertible_invalid_and_duplicate_records(self):
        Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Canonical Participant',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Hospital A',
            email='canonical@example.com',
            phone='8801911269258',
            country='Bangladesh',
        )
        Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Convertible Participant',
            degree='MBBS',
            year_of_graduation=2021,
            department=self.department,
            organization='Hospital B',
            email='convertible@example.com',
            phone='01911269258',
            country='Bangladesh',
        )
        UserProfile.objects.create(
            user=User.objects.create_user(username='bad-profile', password='password', email='bad-profile@example.com'),
            name='Bad Profile',
            email='bad-profile@example.com',
            phone='abc123',
            country='Bangladesh',
        )

        report = run_phone_audit(selected_models=['participant', 'user_profile'])

        self.assertEqual(report['summary']['duplicate_group_count'], 1)
        self.assertGreaterEqual(report['summary']['issue_counts'].get('duplicate_normalized_phone', 0), 2)
        self.assertGreaterEqual(report['summary']['issue_counts'].get('invalid_phone', 0), 1)

        participant_rows = [row for row in report['rows'] if row['model_key'] == 'participant']
        self.assertEqual(len(participant_rows), 2)
        self.assertTrue(all('duplicate_normalized_phone' in row['issues'] for row in participant_rows))

    def test_phone_audit_can_include_valid_rows(self):
        UserProfile.objects.create(
            user=self.user,
            name='Valid Profile',
            email='audit-user@example.com',
            phone='8801911269258',
            country='Bangladesh',
        )

        report = run_phone_audit(selected_models=['user_profile'], include_valid=True)

        self.assertEqual(report['summary']['total_records'], 1)
        self.assertEqual(report['summary']['returned_records'], 1)
        self.assertEqual(report['rows'][0]['status'], 'sms_ready_bd')
        self.assertEqual(report['rows'][0]['issues'], [])


class PhoneFixTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='fix-user', password='password', email='fix-user@example.com')
        self.event = Event.objects.create(
            name='Fix Event',
            slogan='Fix phones',
            year=2026,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            location='Dhaka',
            event_status='active',
            registration='Open',
        )
        self.department = Department.objects.create(event=self.event, name='Surgery')

    def test_build_phone_fix_report_returns_safe_candidates_only(self):
        safe_profile = UserProfile.objects.create(
            user=self.user,
            name='Safe Fix',
            email='fix-user@example.com',
            phone='01911269258',
            country='Bangladesh',
        )
        Participant.objects.create(
            user=self.user,
            event=self.event,
            name='Dup A',
            degree='MBBS',
            year_of_graduation=2020,
            department=self.department,
            organization='Hospital A',
            email='dup-a@example.com',
            phone='01911269259',
            country='Bangladesh',
        )
        Participant.objects.create(
            user=User.objects.create_user(username='dup-user', password='password', email='dup-user@example.com'),
            event=self.event,
            name='Dup B',
            degree='MBBS',
            year_of_graduation=2021,
            department=self.department,
            organization='Hospital B',
            email='dup-b@example.com',
            phone='8801911269259',
            country='Bangladesh',
        )

        report = build_phone_fix_report(selected_models=['user_profile', 'participant'])

        self.assertEqual(report['summary']['candidate_count'], 1)
        self.assertEqual(report['summary']['skipped_due_to_duplicate'], 1)
        self.assertEqual(report['candidates'][0]['model_key'], 'user_profile')
        self.assertEqual(report['candidates'][0]['id'], safe_profile.id)
        self.assertEqual(report['candidates'][0]['normalized_phone'], '8801911269258')

    def test_apply_phone_fixes_updates_only_safe_candidates(self):
        profile = UserProfile.objects.create(
            user=self.user,
            name='Apply Fix',
            email='fix-user@example.com',
            phone='+880 1911-269258',
            country='Bangladesh',
        )

        result = apply_phone_fixes(selected_models=['user_profile'])
        profile.refresh_from_db()

        self.assertEqual(result['summary']['candidate_count'], 1)
        self.assertEqual(result['summary']['updated_count'], 1)
        self.assertEqual(profile.phone, '8801911269258')


class SmsServiceTests(TestCase):
    @override_settings(
        SMS_ENABLED=True,
        SMS_GATEWAY_URL='http://149.20.188.26:8124/sendtext',
        SMS_GATEWAY_API_KEY='api-key',
        SMS_GATEWAY_SECRET_KEY='secret-key',
        SMS_GATEWAY_CALLER_ID='caller-id',
        SMS_GATEWAY_HASH='',
        SMS_REQUEST_TIMEOUT=15,
    )
    @patch('registration.sms.requests.post')
    def test_send_sms_posts_expected_payload_for_valid_bangladesh_number(self, mock_post):
        from registration.sms import send_sms

        mock_post.return_value.ok = True
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'Status': '0', 'Text': 'ACCEPTD', 'Message_ID': '1'}

        result = send_sms('01712345678', 'Test SMS', country='Bangladesh', context={'source': 'test'})

        self.assertEqual(result['status'], 'sent')
        mock_post.assert_called_once_with(
            'http://149.20.188.26:8124/sendtext',
            json={
                'apikey': 'api-key',
                'secretkey': 'secret-key',
                'callerID': 'caller-id',
                'toUser': '8801712345678',
                'messageContent': 'Test SMS',
            },
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )

    @override_settings(SMS_ENABLED=True, SMS_GATEWAY_URL='http://149.20.188.26:8124/sendtext', SMS_GATEWAY_API_KEY='api-key', SMS_GATEWAY_SECRET_KEY='secret-key', SMS_GATEWAY_CALLER_ID='caller-id')
    @patch('registration.sms.requests.post')
    def test_send_sms_skips_invalid_or_non_bangladesh_numbers(self, mock_post):
        from registration.sms import send_sms

        result = send_sms('not-a-phone', 'Test SMS', country='Bangladesh', context={'source': 'test'})

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'ineligible_phone')
        mock_post.assert_not_called()

    @override_settings(SMS_ENABLED=False, SMS_GATEWAY_URL='http://149.20.188.26:8124/sendtext', SMS_GATEWAY_API_KEY='api-key', SMS_GATEWAY_SECRET_KEY='secret-key', SMS_GATEWAY_CALLER_ID='caller-id')
    @patch('registration.sms.requests.post')
    def test_send_sms_skips_when_disabled(self, mock_post):
        from registration.sms import send_sms

        result = send_sms('01712345678', 'Test SMS', country='Bangladesh', context={'source': 'test'})

        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'disabled')
        mock_post.assert_not_called()
