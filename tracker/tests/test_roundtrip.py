import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from tracker.compatibility import build_roundtrip_report
from tracker.models import (
    Behavior,
    IndependentVariableDefinition,
    Modifier,
    ObservationSession,
    Project,
    Subject,
)
from tracker.views import (
    build_boris_like_payload,
    build_project_boris_payload,
    import_project_payload,
    import_session_payload,
    load_session_import_payload,
)

User = get_user_model()
FIXTURES = Path(__file__).resolve().parent / 'fixtures'


class RoundTripCertificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='fixture_user', password='pass12345')

    def _base_project(self):
        project = Project.objects.create(owner=self.user, name='Fixture Project')
        Behavior.objects.create(project=project, name='Eat', key_binding='E')
        Behavior.objects.create(project=project, name='Stand', key_binding='S', mode=Behavior.MODE_STATE)
        Modifier.objects.create(project=project, name='Near', key_binding='N')
        Subject.objects.create(project=project, name='Cow 1', key_binding='C')
        IndependentVariableDefinition.objects.create(
            project=project,
            label='Location',
            value_type=IndependentVariableDefinition.TYPE_TEXT,
        )
        return project

    def test_boris_observation_fixture_roundtrip(self):
        project = self._base_project()
        session = ObservationSession.objects.create(
            project=project,
            observer=self.user,
            title='Fixture Observation',
        )
        payload = json.loads((FIXTURES / 'boris_observation_roundtrip.json').read_text(encoding='utf-8'))
        upload = SimpleUploadedFile(
            'boris_observation_roundtrip.json',
            json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )
        imported_payload, report = load_session_import_payload(upload, session)
        self.assertEqual(report['detected_format'], 'boris-observation-v3')
        import_session_payload(session, imported_payload, clear_existing=True)
        exported_payload = build_boris_like_payload(session)
        comparison = build_roundtrip_report(payload, exported_payload, family='session')
        self.assertTrue(comparison['equivalent'], comparison)

    def test_cowlog_fixture_roundtrip_via_pybehaviorlog_json(self):
        project = self._base_project()
        session = ObservationSession.objects.create(
            project=project,
            observer=self.user,
            title='CowLog Fixture',
        )
        raw_text = (FIXTURES / 'cowlog_results_roundtrip.txt').read_text(encoding='utf-8')
        upload = SimpleUploadedFile('cowlog_results_roundtrip.txt', raw_text.encode('utf-8'), content_type='text/plain')
        imported_payload, report = load_session_import_payload(upload, session)
        self.assertEqual(report['detected_format'], 'cowlog-results-v1')
        import_session_payload(session, imported_payload, clear_existing=True)
        exported_payload = {
            'schema': 'pybehaviorlog-0.9.1-session',
            'events': [
                {
                    'time': event.timestamp_seconds,
                    'behavior': event.behavior.name,
                    'event_kind': event.event_kind,
                    'modifiers': [item.name for item in event.modifiers.order_by('sort_order', 'name')],
                    'subjects': [item.name for item in event.all_subjects_ordered],
                    'comment': event.comment,
                }
                for event in session.events.order_by('timestamp_seconds', 'pk')
            ],
            'annotations': [],
        }
        comparison = build_roundtrip_report(imported_payload, exported_payload, family='session')
        self.assertTrue(comparison['equivalent'], comparison)

    def test_boris_project_fixture_roundtrip(self):
        project = Project.objects.create(owner=self.user, name='Imported Project')
        payload = json.loads((FIXTURES / 'boris_project_roundtrip.json').read_text(encoding='utf-8'))
        counts = import_project_payload(project, payload, actor=self.user, import_sessions=True)
        self.assertGreaterEqual(counts['sessions_imported'], 1)
        exported_payload = build_project_boris_payload(project)
        comparison = build_roundtrip_report(payload, exported_payload, family='project')
        self.assertTrue(comparison['equivalent'], comparison)

    def test_roundtrip_report_flags_mismatch(self):
        left = {
            'schema': 'boris-observation-v3',
            'observations': [{'events': [{'time': 1.0, 'behavior': 'Eat', 'event_kind': 'point'}]}],
        }
        right = {
            'schema': 'boris-observation-v3',
            'observations': [{'events': [{'time': 1.0, 'behavior': 'Drink', 'event_kind': 'point'}]}],
        }
        report = build_roundtrip_report(left, right, family='session')
        self.assertFalse(report['equivalent'])
        self.assertIn('events', report['mismatches'])
