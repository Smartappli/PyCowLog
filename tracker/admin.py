from django.contrib import admin

from .models import (
    Behavior,
    BehaviorCategory,
    Modifier,
    ObservationEvent,
    ObservationSession,
    Project,
    SessionVideoLink,
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


@admin.register(Behavior)
class BehaviorAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'mode', 'key_binding', 'category', 'sort_order')
    list_filter = ('project', 'mode', 'category')
    search_fields = ('name', 'description')


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'uploaded_at')
    list_filter = ('project',)
    search_fields = ('title', 'notes')


class SessionVideoInline(admin.TabularInline):
    model = SessionVideoLink
    extra = 0


@admin.register(ObservationSession)
class ObservationSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'video', 'observer', 'playback_rate', 'created_at')
    list_filter = ('project', 'observer')
    search_fields = ('title', 'notes')
    inlines = [SessionVideoInline]


@admin.register(ObservationEvent)
class ObservationEventAdmin(admin.ModelAdmin):
    list_display = ('session', 'behavior', 'event_kind', 'timestamp_seconds', 'created_at')
    list_filter = ('session__project', 'event_kind', 'behavior__mode')
    search_fields = ('session__title', 'behavior__name', 'comment')
    filter_horizontal = ('modifiers',)


@admin.register(SessionVideoLink)
class SessionVideoLinkAdmin(admin.ModelAdmin):
    list_display = ('session', 'video', 'sort_order')
    list_filter = ('session__project',)
