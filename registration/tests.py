from datetime import date, time
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core import mail
from registration.models import (
    Event, ProgramDay, HallRoom, TimeSlot, ProgramPerson, UserProfile,
    ProgramSession, ProgramSessionFaculty, ProgramSessionItem, ProgramTalkSlot,
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
        self.assertContains(response, 'is added to the program person library.')
        self.assertContains(response, profile.name)
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
