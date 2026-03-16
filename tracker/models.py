from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_cowlog_projects',
    )
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='shared_cowlog_projects',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'name'], name='unique_project_name_per_owner'),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self):
        return reverse('tracker:project_detail', args=[self.pk])

    def role_for_user(self, user) -> str | None:
        """Return the effective role of a user inside the project."""
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        if self.owner_id == user.id:
            return ProjectMembership.ROLE_OWNER
        membership = self.memberships.filter(user=user).only('role').first()
        if membership is not None:
            return membership.role
        if self.collaborators.filter(pk=user.pk).exists():
            return ProjectMembership.ROLE_EDITOR
        return None

    def can_view(self, user) -> bool:
        return self.role_for_user(user) is not None

    def can_edit(self, user) -> bool:
        return self.role_for_user(user) in {
            ProjectMembership.ROLE_OWNER,
            ProjectMembership.ROLE_EDITOR,
        }

    def can_review(self, user) -> bool:
        return self.role_for_user(user) in {
            ProjectMembership.ROLE_OWNER,
            ProjectMembership.ROLE_EDITOR,
            ProjectMembership.ROLE_REVIEWER,
        }

    def can_manage_members(self, user) -> bool:
        return self.role_for_user(user) == ProjectMembership.ROLE_OWNER


class ProjectMembership(models.Model):
    """Explicit project membership with a role-based permission model."""

    ROLE_OWNER = 'owner'
    ROLE_EDITOR = 'editor'
    ROLE_REVIEWER = 'reviewer'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_OWNER, _('Owner')),
        (ROLE_EDITOR, _('Editor')),
        (ROLE_REVIEWER, _('Reviewer')),
        (ROLE_VIEWER, _('Viewer')),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pybehaviorlog_memberships',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project__name', 'user__username']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'user'],
                name='unique_project_membership',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.project.name} - {self.user.username} ({self.role})'


