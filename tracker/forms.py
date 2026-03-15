from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import (
    Behavior,
    BehaviorCategory,
    Modifier,
    ObservationSession,
    VideoAsset,
    Project,
)


User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }


class ProjectSettingsForm(forms.ModelForm):
    collaborators = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Project
        fields = ['name', 'description', 'collaborators']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = User.objects.order_by('username')
        if owner is not None:
            queryset = queryset.exclude(pk=owner.pk)
        self.fields['collaborators'].queryset = queryset


class EthogramImportForm(forms.Form):
    file = forms.FileField(help_text='Fichier JSON exporté depuis CowLog Django V4.')
    replace_existing = forms.BooleanField(
        required=False,
        label='Remplacer complètement les catégories, modificateurs et comportements existants',
        help_text=(
            'Refusé si le projet contient déjà des sessions ou des événements pour éviter une perte de données.'
        ),
    )


class BehaviorCategoryForm(forms.ModelForm):
    class Meta:
        model = BehaviorCategory
        fields = ['name', 'color', 'sort_order']
        widgets = {
            'color': forms.TextInput(attrs={'type': 'color'}),
        }


class ModifierForm(forms.ModelForm):
    class Meta:
        model = Modifier
        fields = ['name', 'description', 'key_binding', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'key_binding': forms.TextInput(attrs={'maxlength': 1}),
        }

    def clean_key_binding(self):
        return self.cleaned_data['key_binding'].upper()


class BehaviorForm(forms.ModelForm):
    class Meta:
        model = Behavior
        fields = ['category', 'name', 'description', 'key_binding', 'color', 'mode', 'sort_order']
        widgets = {
            'description': forms.TextInput(),
            'key_binding': forms.TextInput(attrs={'maxlength': 1}),
            'color': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].required = False
        if project is not None:
            self.fields['category'].queryset = project.categories.all()

    def clean_key_binding(self):
        return self.cleaned_data['key_binding'].upper()


class VideoAssetForm(forms.ModelForm):
    class Meta:
        model = VideoAsset
        fields = ['title', 'file', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['file'].required = False


class ObservationSessionForm(forms.ModelForm):
    additional_videos = forms.ModelMultipleChoiceField(
        queryset=VideoAsset.objects.none(),
        required=False,
        help_text='Vidéos secondaires synchronisées avec la vidéo principale dans le lecteur V4.',
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ObservationSession
        fields = ['video', 'additional_videos', 'title', 'playback_rate', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None:
            video_qs = project.videos.order_by('title')
            self.fields['video'].queryset = video_qs
            self.fields['additional_videos'].queryset = video_qs
        if self.instance and self.instance.pk:
            linked_ids = list(self.instance.video_links.exclude(video=self.instance.video).values_list('video_id', flat=True))
            self.fields['additional_videos'].initial = linked_ids


class DeleteConfirmForm(forms.Form):
    confirm = forms.BooleanField(label='Je confirme la suppression')
