from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import (
    Behavior,
    KeyboardProfile,
    Modifier,
    ObservationEvent,
    ObservationSession,
    Project,
    Subject,
)
from tracker.views import (
    build_agreement_analysis,
    build_boris_like_payload,
    build_ethogram_payload,
    build_integrity_report,
    build_keyboard_profile_payload,
    build_project_boris_payload,
    build_project_statistics,
    build_reproducibility_bundle,
    build_statistics,
    build_subject_statistics,
    build_transition_rows,
    import_ethogram_payload,
    import_session_payload,
    resolve_event_kind,
)

User = get_user_model()


class HelperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.point_behavior = Behavior.objects.create(
            project=self.project, name='Eat', key_binding='e'
        )
        self.state_behavior = Behavior.objects.create(
            project=self.project,
            name='Stand',
            key_binding='s',
            mode=Behavior.MODE_STATE,
        )
        self.modifier = Modifier.objects.create(project=self.project, name='Near', key_binding='n')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='c')
        self.session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Live session',
            session_kind='live',
        )

    def test_resolve_event_kind_for_state(self):
        kind1 = resolve_event_kind(self.session, self.state_behavior, None)
        self.assertEqual(kind1, ObservationEvent.KIND_START)
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            event_kind=ObservationEvent.KIND_START,
            timestamp_seconds=Decimal('1.000'),
        )
        kind2 = resolve_event_kind(self.session, self.state_behavior, None)
        self.assertEqual(kind2, ObservationEvent.KIND_STOP)

    def test_build_statistics_subjects_transitions_and_integrity(self):
        event1 = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            subject=self.subject,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        event1.subjects.add(self.subject)
        start_event = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            subject=self.subject,
            event_kind=ObservationEvent.KIND_START,
            timestamp_seconds=Decimal('2.000'),
        )
        start_event.subjects.add(self.subject)
        stop_event = ObservationEvent.objects.create(
            session=self.session,
            behavior=self.state_behavior,
            subject=self.subject,
            event_kind=ObservationEvent.KIND_STOP,
            timestamp_seconds=Decimal('5.000'),
        )
        stop_event.subjects.add(self.subject)
        stats = build_statistics(self.session)
        subject_rows = build_subject_statistics(self.session)
        transitions = build_transition_rows(self.session)
        integrity = build_integrity_report(self.session)
        self.assertEqual(stats['session_event_count'], 3)
        self.assertEqual(subject_rows[0]['subject'], 'Cow 1')
        self.assertEqual(sum(row['count'] for row in transitions), 2)
        self.assertEqual(integrity['issue_count'], 0)

    def test_build_project_statistics_and_payloads(self):
        payload = build_ethogram_payload(self.project)
        self.assertEqual(payload['schema'], 'pybehaviorlog-0.8.3-ethogram')
        imported_categories, _, imported_behaviors = import_ethogram_payload(
            self.project, payload, replace_existing=False
        )
        self.assertEqual(imported_categories, 0)
        self.assertEqual(imported_behaviors, 0)
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        analytics = build_project_statistics(self.project)
        boris_payload = build_boris_like_payload(self.session)
        project_payload = build_project_boris_payload(self.project)
        self.assertEqual(analytics['session_count'], 1)
        self.assertEqual(analytics['event_count'], 1)
        self.assertEqual(boris_payload['schema'], 'boris-observation-v3')
        self.assertEqual(project_payload['schema'], 'boris-project-v1')

    def test_import_session_payload_v83(self):
        payload = {
            'schema': 'pybehaviorlog-0.8.3-session',
            'workflow_status': 'validated',
            'review_notes': 'Checked',
            'events': [
                {
                    'behavior': 'Eat',
                    'event_kind': 'point',
                    'timestamp_seconds': 1.5,
                    'subjects': ['Cow 1'],
                    'modifiers': ['Near'],
                    'comment': 'Imported',
                }
            ],
            'annotations': [
                {
                    'timestamp_seconds': 2.0,
                    'title': 'Mark',
                    'note': 'Imported note',
                    'color': '#ff0000',
                }
            ],
        }
        event_count, annotation_count = import_session_payload(
            self.session, payload, clear_existing=True
        )
        self.assertEqual(event_count, 1)
        self.assertEqual(annotation_count, 1)
        event = self.session.events.get()
        self.assertEqual(event.subjects_display, 'Cow 1')
        self.assertEqual(self.session.workflow_status, 'validated')

    def test_keyboard_profile_payload_and_reproducibility_bundle(self):
        profile = KeyboardProfile.objects.create(
            project=self.project,
            name='Default',
            is_default=True,
            behavior_bindings={str(self.point_behavior.pk): 'x'},
            modifier_bindings={str(self.modifier.pk): 'm'},
            subject_bindings={str(self.subject.pk): 'z'},
        )
        payload = build_keyboard_profile_payload(self.project)
        bundle = build_reproducibility_bundle(self.project)
        self.assertIn('ethogram.json', bundle)
        self.assertIn('manifest.json', bundle)
        self.assertIn(str(self.point_behavior.pk), payload['behavior_bindings'])
        self.assertTrue(profile.is_default)

    def test_agreement_analysis(self):
        other_session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Second session',
            session_kind='live',
        )
        ObservationEvent.objects.create(
            session=self.session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        ObservationEvent.objects.create(
            session=other_session,
            behavior=self.point_behavior,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.000'),
        )
        agreement = build_agreement_analysis(self.session, other_session)
        self.assertEqual(agreement['percent_agreement'], 100.0)
        self.assertGreaterEqual(agreement['bucket_count'], 1)
