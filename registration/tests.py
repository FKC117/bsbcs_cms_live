from datetime import date, time
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from registration.models import (
    Event, ProgramDay, HallRoom, TimeSlot, ProgramPerson,
    ProgramSession, ProgramSessionFaculty, ProgramSessionItem,
    ProgramItemFaculty, AbstractSubmission
)

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
        self.assertIn('/accounts/login/', response.url)

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
        self.assertTrue(ProgramPerson.objects.filter(name='Dr. Robert Brown').exists())

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
