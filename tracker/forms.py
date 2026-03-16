from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import (
    Behavior,
    BehaviorCategory,
    IndependentVariableDefinition,
    KeyboardProfile,
    Modifier,
    ObservationSession,
    ObservationTemplate,
    ObservationVariableValue,
    Project,
    ProjectMembership,
    Subject,
    SubjectGroup,
    VideoAsset,
)

User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=False, label=_('Email'))

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}
        labels = {'name': _('Name'), 'description': _('Description')}


class ProjectSettingsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}
        labels = {'name': _('Name'), 'description': _('Description')}


class ProjectMembershipForm(forms.ModelForm):
    class Meta:
        model = ProjectMembership
        fields = ['user', 'role']
        labels = {'user': _('User'), 'role': _('Role')}

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        queryset = User.objects.order_by('username')
        if project is not None:
            excluded_ids = set(project.memberships.values_list('user_id', flat=True))
            if self.instance and self.instance.pk and self.instance.user_id:
                excluded_ids.discard(self.instance.user_id)
            queryset = queryset.exclude(pk=project.owner_id).exclude(pk__in=excluded_ids)
        self.fields['user'].queryset = queryset


class KeyboardProfileForm(forms.ModelForm):
    class Meta:
        model = KeyboardProfile
        fields = ['name', 'description', 'is_default']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}
        labels = {
            'name': _('Name'),
            'description': _('Description'),
            'is_default': _('Set as default profile'),
        }


class EthogramImportForm(forms.Form):
    file = forms.FileField(
        label=_('File'),
        help_text=_('JSON export from PyBehaviorLog 0.8 and earlier supported versions or BORIS-like JSON.')
    )
    replace_existing = forms.BooleanField(
        required=False,
        label=_('Replace all existing ethogram entities'),
        help_text=_('Blocked when the project already contains sessions or events.'),
    )


class SessionImportForm(forms.Form):
    file = forms.FileField(label=_('File'), help_text=_('PyBehaviorLog 0.8 and earlier supported versions JSON or simplified BORIS-like JSON.'))
    clear_existing = forms.BooleanField(
        required=False,
        label=_('Delete existing events and annotations before import'),
    )


class BehaviorCategoryForm(forms.ModelForm):
    class Meta:
        model = BehaviorCategory
        fields = ['name', 'color', 'sort_order']
        widgets = {'color': forms.TextInput(attrs={'type': 'color'})}
        labels = {'name': _('Name'), 'color': _('Color'), 'sort_order': _('Sort order')}


class ModifierForm(forms.ModelForm):
    class Meta:
        model = Modifier
        fields = ['name', 'description', 'key_binding', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'key_binding': forms.TextInput(attrs={'maxlength': 1}),
        }
        labels = {'name': _('Name'), 'description': _('Description'), 'key_binding': _('Key binding'), 'sort_order': _('Sort order')}

    def clean_key_binding(self):
        return self.cleaned_data['key_binding'].upper()


class SubjectGroupForm(forms.ModelForm):
    class Meta:
        model = SubjectGroup
        fields = ['name', 'description', 'color', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'color': forms.TextInput(attrs={'type': 'color'}),
        }
        labels = {'name': _('Name'), 'description': _('Description'), 'color': _('Color'), 'sort_order': _('Sort order')}


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'description', 'groups', 'key_binding', 'color', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'key_binding': forms.TextInput(attrs={'maxlength': 1}),
            'color': forms.TextInput(attrs={'type': 'color'}),
            'groups': forms.CheckboxSelectMultiple(),
        }
        labels = {'name': _('Name'), 'description': _('Description'), 'groups': _('Groups'), 'key_binding': _('Key binding'), 'color': _('Color'), 'sort_order': _('Sort order')}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['groups'].required = False
        self.fields['groups'].widget = forms.CheckboxSelectMultiple()
        if project is not None:
            self.fields['groups'].queryset = project.subject_groups.order_by('sort_order', 'name')

    def clean_key_binding(self):
        return (self.cleaned_data.get('key_binding') or '').upper()