class KeyboardProfile(models.Model):
    """Reusable keyboard profile overriding project-level shortcut defaults."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='keyboard_profiles')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    behavior_bindings = models.JSONField(default=dict, blank=True)
    modifier_bindings = models.JSONField(default=dict, blank=True)
    subject_bindings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'],
                name='unique_keyboard_profile_name_per_project',
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        for attribute in ('behavior_bindings', 'modifier_bindings', 'subject_bindings'):
            payload = getattr(self, attribute) or {}
            cleaned = {
                str(key): (str(value).upper()[:1] if value else '')
                for key, value in payload.items()
                if str(value).strip()
            }
            setattr(self, attribute, cleaned)
        super().save(*args, **kwargs)
        if self.is_default:
            KeyboardProfile.objects.filter(project=self.project).exclude(pk=self.pk).update(
                is_default=False
            )


class BehaviorCategory(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=120)
    color = models.CharField(max_length=7, default='#0f766e')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_category_name_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Modifier(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='modifiers')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    key_binding = models.CharField(max_length=1)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_modifier_name_per_project'
            ),
            models.UniqueConstraint(
                fields=['project', 'key_binding'], name='unique_modifier_key_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.key_binding = self.key_binding.upper()
        super().save(*args, **kwargs)


class SubjectGroup(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='subject_groups')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=7, default='#7c3aed')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_subject_group_name_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Subject(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='subjects')
    groups = models.ManyToManyField(SubjectGroup, blank=True, related_name='subjects')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    key_binding = models.CharField(max_length=1, blank=True)
    color = models.CharField(max_length=7, default='#9333ea')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_subject_name_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.key_binding = (self.key_binding or '').upper()
        super().save(*args, **kwargs)


class IndependentVariableDefinition(models.Model):
    TYPE_TEXT = 'text'
    TYPE_LONGTEXT = 'longtext'
    TYPE_NUMERIC = 'numeric'
    TYPE_SET = 'set'
    TYPE_BOOLEAN = 'boolean'
    TYPE_TIMESTAMP = 'timestamp'
    TYPE_CHOICES = [
        (TYPE_TEXT, _('Text')),
        (TYPE_LONGTEXT, _('Long text')),
        (TYPE_NUMERIC, _('Numeric')),
        (TYPE_SET, _('Value from a list')),
        (TYPE_BOOLEAN, _('Boolean')),
        (TYPE_TIMESTAMP, _('Timestamp')),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='variable_definitions'
    )
    label = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    value_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_TEXT)
    set_values = models.TextField(blank=True, help_text=_('Comma-separated values for list fields.'))
    default_value = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'label']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'label'], name='unique_variable_label_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.label

    @property
    def value_options(self) -> list[str]:
        if self.value_type != self.TYPE_SET:
            return []
        return [item.strip() for item in self.set_values.split(',') if item.strip()]


class Behavior(models.Model):
    MODE_POINT = 'point'
    MODE_STATE = 'state'
    MODE_CHOICES = [
        (MODE_POINT, _('Point')),
        (MODE_STATE, _('State')),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='behaviors')
    category = models.ForeignKey(
        BehaviorCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='behaviors',
    )
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=255, blank=True)
    key_binding = models.CharField(max_length=1)
    color = models.CharField(max_length=7, default='#2563eb')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_POINT)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_behavior_name_per_project_v2'
            ),
            models.UniqueConstraint(
                fields=['project', 'key_binding'], name='unique_behavior_key_per_project_v2'
            ),
        ]

    def __str__(self) -> str:
        return f'{self.project.name} - {self.name}'

    def save(self, *args, **kwargs):
        self.key_binding = self.key_binding.upper()
        super().save(*args, **kwargs)


class ObservationTemplate(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='observation_templates'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    behaviors = models.ManyToManyField(Behavior, blank=True, related_name='templates')
    modifiers = models.ManyToManyField(Modifier, blank=True, related_name='templates')
    subjects = models.ManyToManyField(Subject, blank=True, related_name='templates')
    variable_definitions = models.ManyToManyField(
        IndependentVariableDefinition,
        blank=True,
        related_name='templates',
    )
    default_session_kind = models.CharField(max_length=10, default='media')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'], name='unique_template_name_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.name


class VideoAsset(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='videos/')
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['title', '-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'title'], name='unique_video_title_per_project'
            ),
        ]

    def __str__(self) -> str:
        return self.title


class ObservationSession(models.Model):
    KIND_MEDIA = 'media'
    KIND_LIVE = 'live'
    KIND_CHOICES = [
        (KIND_MEDIA, _('Media')),
        (KIND_LIVE, _('Live')),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_IN_REVIEW = 'in_review'
    STATUS_VALIDATED = 'validated'
    STATUS_LOCKED = 'locked'
    STATUS_CHOICES = [
        (STATUS_DRAFT, _('Draft')),
        (STATUS_IN_REVIEW, _('In review')),
        (STATUS_VALIDATED, _('Validated')),
        (STATUS_LOCKED, _('Locked')),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='sessions')
    video = models.ForeignKey(
        VideoAsset,
        on_delete=models.SET_NULL,
        related_name='sessions',
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        ObservationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessions',
    )
    keyboard_profile = models.ForeignKey(
        KeyboardProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessions',
    )
    session_kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_MEDIA)
    workflow_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    observer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cowlog_sessions',
    )
    notes = models.TextField(blank=True)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_cowlog_sessions',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    playback_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.00,
        validators=[MinValueValidator(0.25), MaxValueValidator(4.00)],
    )
    frame_step_seconds = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=0.0400,
        validators=[MinValueValidator(0.0010), MaxValueValidator(1.0000)],
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self):
        return reverse('tracker:session_player', args=[self.pk])

    @property
    def all_videos_ordered(self):
        links = list(self.video_links.select_related('video').order_by('sort_order', 'pk'))
        if links:
            return [link.video for link in links if link.video_id]
        return [self.video] if self.video_id else []

    @property
    def primary_label(self) -> str:
        if self.session_kind == self.KIND_LIVE:
            return 'LIVE'
        return self.video.title if self.video_id else 'No media'

    @property
    def effective_keyboard_profile(self):
        if self.keyboard_profile_id:
            return self.keyboard_profile
        return self.project.keyboard_profiles.filter(is_default=True).first()

    @property
    def is_locked_for_coding(self) -> bool:
        return self.workflow_status == self.STATUS_LOCKED


class ObservationVariableValue(models.Model):
    session = models.ForeignKey(
        ObservationSession, on_delete=models.CASCADE, related_name='variable_values'
    )
    definition = models.ForeignKey(
        IndependentVariableDefinition, on_delete=models.CASCADE, related_name='values'
    )
    value = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['definition__sort_order', 'definition__label']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'definition'], name='unique_variable_value_per_session'
            ),
        ]

    def __str__(self) -> str:
        return f'{self.session.title} - {self.definition.label}: {self.value}'


class SessionVideoLink(models.Model):
    session = models.ForeignKey(
        ObservationSession, on_delete=models.CASCADE, related_name='video_links'
    )
    video = models.ForeignKey(VideoAsset, on_delete=models.CASCADE, related_name='session_links')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['session', 'video'], name='unique_video_per_session'),
        ]

    def __str__(self) -> str:
        return f'{self.session.title} - {self.video.title}'


class ObservationSegment(models.Model):
    STATUS_TODO = 'todo'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_DONE = 'done'
    STATUS_CHOICES = [
        (STATUS_TODO, _('To do')),
        (STATUS_IN_PROGRESS, _('In progress')),
        (STATUS_DONE, _('Done')),
    ]

    session = models.ForeignKey(
        ObservationSession, on_delete=models.CASCADE, related_name='segments'
    )
    title = models.CharField(max_length=160)
    start_seconds = models.DecimalField(max_digits=10, decimal_places=3)
    end_seconds = models.DecimalField(max_digits=10, decimal_places=3)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TODO)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_observation_segments',
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='review_observation_segments',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_seconds', 'end_seconds', 'pk']

    def __str__(self) -> str:
        return f'{self.session.title} - {self.title} [{self.start_seconds}, {self.end_seconds}]'

    @property
    def duration_seconds(self) -> float:
        return round(float(self.end_seconds - self.start_seconds), 3)



class ObservationEvent(models.Model):
    KIND_POINT = 'point'
    KIND_START = 'start'
    KIND_STOP = 'stop'
    KIND_CHOICES = [
        (KIND_POINT, _('Point')),
        (KIND_START, _('Start')),
        (KIND_STOP, _('Stop')),
    ]

    session = models.ForeignKey(ObservationSession, on_delete=models.CASCADE, related_name='events')
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        related_name='events',
        null=True,
        blank=True,
    )
    subjects = models.ManyToManyField(Subject, blank=True, related_name='multi_events')
    behavior = models.ForeignKey(Behavior, on_delete=models.CASCADE, related_name='events')
    event_kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    timestamp_seconds = models.DecimalField(max_digits=10, decimal_places=3)
    frame_index = models.PositiveIntegerField(null=True, blank=True)
    comment = models.CharField(max_length=255, blank=True)
    modifiers = models.ManyToManyField(Modifier, blank=True, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp_seconds', 'pk']

    def __str__(self) -> str:
        return f'{self.session.title} - {self.behavior.name} - {self.event_kind} @ {self.timestamp_seconds}s'

    @property
    def modifiers_display(self) -> str:
        return ', '.join(
            self.modifiers.order_by('sort_order', 'name').values_list('name', flat=True)
        )

    @property
    def all_subjects_ordered(self) -> list[Subject]:
        subjects = list(self.subjects.order_by('sort_order', 'name'))
        if subjects:
            return subjects
        return [self.subject] if self.subject_id else []

    @property
    def subjects_display(self) -> str:
        return ', '.join(subject.name for subject in self.all_subjects_ordered)


class SessionAnnotation(models.Model):
    session = models.ForeignKey(
        ObservationSession, on_delete=models.CASCADE, related_name='annotations'
    )
    timestamp_seconds = models.DecimalField(max_digits=10, decimal_places=3)
    title = models.CharField(max_length=120)
    note = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#f59e0b')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cowlog_annotations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp_seconds', 'pk']

    def __str__(self) -> str:
        return f'{self.session.title} - {self.title} @ {self.timestamp_seconds}s'


class ObservationAuditLog(models.Model):
    TARGET_EVENT = 'event'
    TARGET_ANNOTATION = 'annotation'
    TARGET_SESSION = 'session'
    TARGET_IMPORT = 'import'
    TARGET_EXPORT = 'export'
    TARGET_CHOICES = [
        (TARGET_EVENT, _('Event')),
        (TARGET_ANNOTATION, _('Annotation')),
        (TARGET_SESSION, _('Session')),
        (TARGET_IMPORT, _('Import')),
        (TARGET_EXPORT, _('Export')),
    ]

    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_STATUS = 'status'
    ACTION_IMPORT = 'import'
    ACTION_EXPORT = 'export'
    ACTION_CHOICES = [
        (ACTION_CREATE, _('Create')),
        (ACTION_UPDATE, _('Update')),
        (ACTION_DELETE, _('Delete')),
        (ACTION_STATUS, _('Status change')),
        (ACTION_IMPORT, _('Import')),
        (ACTION_EXPORT, _('Export')),
    ]

    session = models.ForeignKey(
        ObservationSession, on_delete=models.CASCADE, related_name='audit_logs'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cowlog_audit_logs',
    )
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    summary = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self) -> str:
        return f'{self.session.title} - {self.action} {self.target_type}'
