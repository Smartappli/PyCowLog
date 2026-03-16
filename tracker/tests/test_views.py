import json
from io import BytesIO
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from tracker.models import (
    Behavior,
    KeyboardProfile,
    ObservationSegment,
    ObservationSession,
    Project,
    ProjectMembership,
    Subject,
)

User = get_user_model()


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.reviewer = User.objects.create_user(username='reviewer', password='pass12345')
        self.viewer = User.objects.create_user(username='viewer', password='pass12345')
        self.client = Client()
        self.client.login(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.behavior = Behavior.objects.create(project=self.project, name='Eat', key_binding='e')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='c')
        self.profile = KeyboardProfile.objects.create(
            project=self.project,
            name='Default',
            is_default=True,
            behavior_bindings={str(self.behavior.pk): 'E'},
            modifier_bindings={},
            subject_bindings={str(self.subject.pk): 'C'},
        )
        ProjectMembership.objects.create(
            project=self.project,
            user=self.reviewer,
            role=ProjectMembership.ROLE_REVIEWER,
        )
        ProjectMembership.objects.create(
            project=self.project,
            user=self.viewer,
            role=ProjectMembership.ROLE_VIEWER,
        )

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
            keyboard_profile=self.profile,
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
        self.assertIn('pybehaviorlog-0.9.1-session', export_response.content.decode('utf-8'))

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

    def test_annotation_workflow_and_audit_endpoints_for_reviewer(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Workflow session',
            session_kind='live',
        )
        reviewer_client = Client()
        reviewer_client.login(username='reviewer', password='pass12345')
        annotation_response = reviewer_client.post(
            reverse('tracker:annotation_create_api', args=[session.pk]),
            data=json.dumps({'timestamp_seconds': 1.0, 'title': 'Mark', 'note': 'Note'}),
            content_type='application/json',
        )
        self.assertEqual(annotation_response.status_code, 201)

        workflow_response = reviewer_client.post(
            reverse('tracker:session_workflow_action', args=[session.pk]),
            data=json.dumps({'action': 'validate', 'review_notes': 'Checked'}),
            content_type='application/json',
        )
        self.assertEqual(workflow_response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.workflow_status, ObservationSession.STATUS_VALIDATED)
        self.assertEqual(session.review_notes, 'Checked')

        audit_response = reviewer_client.get(reverse('tracker:session_audit_json', args=[session.pk]))
        self.assertEqual(audit_response.status_code, 200)
        self.assertGreaterEqual(len(audit_response.json()['audit_rows']), 2)

    def test_viewer_cannot_code(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Viewer session',
            session_kind='live',
        )
        viewer_client = Client()
        viewer_client.login(username='viewer', password='pass12345')
        response = viewer_client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps({'behavior_id': self.behavior.pk, 'timestamp_seconds': 1.5}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

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

    def test_project_bundle_export(self):
        self.project.sessions.create(title='Bundle session', observer=self.user, session_kind='live')
        response = self.client.get(reverse('tracker:project_export_bundle', args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        archive = ZipFile(BytesIO(response.content))
        self.assertIn('manifest.json', archive.namelist())
        self.assertIn('ethogram.json', archive.namelist())

    def test_project_analytics_agreement(self):
        session_a = self.project.sessions.create(title='A', observer=self.user, session_kind='live')
        session_b = self.project.sessions.create(title='B', observer=self.user, session_kind='live')
        for session in [session_a, session_b]:
            self.client.post(
                reverse('tracker:event_create_api', args=[session.pk]),
                data=json.dumps({'behavior_id': self.behavior.pk, 'timestamp_seconds': 1.0}),
                content_type='application/json',
            )
        response = self.client.get(
            reverse('tracker:project_analytics', args=[self.project.pk]),
            {'reference_session': session_a.pk, 'comparison_session': session_b.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['agreement']['cohen_kappa'], 1.0)
        self.assertContains(response, '100', status_code=200)

    def test_session_media_analysis_endpoint_and_extra_exports(self):
        session = self.project.sessions.create(
            title='Media session',
            observer=self.user,
            session_kind='live',
        )
        response = self.client.get(reverse('tracker:session_media_analysis_json', args=[session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('media_analysis', response.json())
        html_response = self.client.get(reverse('tracker:session_export_html', args=[session.pk]))
        self.assertEqual(html_response.status_code, 200)
        sql_response = self.client.get(reverse('tracker:session_export_sql', args=[session.pk]))
        self.assertEqual(sql_response.status_code, 200)
        self.assertIn('CREATE TABLE IF NOT EXISTS pybehaviorlog_event_export', sql_response.content.decode('utf-8'))

    def test_session_import_accepts_csv(self):
        session = self.project.sessions.create(
            title='CSV import session',
            observer=self.user,
            session_kind='live',
        )
        content = 'time,behavior,event_kind,subjects,comment\n1.500,Eat,point,Cow 1,CSV import\n'
        upload = SimpleUploadedFile('events.csv', content.encode('utf-8'), content_type='text/csv')
        response = self.client.post(
            reverse('tracker:session_import_json', args=[session.pk]),
            data={'file': upload, 'clear_existing': True},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(session.events.count(), 1)

    def test_project_import_boris_json_view(self):
        payload = {
            'schema': 'boris-project-v3',
            'ethogram': {'schema': 'pybehaviorlog-0.9.1-ethogram', 'categories': [], 'modifiers': [], 'subject_groups': [], 'subjects': [], 'variables': [], 'behaviors': [{'name': 'Imported behavior', 'description': '', 'key_binding': 'i', 'color': '#0f766e', 'mode': 'point', 'sort_order': 1, 'category': None}]},
            'subject_groups': [{'name': 'Imported group', 'description': '', 'color': '#123456', 'sort_order': 1}],
            'subjects': [{'name': 'Imported subject', 'description': '', 'key_binding': 's', 'color': '#654321', 'sort_order': 1, 'groups': ['Imported group']}],
            'variables': [{'label': 'Weight', 'description': '', 'value_type': 'numeric', 'set_values': [], 'default_value': '0', 'sort_order': 1}],
            'observation_templates': [{'name': 'Imported template', 'description': '', 'default_session_kind': 'live', 'behaviors': ['Imported behavior'], 'modifiers': [], 'subjects': ['Imported subject'], 'variable_definitions': ['Weight']}],
            'sessions': [{'schema': 'boris-observation-v3', 'observations': [{'title': 'Imported session', 'events': [{'behavior': 'Imported behavior', 'time': 1.0, 'event_kind': 'point', 'subjects': ['Imported subject']}], 'annotations': []}]}],
        }
        upload = SimpleUploadedFile('project.json', json.dumps(payload).encode('utf-8'), content_type='application/json')
        response = self.client.post(
            reverse('tracker:project_import_boris_json', args=[self.project.pk]),
            data={'file': upload, 'import_sessions': 'on', 'create_live_sessions': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.project.subjects.filter(name='Imported subject').exists())
        self.assertTrue(self.project.observation_templates.filter(name='Imported template').exists())
        self.assertTrue(self.project.sessions.filter(title='Imported session').exists())

    def test_workflow_save_notes_action(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Review notes session',
            session_kind='live',
        )
        reviewer_client = Client()
        reviewer_client.login(username='reviewer', password='pass12345')
        response = reviewer_client.post(
            reverse('tracker:session_workflow_action', args=[session.pk]),
            data=json.dumps({'action': 'save_notes', 'review_notes': 'Detailed review note'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.review_notes, 'Detailed review note')




    def test_workflow_fix_unpaired_states_action(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Unpaired session',
            session_kind='live',
        )
        self.client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps({'behavior_id': self.behavior.pk, 'timestamp_seconds': 1.0}),
            content_type='application/json',
        )
        state_behavior = Behavior.objects.create(
            project=self.project,
            name='Standing',
            key_binding='s',
            mode=Behavior.MODE_STATE,
        )
        self.client.post(
            reverse('tracker:event_create_api', args=[session.pk]),
            data=json.dumps({'behavior_id': state_behavior.pk, 'timestamp_seconds': 2.0, 'event_kind': 'start'}),
            content_type='application/json',
        )
        response = self.client.post(
            reverse('tracker:session_workflow_action', args=[session.pk]),
            data=json.dumps({'action': 'fix_unpaired_states', 'timestamp_seconds': 4.5}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fixed_count'], 1)
        stop_event = session.events.filter(behavior=state_behavior, event_kind='stop').first()
        self.assertIsNotNone(stop_event)
        self.assertEqual(float(stop_event.timestamp_seconds), 4.5)

    def test_project_import_boris_json_accepts_mapping_shapes(self):
        payload = {
            'schema': 'boris-project-v2',
            'ethogram': {
                'schema': 'pybehaviorlog-0.9.1-ethogram',
                'categories': {'General': {'color': '#111111', 'sort_order': 1}},
                'modifiers': {'Near': {'description': 'proximity', 'key': 'n', 'sort_order': 1}},
                'behaviors': {'Imported code': {'description': '', 'key': 'i', 'color': '#0f766e', 'mode': 'point', 'sort_order': 1, 'category': {'name': 'General'}}},
            },
            'groups': {'Adults': {'description': 'adult group', 'color': '#123456', 'sort_order': 1}},
            'subjects': {'Cow A': {'key': 'a', 'color': '#654321', 'sort_order': 1, 'groups': ['Adults']}},
            'independent_variables': {'Weight': {'value_type': 'numeric', 'default_value': '0'}},
            'templates': {'Standard': {'default_session_kind': 'live', 'codes': ['Imported code'], 'subjects': ['Cow A'], 'variables': ['Weight']}},
            'observations': {
                'Obs 1': {
                    'description': 'Imported mapping session',
                    'events': [
                        {'code': 'Imported code', 'time': 1.25, 'subject': 'Cow A', 'modifier': 'Near'},
                    ],
                    'annotations': [{'time': 1.5, 'title': 'Mark', 'comment': 'ok'}],
                }
            },
        }
        upload = SimpleUploadedFile('project.json', json.dumps(payload).encode('utf-8'), content_type='application/json')
        response = self.client.post(
            reverse('tracker:project_import_boris_json', args=[self.project.pk]),
            data={'file': upload, 'import_sessions': 'on', 'create_live_sessions': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        imported_behavior = self.project.behaviors.get(name='Imported code')
        imported_session = self.project.sessions.get(title='Imported mapping session')
        imported_event = imported_session.events.get(behavior=imported_behavior)
        self.assertEqual(imported_event.subjects_display, 'Cow A')
        self.assertEqual(imported_event.modifiers_display, 'Near')
        self.assertEqual(imported_session.annotations.first().title, 'Mark')

    def test_session_player_contains_event_editor_controls(self):
        session = self.project.sessions.create(
            title='Interface session',
            observer=self.user,
            session_kind='live',
            keyboard_profile=self.profile,
        )
        response = self.client.get(reverse('tracker:session_player', args=[session.pk]))
        self.assertContains(response, 'event-editor')
        self.assertContains(response, 'fix-unpaired-btn')


    def test_review_queue_and_segment_crud(self):
        session = self.project.sessions.create(title='Segment session', observer=self.user, session_kind='live')
        reviewer_client = Client()
        reviewer_client.login(username='reviewer', password='pass12345')
        create_response = reviewer_client.post(
            reverse('tracker:segment_create', args=[session.pk]),
            data={
                'title': 'Intro',
                'start_seconds': '0',
                'end_seconds': '12.5',
                'status': 'todo',
                'assignee': self.user.pk,
                'reviewer': self.reviewer.pk,
                'notes': 'Check the opening phase',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        segment = ObservationSegment.objects.get(session=session)
        queue_response = reviewer_client.get(reverse('tracker:review_queue'), {'filter': 'review'})
        self.assertEqual(queue_response.status_code, 200)
        self.assertContains(queue_response, 'Intro')
        update_response = reviewer_client.post(
            reverse('tracker:segment_update', args=[segment.pk]),
            data={
                'title': 'Intro',
                'start_seconds': '0',
                'end_seconds': '10',
                'status': 'done',
                'assignee': self.user.pk,
                'reviewer': self.reviewer.pk,
                'notes': 'Reviewed',
            },
        )
        self.assertEqual(update_response.status_code, 302)
        segment.refresh_from_db()
        self.assertEqual(segment.status, ObservationSegment.STATUS_DONE)

    def test_segment_batch_assign_and_review_queue_filters_and_export(self):
        session = self.project.sessions.create(title='Batch session', observer=self.user, session_kind='live')
        first = ObservationSegment.objects.create(
            session=session,
            title='Intro segment',
            start_seconds='0',
            end_seconds='5',
            status=ObservationSegment.STATUS_TODO,
            assignee=self.user,
            reviewer=self.reviewer,
        )
        second = ObservationSegment.objects.create(
            session=session,
            title='Core segment',
            start_seconds='5',
            end_seconds='15',
            status=ObservationSegment.STATUS_IN_PROGRESS,
            assignee=None,
            reviewer=self.reviewer,
        )

        reviewer_client = Client()
        reviewer_client.login(username='reviewer', password='pass12345')
        batch_response = reviewer_client.post(
            reverse('tracker:segment_batch_assign', args=[session.pk]),
            data={
                'segment_ids': [first.pk, second.pk],
                'set_assignee': '1',
                'assignee': self.reviewer.pk,
                'set_status': '1',
                'status': ObservationSegment.STATUS_DONE,
            },
        )
        self.assertEqual(batch_response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.assignee_id, self.reviewer.pk)
        self.assertEqual(second.assignee_id, self.reviewer.pk)
        self.assertEqual(first.status, ObservationSegment.STATUS_DONE)
        self.assertEqual(second.status, ObservationSegment.STATUS_DONE)

        queue_response = reviewer_client.get(
            reverse('tracker:review_queue'),
            {
                'filter': 'all',
                'status': 'done',
                'assignee': 'me',
                'q': 'Core',
            },
        )
        self.assertEqual(queue_response.status_code, 200)
        self.assertContains(queue_response, 'Core segment')
        self.assertNotContains(queue_response, 'Intro segment')

        export_response = reviewer_client.get(
            reverse('tracker:review_queue_export_segment_analytics_csv')
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('Core segment', export_response.content.decode('utf-8'))

    def test_session_export_json_contains_segments(self):
        session = self.project.sessions.create(title='Segment export', observer=self.user, session_kind='live')
        ObservationSegment.objects.create(
            session=session,
            title='A',
            start_seconds='1.0',
            end_seconds='2.0',
            status=ObservationSegment.STATUS_TODO,
            assignee=self.user,
            reviewer=self.reviewer,
        )
        response = self.client.get(reverse('tracker:session_export_json', args=[session.pk]))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode('utf-8'))
        self.assertEqual(payload['segments'][0]['title'], 'A')
