import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from tracker.models import Behavior, ObservationSession, Project, Subject

User = get_user_model()


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.client = Client()
        self.client.login(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.behavior = Behavior.objects.create(project=self.project, name='Eat', key_binding='e')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='c')

    def test_home_requires_login(self):
        anon = Client()
        response = anon.get(reverse('tracker:home'))
        self.assertEqual(response.status_code, 302)

    def test_home_page(self):
        response = self.client.get(reverse('tracker:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PyBehaviorLog')

    def test_event_api_create_list_and_export_json(self):
        session = self.project.sessions.create(
            title='Live session',
            observer=self.user,
            session_kind='live',
        )
        response = self.client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps(
                {
                    'behavior_id': self.behavior.pk,
                    'timestamp_seconds': 1.5,
                    'comment': 'ok',
                    'subject_ids': [self.subject.pk],
                }
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['event']['behavior'], 'Eat')
        self.assertEqual(payload['event']['subjects_display'], 'Cow 1')

        list_response = self.client.get(reverse('tracker:session_events_json', args=[session.pk]))
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(len(list_payload['events']), 1)
        self.assertEqual(len(list_payload['audit_rows']), 1)
        self.assertEqual(list_payload['subject_rows'][0]['subject'], 'Cow 1')

        export_response = self.client.get(reverse('tracker:session_export_json', args=[session.pk]))
        self.assertEqual(export_response.status_code, 200)
        self.assertIn('pybehaviorlog-v7-session', export_response.content.decode('utf-8'))

    def test_event_update_and_delete_api(self):
        session = self.project.sessions.create(
            title='Live session',
            observer=self.user,
            session_kind='live',
        )
        create_response = self.client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps({'behavior_id': self.behavior.pk, 'timestamp_seconds': 1.5}),
            content_type='application/json',
        )
        event_id = create_response.json()['event']['id']
        update_response = self.client.post(
            reverse('tracker:event_update_api', args=[event_id]),
            data=json.dumps(
                {'behavior_id': self.behavior.pk, 'timestamp_seconds': 2.0, 'comment': 'updated'}
            ),
            content_type='application/json',
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()['event']['comment'], 'updated')
        delete_response = self.client.post(
            reverse('tracker:event_delete_api', args=[event_id]),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(session.events.exists())

    def test_annotation_workflow_and_audit_endpoints(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Workflow session',
            session_kind='live',
        )
        annotation_response = self.client.post(
            reverse('tracker:annotation_create_api', args=[session.pk]),
            data=json.dumps({'timestamp_seconds': 1.0, 'title': 'Mark', 'note': 'Note'}),
            content_type='application/json',
        )
        self.assertEqual(annotation_response.status_code, 201)

        workflow_response = self.client.post(
            reverse('tracker:session_workflow_action', args=[session.pk]),
            data=json.dumps({'action': 'validate', 'review_notes': 'Checked'}),
            content_type='application/json',
        )
        self.assertEqual(workflow_response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.workflow_status, ObservationSession.STATUS_VALIDATED)
        self.assertEqual(session.review_notes, 'Checked')

        audit_response = self.client.get(reverse('tracker:session_audit_json', args=[session.pk]))
        self.assertEqual(audit_response.status_code, 200)
        self.assertGreaterEqual(len(audit_response.json()['audit_rows']), 2)

    def test_locked_session_blocks_event_creation(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Locked session',
            session_kind='live',
            workflow_status=ObservationSession.STATUS_LOCKED,
        )
        response = self.client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps({'behavior_id': self.behavior.pk, 'timestamp_seconds': 1.5}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