class IndependentVariableDefinitionForm(forms.ModelForm):
    class Meta:
        model = IndependentVariableDefinition
        fields = ['label', 'description', 'value_type', 'set_values', 'default_value', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'set_values': forms.Textarea(attrs={'rows': 3}),
            'default_value': forms.TextInput(),
        }
        labels = {'label': _('Label'), 'description': _('Description'), 'value_type': _('Value type'), 'set_values': _('Allowed values'), 'default_value': _('Default value'), 'sort_order': _('Sort order')}


class BehaviorForm(forms.ModelForm):
    class Meta:
        model = Behavior
        fields = ['category', 'name', 'description', 'key_binding', 'color', 'mode', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'key_binding': forms.TextInput(attrs={'maxlength': 1}),
            'color': forms.TextInput(attrs={'type': 'color'}),
        }
        labels = {'category': _('Category'), 'name': _('Name'), 'description': _('Description'), 'key_binding': _('Key binding'), 'color': _('Color'), 'mode': _('Mode'), 'sort_order': _('Sort order')}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].required = False
        if project is not None:
            self.fields['category'].queryset = project.categories.all()

    def clean_key_binding(self):
        return self.cleaned_data['key_binding'].upper()


class ObservationTemplateForm(forms.ModelForm):
    class Meta:
        model = ObservationTemplate
        fields = [
            'name',
            'description',
            'default_session_kind',
            'behaviors',
            'modifiers',
            'subjects',
            'variable_definitions',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'behaviors': forms.CheckboxSelectMultiple(),
            'modifiers': forms.CheckboxSelectMultiple(),
            'subjects': forms.CheckboxSelectMultiple(),
            'variable_definitions': forms.CheckboxSelectMultiple(),
        }
        labels = {'name': _('Name'), 'description': _('Description'), 'default_session_kind': _('Default session kind'), 'behaviors': _('Behaviors'), 'modifiers': _('Modifiers'), 'subjects': _('Subjects'), 'variable_definitions': _('Independent variables')}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ['behaviors', 'modifiers', 'subjects', 'variable_definitions']:
            self.fields[field_name].required = False
            self.fields[field_name].widget = forms.CheckboxSelectMultiple()
        if project is not None:
            self.fields['behaviors'].queryset = project.behaviors.order_by('sort_order', 'name')
            self.fields['modifiers'].queryset = project.modifiers.order_by('sort_order', 'name')
            self.fields['subjects'].queryset = project.subjects.order_by('sort_order', 'name')
            self.fields['variable_definitions'].queryset = project.variable_definitions.order_by(
                'sort_order', 'label'
            )


