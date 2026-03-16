from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.forms import (
    BehaviorForm,
    ModifierForm,
    ObservationSessionForm,
    ObservationTemplateForm,
    ProjectSettingsForm,
    SubjectForm,
    VideoAssetForm,
)
from tracker.models import (
    Behavior,
    BehaviorCategory,
    IndependentVariableDefinition,
    Modifier,
    ObservationSession,
    Project,
    Subject,
    SubjectGroup,
    VideoAsset,
)

User = get_user_model()


class ObservationSessionFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.video = VideoAsset.objects.create(
            project=self.project, title='Vid 1', file='videos/test.mp4'
        )
        self.weather = IndependentVariableDefinition.objects.create(
            project=self.project,
            label='Weather',
            value_type=IndependentVariableDefinition.TYPE_SET,
            set_values='sunny,cloudy',
            default_value='sunny',
        )
        self.flag = IndependentVariableDefinition.objects.create(
            project=self.project,
            label='Night',
            value_type=IndependentVariableDefinition.TYPE_BOOLEAN,
            default_value='false',
        )

    def test_media_session_requires_video(self):
        form = ObservationSessionForm(
            data={
                'session_kind': 'media',
                'title': 'Session 1',
                'playback_rate': '1.00',
                'frame_step_seconds': '0.0400',
                'recorded_at': '2026-03-15T10:00',
                f'var_{self.weather.pk}': 'sunny',
            },
            project=self.project,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('video', form.errors)

    def test_live_session_is_valid_without_video(self):
        form = ObservationSessionForm(
            data={
                'session_kind': 'live',
                'title': 'Session 1',
                'playback_rate': '1.00',
                'frame_step_seconds': '0.0400',
                'recorded_at': '2026-03-15T10:00',
                f'var_{self.weather.pk}': 'cloudy',
                f'var_{self.flag.pk}': 'true',
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_media_session_with_video_and_save_variable_values(self):
        form = ObservationSessionForm(
            data={
                'session_kind': 'media',
                'video': self.video.pk,
                'title': 'Session 1',
                'playback_rate': '1.00',
                'frame_step_seconds': '0.0400',
                'recorded_at': '2026-03-15T10:00',
                f'var_{self.weather.pk}': 'sunny',
                f'var_{self.flag.pk}': 'false',
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid(), form.errors)
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.user,
            title='Session 1',
            session_kind=ObservationSession.KIND_MEDIA,
            video=self.video,
        )
        form.save_variable_values(session)
        values = {item.definition.label: item.value for item in session.variable_values.all()}
        self.assertEqual(values['Weather'], 'sunny')
        self.assertEqual(values['Night'], 'false')


class SubjectAndTemplateFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='olivier', password='pass12345')
        self.project = Project.objects.create(owner=self.user, name='Project 1')
        self.group = SubjectGroup.objects.create(project=self.project, name='Adults')
        self.subject = Subject.objects.create(project=self.project, name='Cow 1', key_binding='c')
        self.behavior = Behavior.objects.create(project=self.project, name='Eat', key_binding='e')
        self.modifier = Modifier.objects.create(project=self.project, name='Near', key_binding='n')
        self.variable = IndependentVariableDefinition.objects.create(
            project=self.project, label='Weather'
        )

    def test_subject_form_uses_project_groups(self):
        form = SubjectForm(
            data={
                'name': 'Cow 2',
                'description': '',
                'groups': [self.group.pk],
                'key_binding': 'd',
                'color': '#ffffff',
                'sort_order': 0,
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid(), form.errors)
        subject = form.save(commit=False)
        subject.project = self.project
        subject.save()
        form.save_m2m()
        self.assertEqual(subject.groups.first(), self.group)

    def test_template_form_querysets(self):
        form = ObservationTemplateForm(
            data={
                'name': 'Default template',
                'description': 'Reusable setup',
                'default_session_kind': 'media',
                'behaviors': [self.behavior.pk],
                'modifiers': [self.modifier.pk],
                'subjects': [self.subject.pk],
                'variable_definitions': [self.variable.pk],
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid(), form.errors)


class AdditionalFormCoverageTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass12345')
        self.other = User.objects.create_user(username='other', password='pass12345')
        self.project = Project.objects.create(owner=self.owner, name='Project 1')
        self.category = BehaviorCategory.objects.create(project=self.project, name='General')
        self.video = VideoAsset.objects.create(
            project=self.project, title='Video 1', file='videos/test.mp4'
        )
        self.timestamp_var = IndependentVariableDefinition.objects.create(
            project=self.project,
            label='Observed at',
            value_type=IndependentVariableDefinition.TYPE_TIMESTAMP,
        )
        self.longtext_var = IndependentVariableDefinition.objects.create(
            project=self.project,
            label='Context',
            value_type=IndependentVariableDefinition.TYPE_LONGTEXT,
        )

    def test_project_settings_excludes_owner(self):
        form = ProjectSettingsForm(owner=self.owner)
        self.assertNotIn(self.owner, form.fields['collaborators'].queryset)
        self.assertIn(self.other, form.fields['collaborators'].queryset)

    def test_modifier_and_behavior_key_cleaning(self):
        modifier_form = ModifierForm(
            data={'name': 'Near', 'description': '', 'key_binding': 'n', 'sort_order': 0}
        )
        behavior_form = BehaviorForm(
            data={
                'category': self.category.pk,
                'name': 'Eat',
                'description': '',
                'key_binding': 'e',
                'color': '#ffffff',
                'mode': 'point',
                'sort_order': 0,
            },
            project=self.project,
        )
        self.assertTrue(modifier_form.is_valid(), modifier_form.errors)
        self.assertEqual(modifier_form.clean_key_binding(), 'N')
        self.assertTrue(behavior_form.is_valid(), behavior_form.errors)
        self.assertEqual(behavior_form.fields['category'].queryset.get(), self.category)
        self.assertEqual(behavior_form.clean_key_binding(), 'E')

    def test_video_form_existing_instance_makes_file_optional(self):
        form = VideoAssetForm(instance=self.video)
        self.assertFalse(form.fields['file'].required)

    def test_session_form_supports_timestamp_and_longtext_variables(self):
        form = ObservationSessionForm(
            data={
                'session_kind': 'media',
                'video': self.video.pk,
                'title': 'Session 1',
                'playback_rate': '1.00',
                'frame_step_seconds': '0.0400',
                'recorded_at': '2026-03-15T10:00',
                f'var_{self.timestamp_var.pk}': '2026-03-15T10:05',
                f'var_{self.longtext_var.pk}': 'Detailed free-text context',
            },
            project=self.project,
        )
        self.assertTrue(form.is_valid(), form.errors)
        session = ObservationSession.objects.create(
            project=self.project,
            observer=self.owner,
            title='Existing session',
            session_kind=ObservationSession.KIND_MEDIA,
            video=self.video,
        )
        form.save_variable_values(session)
        values = {item.definition.label: item.value for item in session.variable_values.all()}
        self.assertIn('2026-03-15T10:05', values['Observed at'])
        self.assertEqual(values['Context'], 'Detailed free-text context')
