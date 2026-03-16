import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from tracker.models import (
    Behavior,
    Modifier,
    ObservationEvent,
    ObservationSession,
    Project,
    Subject,
)
from tracker.views import (
    build_behavioral_sequences_text,
    build_binary_table_rows,
    build_session_compatibility_report,
    build_textgrid_text,
    load_session_import_payload,
)

User = get_user_model()


class CompatibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.client = Client()
        self.client.login(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.point_behavior = Behavior.objects.create(
            project=self.project,
            name='Eat',
            key_binding='E',
        )
        self.state_behavior = Behavior.objects.create(
            project=self.project,
            name='Stand',
            key_binding='S',
            mode=Behavior.MODE_STATE,
        )
        self.modifier = Modifier.objects.create(project=self.project, name='Near', key_binding='N')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='C')
        self.session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Session 1',
            session_kind='live',
        )

    def test_load_session_import_payload_supports_cowlog_text(self):
        upload = SimpleUploadedFile(
            'cowlog.txt',
            b'1.0\tEat\tNear\n',
            content_type='text/plain',
        )
        payload, report = load_session_import_payload(upload, self.session)
        self.assertEqual(report['detected_format'], 'cowlog-results-v1')
        self.assertEqual(payload['events'][0]['behavior'], 'Eat')
        self.assertEqual(payload['events'][0]['modifiers'], ['Near'])

    def test_session_import_view_accepts_cowlog_text(self):
        upload = SimpleUploadedFile(
            'cowlog.txt',
            b'1.0\tEat\tNear\n',
            content_type='text/plain',
        )
        response = self.client.post(
            reverse('tracker:session_import_json', args=[self.session.pk]),
            data={'file': upload, 'clear_existing': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        event = self.session.events.get()
        self.assertEqual(event.behavior.name, 'Eat')
        self.assertEqual(event.modifiers_display, 'Near')


    def test_load_session_import_payload_supports_state_intervals_from_tabular_rows(self):
        upload = SimpleUploadedFile(
            'boris_rows.csv',
            b'time,stop,behavior,subject,modifier,comment\n1.0,3.0,Stand,Cow 1,Near,Frame A\n',
            content_type='text/csv',
        )
        payload, report = load_session_import_payload(upload, self.session)
        self.assertEqual(report['detected_format'], 'boris-tabular-csv-v1')
        self.assertEqual(len(payload['events']), 2)
        self.assertEqual(payload['events'][0]['event_kind'], 'start')
        self.assertEqual(payload['events'][1]['event_kind'], 'stop')

    def test_session_undo_and_redo_endpoints_restore_event_state(self):
        response = self.client.post(
            reverse('tracker:event_create_api', args=[self.session.pk]),
            data=json.dumps(
                {
                    'behavior_id': self.point_behavior.pk,
                    'timestamp_seconds': '1.000',
                    'modifier_ids': [self.modifier.pk],
                    'subject_ids': [self.subject.pk],
                }
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.session.events.count(), 1)
        undo_response = self.client.post(
            reverse('tracker:session_undo_api', args=[self.session.pk]),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(undo_response.status_code, 200)
        self.assertEqual(self.session.events.count(), 0)
        redo_response = self.client.post(
            reverse('tracker:session_redo_api', args=[self.session.pk]),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(redo_response.status_code, 200)
        self.assertEqual(self.session.events.count(), 1)

    def test_behavioral_sequences_and_textgrid_exports(self):
        point_event = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        point_event.subjects.add(self.subject)
        start_event = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            event_kind=ObservationEvent.KIND_START,
            timestamp_seconds=Decimal('2.000'),
        )
        start_event.subjects.add(self.subject)
        stop_event = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            event_kind=ObservationEvent.KIND_STOP,
            timestamp_seconds=Decimal('4.000'),
        )
        stop_event.subjects.add(self.subject)
        sequences = build_behavioral_sequences_text(self.session)
        textgrid = build_textgrid_text(self.session)
        self.assertIn('Cow 1:', sequences)
        self.assertIn('Eat|Stand', sequences)
        self.assertIn('Object class = "TextGrid"', textgrid)
        self.assertIn('name = "Cow 1"', textgrid)

    def test_binary_table_and_compatibility_report(self):
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            event_kind=ObservationEvent.KIND_START,
            timestamp_seconds=Decimal('2.000'),
        )
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            event_kind=ObservationEvent.KIND_STOP,
            timestamp_seconds=Decimal('4.000'),
        )
        rows = build_binary_table_rows(self.session, step_seconds=1.0)
        self.assertEqual(rows[1][1], 1)
        report = build_session_compatibility_report(self.session)
        self.assertFalse(report['cowlog']['ready'])
        self.assertTrue(report['cowlog']['warnings'])

    def test_export_endpoints_for_compatibility_formats(self):
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        response = self.client.get(reverse('tracker:session_export_cowlog_txt', args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('CowLog-compatible', response.content.decode('utf-8'))
        response = self.client.get(
            reverse('tracker:session_export_behavioral_sequences', args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('# observation id:', response.content.decode('utf-8'))
        response = self.client.get(reverse('tracker:session_export_textgrid', args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('TextGrid', response.content.decode('utf-8'))
        response = self.client.get(
            reverse('tracker:session_export_binary_table_tsv', args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('time\tEat\tStand', response.content.decode('utf-8'))
        response = self.client.get(
            reverse('tracker:session_export_compatibility_report', args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode('utf-8'))
        self.assertEqual(payload['schema'], 'pybehaviorlog-0.8.9-session-compatibility-report')
