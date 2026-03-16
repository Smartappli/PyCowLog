from django.contrib import admin

from .models import (
    Behavior,
    BehaviorCategory,
    IndependentVariableDefinition,
    Modifier,
    ObservationAuditLog,
    ObservationEvent,
    ObservationSession,
    ObservationTemplate,
    ObservationVariableValue,
    Project,
    SessionAnnotation,
    SessionVideoLink,
    Subject,
    SubjectGroup,
    VideoAsset,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    search_fields = ('name', 'owner__username')
    filter_horizontal = ('collaborators',)


@admin.register(BehaviorCategory)
class BehaviorCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'sort_order', 'color')
    list_filter = ('project',)
    search_fields = ('name',)


@admin.register(Modifier)
class ModifierAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'key_binding', 'sort_order')
    list_filter = ('project',)
    search_fields = ('name', 'description')


@admin.register(SubjectGroup)
class SubjectGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'sort_order', 'color')
    list_filter = ('project',)
    search_fields = ('name', 'description')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'key_binding', 'sort_order', 'color')
    list_filter = ('project', 'groups')
    search_fields = ('name', 'description')
    filter_horizontal = ('groups',)


@admin.register(IndependentVariableDefinition)
class IndependentVariableDefinitionAdmin(admin.ModelAdmin):
    list_display = ('label', 'project', 'value_type', 'sort_order', 'default_value')
    list_filter = ('project', 'value_type')
    search_fields = ('label', 'description', 'set_values')


@admin.register(Behavior)
class BehaviorAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'mode', 'key_binding', 'category', 'sort_order')
    list_filter = ('project', 'mode', 'category')
    search_fields = ('name', 'description')


@admin.register(ObservationTemplate)
class ObservationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'default_session_kind', 'created_at')
    list_filter = ('project', 'default_session_kind')
    search_fields = ('name', 'description')
    filter_horizontal = ('behaviors', 'modifiers', 'subjects', 'variable_definitions')


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'uploaded_at')
    list_filter = ('project',)
    search_fields = ('title', 'notes')


class SessionVideoInline(admin.TabularInline):
    model = SessionVideoLink
    extra = 0


class VariableValueInline(admin.TabularInline):
    model = ObservationVariableValue
    extra = 0


@admin.register(ObservationSession)
class ObservationSessionAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'project',
        'session_kind',
        'workflow_status',
        'video',
        'observer',
        'playback_rate',
        'frame_step_seconds',
        'created_at',
    )
    list_filter = ('project', 'session_kind', 'workflow_status', 'observer')
    search_fields = ('title', 'notes', 'description', 'review_notes')
    inlines = [SessionVideoInline, VariableValueInline]


@admin.register(ObservationEvent)
class ObservationEventAdmin(admin.ModelAdmin):
    list_display = (
        'session',
        'subject',
        'behavior',
        'event_kind',
        'timestamp_seconds',
        'frame_index',
        'created_at',
    )
    list_filter = ('session__project', 'event_kind', 'behavior__mode', 'subject', 'subjects')
    search_fields = ('session__title', 'behavior__name', 'subject__name', 'comment')
    filter_horizontal = ('modifiers', 'subjects')


@admin.register(SessionAnnotation)
class SessionAnnotationAdmin(admin.ModelAdmin):
    list_display = ('session', 'title', 'timestamp_seconds', 'created_by', 'created_at')
    list_filter = ('session__project',)
    search_fields = ('session__title', 'title', 'note')


@admin.register(SessionVideoLink)
class SessionVideoLinkAdmin(admin.ModelAdmin):
    list_display = ('session', 'video', 'sort_order')
    list_filter = ('session__project',)


@admin.register(ObservationVariableValue)
class ObservationVariableValueAdmin(admin.ModelAdmin):
    list_display = ('session', 'definition', 'value')
    list_filter = ('session__project', 'definition')
    search_fields = ('session__title', 'definition__label', 'value')


@admin.register(ObservationAuditLog)
class ObservationAuditLogAdmin(admin.ModelAdmin):
    list_display = ('session', 'action', 'target_type', 'target_id', 'actor', 'created_at')
    list_filter = ('session__project', 'action', 'target_type')
    search_fields = ('session__title', 'summary', 'actor__username')