class VideoAssetForm(forms.ModelForm):
    class Meta:
        model = VideoAsset
        fields = ['title', 'file', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 4})}
        labels = {'title': _('Title'), 'file': _('File'), 'notes': _('Notes')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['file'].required = False


class ObservationSessionForm(forms.ModelForm):
    additional_videos = forms.ModelMultipleChoiceField(
        queryset=VideoAsset.objects.none(),
        required=False,
        label=_('Additional synchronized videos'),
        help_text=_('Additional videos synchronized with the primary one.'),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ObservationSession
        fields = [
            'template',
            'keyboard_profile',
            'session_kind',
            'video',
            'additional_videos',
            'title',
            'description',
            'playback_rate',
            'frame_step_seconds',
            'recorded_at',
            'notes',
            'review_notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'review_notes': forms.Textarea(attrs={'rows': 3}),
            'recorded_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
        labels = {
            'template': _('Observation template'),
            'keyboard_profile': _('Keyboard profile'),
            'session_kind': _('Session kind'),
            'video': _('Primary video'),
            'title': _('Title'),
            'description': _('Description'),
            'playback_rate': _('Playback rate'),
            'frame_step_seconds': _('Frame step (seconds)'),
            'recorded_at': _('Recorded at'),
            'notes': _('Notes'),
            'review_notes': _('Review notes'),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.variable_definitions = []
        if project is not None:
            video_qs = project.videos.order_by('title')
            template_qs = project.observation_templates.order_by('name')
            self.fields['video'].queryset = video_qs
            self.fields['additional_videos'].queryset = video_qs
            self.fields['template'].queryset = template_qs
            self.fields['keyboard_profile'].queryset = project.keyboard_profiles.order_by('name')
            self.variable_definitions = list(
                project.variable_definitions.order_by('sort_order', 'label')
            )
            for definition in self.variable_definitions:
                field_name = f'var_{definition.pk}'
                if definition.value_type == IndependentVariableDefinition.TYPE_NUMERIC:
                    field = forms.DecimalField(required=False, label=definition.label)
                elif definition.value_type == IndependentVariableDefinition.TYPE_SET:
                    choices = [('', _('---------'))] + [
                        (item, item) for item in definition.value_options
                    ]
                    field = forms.ChoiceField(
                        required=False, label=definition.label, choices=choices
                    )
                elif definition.value_type == IndependentVariableDefinition.TYPE_BOOLEAN:
                    field = forms.TypedChoiceField(
                        required=False,
                        label=definition.label,
                        choices=[('', _('---------')), ('true', _('True')), ('false', _('False'))],
                        coerce=str,
                    )
                elif definition.value_type == IndependentVariableDefinition.TYPE_TIMESTAMP:
                    field = forms.DateTimeField(
                        required=False,
                        label=definition.label,
                        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
                    )
                elif definition.value_type == IndependentVariableDefinition.TYPE_LONGTEXT:
                    field = forms.CharField(
                        required=False,
                        label=definition.label,
                        widget=forms.Textarea(attrs={'rows': 3}),
                    )
                else:
                    field = forms.CharField(required=False, label=definition.label)
                help_text = definition.description or ''
                if (
                    definition.value_type == IndependentVariableDefinition.TYPE_SET
                    and definition.set_values
                ):
                    help_text = (
                        help_text + ' ' if help_text else ''
                    ) + _('Allowed values: %(values)s') % {'values': definition.set_values}
                field.help_text = help_text
                self.fields[field_name] = field
                initial_value = definition.default_value
                if self.instance and self.instance.pk:
                    existing = self.instance.variable_values.filter(definition=definition).first()
                    if existing:
                        initial_value = existing.value
                self.fields[field_name].initial = initial_value
        if self.instance and self.instance.pk:
            linked_ids = list(
                self.instance.video_links.exclude(video=self.instance.video).values_list(
                    'video_id', flat=True
                )
            )
            self.fields['additional_videos'].initial = linked_ids
            if self.instance.recorded_at:
                self.initial['recorded_at'] = self.instance.recorded_at.strftime('%Y-%m-%dT%H:%M')

    def clean(self):
        cleaned_data = super().clean()
        session_kind = cleaned_data.get('session_kind')
        video = cleaned_data.get('video')
        if session_kind == ObservationSession.KIND_MEDIA and video is None:
            self.add_error('video', _('A primary video is required for a media session.'))
        if session_kind == ObservationSession.KIND_MEDIA and not cleaned_data.get('title'):
            self.add_error('title', _('A title is required for a media observation session.'))
        if session_kind == ObservationSession.KIND_LIVE and not cleaned_data.get('title'):
            self.add_error('title', _('A title is required for a live observation session.'))
        if session_kind == ObservationSession.KIND_LIVE:
            cleaned_data['video'] = None
            cleaned_data['additional_videos'] = []
        return cleaned_data

    def save_variable_values(self, session):
        if not self.project:
            return
        for definition in self.variable_definitions:
            field_name = f'var_{definition.pk}'
            value = self.cleaned_data.get(field_name, '')
            if value is None:
                value = ''
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            ObservationVariableValue.objects.update_or_create(
                session=session,
                definition=definition,
                defaults={'value': str(value)},
            )


class DeleteConfirmForm(forms.Form):
    confirm = forms.BooleanField(label=_('I confirm the deletion'))
