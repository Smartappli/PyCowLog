from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import (
    Behavior,
    BehaviorCategory,
    IndependentVariableDefinition,
    KeyboardProfile,
    Modifier,
    ObservationAuditLog,
    ObservationEvent,
    ObservationSession,
    Project,
    ProjectMembership,
    Subject,
    SubjectGroup,
    VideoAsset,
)

User = get_user_model()


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.member = User.objects.create_user(username='member', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.category = BehaviorCategory.objects.create(project=self.project, name='General')
        self.behavior = Behavior.objects.create(
            project=self.project,
            category=self.category,
            name='Eat',
            key_binding='e',
            mode=Behavior.MODE_POINT,
        )
        self.modifier = Modifier.objects.create(project=self.project, name='Near', key_binding='n')
        self.group = SubjectGroup.objects.create(project=self.project, name='Adults')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='c')
        self.subject.groups.add(self.group)
        self.variable = IndependentVariableDefinition.objects.create(
            project=self.project,
            label='Weather',
            value_type=IndependentVariableDefinition.TYPE_SET,
            set_values='sunny,cloudy,rainy',
            default_value='sunny',
        )

    def test_uppercase_key_bindings(self):
        self.assertEqual(self.behavior.key_binding, 'E')
        self.assertEqual(self.modifier.key_binding, 'N')
        self.assertEqual(self.subject.key_binding, 'C')

    def test_value_options(self):
        self.assertEqual(self.variable.value_options, ['sunny', 'cloudy', 'rainy'])

    def test_project_role_helper_and_memberships(self):
        ProjectMembership.objects.create(
            project=self.project,
            user=self.member,
            role=ProjectMembership.ROLE_REVIEWER,
        )
        self.assertEqual(self.project.role_for_user(self.user), ProjectMembership.ROLE_OWNER)
        self.assertEqual(self.project.role_for_user(self.member), ProjectMembership.ROLE_REVIEWER)
        self.assertTrue(self.project.can_review(self.member))
        self.assertFalse(self.project.can_edit(self.member))

    def test_session_primary_label_for_live(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Live 1',
            session_kind=ObservationSession.KIND_LIVE,
        )
        self.assertEqual(session.primary_label, 'LIVE')
        self.assertEqual(session.all_videos_ordered, [])

    def test_session_primary_label_for_media_and_effective_profile(self):
        video = VideoAsset.objects.create(
            project=self.project, title='Vid 1', file='videos/test.mp4'
        )
        profile = KeyboardProfile.objects.create(
            project=self.project,
            name='Default',
            is_default=True,
            behavior_bindings={str(self.behavior.pk): 'Z'},
            modifier_bindings={},
            subject_bindings={},
        )
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Media 1',
            session_kind=ObservationSession.KIND_MEDIA,
            video=video,
        )
        self.assertEqual(session.primary_label, 'Vid 1')
        self.assertEqual(session.effective_keyboard_profile, profile)

    def test_keyboard_profile_normalizes_keys(self):
        profile = KeyboardProfile.objects.create(
            project=self.project,
            name='Alt',
            behavior_bindings={str(self.behavior.pk): 'x'},
            modifier_bindings={str(self.modifier.pk): 'm'},
            subject_bindings={str(self.subject.pk): 's'},
        )
        self.assertEqual(profile.behavior_bindings[str(self.behavior.pk)], 'X')
        self.assertEqual(profile.modifier_bindings[str(self.modifier.pk)], 'M')
        self.assertEqual(profile.subject_bindings[str(self.subject.pk)], 'S')

    def test_event_with_subjects_display_and_lock_flag(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Observation',
            session_kind=ObservationSession.KIND_LIVE,
            workflow_status=ObservationSession.STATUS_LOCKED,
        )
        event = ObservationEvent.objects.create(
            session=session,
            behavior=self.behavior,
            subject=self.subject,
            event_kind=ObservationEvent.KIND_POINT,
            timestamp_seconds=Decimal('1.250'),
            frame_index=31,
        )
        event.subjects.add(self.subject)
        self.assertEqual(event.subjects_display, 'Cow 1')
        self.assertEqual(event.frame_index, 31)
        self.assertTrue(session.is_locked_for_coding)

    def test_audit_log_string(self):
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Audit session',
            session_kind=ObservationSession.KIND_LIVE,
        )
        log = ObservationAuditLog.objects.create(
            session=session,
            actor=self.user,
            target_type=ObservationAuditLog.TARGET_SESSION,
            action=ObservationAuditLog.ACTION_STATUS,
            summary='Workflow changed to validated.',
        )
        self.assertIn('status', str(log))
