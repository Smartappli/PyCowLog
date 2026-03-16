from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from openpyxl import Workbook

from .forms import (
    BehaviorCategoryForm,
    BehaviorForm,
    DeleteConfirmForm,
    EthogramImportForm,
    IndependentVariableDefinitionForm,
    KeyboardProfileForm,
    ModifierForm,
    ObservationSessionForm,
    ObservationTemplateForm,
    ProjectBORISImportForm,
    ProjectForm,
    ProjectMembershipForm,
    ProjectSettingsForm,
    SessionImportForm,
    SignUpForm,
    SubjectForm,
    SubjectGroupForm,
    VideoAssetForm,
)
from .models import (
    Behavior,
    BehaviorCategory,
    IndependentVariableDefinition,
    KeyboardProfile,
    Modifier,
    ObservationAuditLog,
    ObservationEvent,
    ObservationSession,
    ObservationTemplate,
    ObservationVariableValue,
    Project,
    ProjectMembership,
    SessionAnnotation,
    SessionVideoLink,
    Subject,
    SubjectGroup,
    VideoAsset,
)


def signup(request):  # pragma: no cover
    if request.user.is_authenticated:
        return redirect('tracker:home')

    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, _('Account created successfully.'))
        return redirect('tracker:home')
    return render(request, 'registration/signup.html', {'form': form})


def accessible_projects_qs(user):
    """Return every project visible to the current authenticated user."""
    return (
        Project.objects.filter(
            Q(owner=user) | Q(collaborators=user) | Q(memberships__user=user)
        )
        .distinct()
        .select_related('owner')
        .prefetch_related('collaborators', 'memberships__user', 'keyboard_profiles')
    )


def get_accessible_project(user, pk: int) -> Project:
    return get_object_or_404(accessible_projects_qs(user), pk=pk)


def project_role(user, project: Project) -> str | None:
    return project.role_for_user(user)


def _require_project_owner(user, project: Project, message: str | None = None) -> None:
    if project_role(user, project) != ProjectMembership.ROLE_OWNER:
        raise PermissionDenied(message or _('Only the project owner can update project settings.'))


def _require_project_editor(user, project: Project, message: str | None = None) -> None:
    if not project.can_edit(user):
        raise PermissionDenied(message or _('You need editor permissions for this project.'))


def _require_project_reviewer(user, project: Project, message: str | None = None) -> None:
    if not project.can_review(user):
        raise PermissionDenied(message or _('You need reviewer permissions for this project.'))


def get_owned_project(user, pk: int) -> Project:
    project = get_accessible_project(user, pk)
    _require_project_owner(user, project)
    return project


def accessible_sessions_qs(user):
    return (
        ObservationSession.objects.filter(
            Q(project__owner=user)
            | Q(project__collaborators=user)
            | Q(project__memberships__user=user)
        )
        .distinct()
        .select_related('project', 'video', 'observer', 'project__owner', 'keyboard_profile')
    )


def get_accessible_session(user, pk: int) -> ObservationSession:
    session_qs = accessible_sessions_qs(user).prefetch_related(
        'project__behaviors__category',
        'project__modifiers',
        'project__categories',
        'project__subjects__groups',
        'project__subject_groups',
        'project__variable_definitions',
        'project__observation_templates',
        'project__keyboard_profiles',
        'video_links__video',
        'variable_values__definition',
        'audit_logs__actor',
        Prefetch(
            'events',
            queryset=ObservationEvent.objects.select_related(
                'behavior', 'behavior__category', 'subject'
            )
            .prefetch_related('modifiers', 'subjects')
            .order_by('timestamp_seconds', 'pk'),
        ),
        'annotations',
    )
    return get_object_or_404(session_qs, pk=pk)


def _get_owned_category(user, pk: int) -> BehaviorCategory:
    category = get_object_or_404(BehaviorCategory.objects.select_related('project'), pk=pk)
    _require_project_editor(user, category.project, _('You need editor permissions to manage categories.'))
    return category


def _get_owned_modifier(user, pk: int) -> Modifier:
    modifier = get_object_or_404(Modifier.objects.select_related('project'), pk=pk)
    _require_project_editor(user, modifier.project, _('You need editor permissions to manage modifiers.'))
    return modifier


def _get_owned_behavior(user, pk: int) -> Behavior:
    behavior = get_object_or_404(Behavior.objects.select_related('project', 'category'), pk=pk)
    _require_project_editor(user, behavior.project, _('You need editor permissions to manage behaviors.'))
    return behavior


def _get_owned_video(user, pk: int) -> VideoAsset:
    video = get_object_or_404(VideoAsset.objects.select_related('project'), pk=pk)
    _require_project_editor(user, video.project, _('You need editor permissions to manage videos.'))
    return video


def _require_editable_session(session: ObservationSession, user=None) -> None:
    if user is not None and not session.project.can_edit(user):
        raise PermissionDenied(_('You need editor permissions to modify this session.'))
    if session.is_locked_for_coding:
        raise PermissionDenied(_('This session is locked and cannot be modified.'))


def _log_audit(
    session: ObservationSession,
    *,
    actor,
    action: str,
    target_type: str,
    summary: str,
    payload: dict | None = None,
    target_id: int | None = None,
) -> ObservationAuditLog:
    return ObservationAuditLog.objects.create(
        session=session,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        payload=payload or {},
    )


def _decimal(value, default: str = '0') -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _session_duration(
    session: ObservationSession, duration_hint: str | float | Decimal | None = None
) -> Decimal:
    duration = _decimal(duration_hint, default='0')
    if duration > 0:
        return duration
    last_event = (
        ObservationEvent.objects.filter(session=session).order_by('-timestamp_seconds').first()
    )
    last_annotation = (
        SessionAnnotation.objects.filter(session=session).order_by('-timestamp_seconds').first()
    )
    candidates = [Decimal('0')]
    if last_event is not None:
        candidates.append(last_event.timestamp_seconds)
    if last_annotation is not None:
        candidates.append(last_annotation.timestamp_seconds)
    return max(candidates)


def serialize_event(event: ObservationEvent) -> dict:
    modifiers = list(
        event.modifiers.order_by('sort_order', 'name').values('id', 'name', 'key_binding')
    )
    subjects = [
        {
            'id': subject.id,
            'name': subject.name,
            'key_binding': subject.key_binding,
            'color': subject.color,
            'groups': [group.name for group in subject.groups.order_by('sort_order', 'name')],
        }
        for subject in event.all_subjects_ordered
    ]
    return {
        'id': event.pk,
        'behavior': event.behavior.name,
        'behavior_id': event.behavior_id,
        'behavior_mode': event.behavior.mode,
        'category': event.behavior.category.name if event.behavior.category else '',
        'color': event.behavior.color,
        'event_kind': event.event_kind,
        'timestamp_seconds': float(event.timestamp_seconds),
        'frame_index': event.frame_index,
        'comment': event.comment,
        'subject': event.subject.name if event.subject_id else '',
        'subject_id': event.subject_id,
        'subjects': subjects,
        'subjects_display': ', '.join(item['name'] for item in subjects),
        'modifiers': modifiers,
        'created_at': event.created_at.isoformat(),
    }


def serialize_annotation(annotation: SessionAnnotation) -> dict:
    return {
        'id': annotation.pk,
        'timestamp_seconds': float(annotation.timestamp_seconds),
        'title': annotation.title,
        'note': annotation.note,
        'color': annotation.color,
        'created_by': annotation.created_by.username if annotation.created_by else '',
        'created_at': annotation.created_at.isoformat(),
    }


def compute_state_status(session: ObservationSession) -> dict[int, bool]:
    state_map: dict[int, bool] = {}
    state_behaviors = {
        behavior.id for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE)
    }
    for behavior_id in state_behaviors:
        state_map[behavior_id] = False

    event_qs = (
        ObservationEvent.objects.filter(session=session)
        .select_related('behavior')
        .order_by('timestamp_seconds', 'pk')
    )
    for event in event_qs:
        if event.behavior.mode != Behavior.MODE_STATE:
            continue
        if event.event_kind == ObservationEvent.KIND_START:
            state_map[event.behavior_id] = True
        elif event.event_kind == ObservationEvent.KIND_STOP:
            state_map[event.behavior_id] = False
    return state_map


def build_statistics(
    session: ObservationSession, duration_hint: str | float | Decimal | None = None
) -> dict:
    end_time = _session_duration(session, duration_hint)
    behaviors = list(
        session.project.behaviors.select_related('category').order_by('sort_order', 'name')
    )
    events = list(session.events.all())
    stats: dict[int, dict] = {}
    open_states: dict[int, Decimal | None] = {}

    for behavior in behaviors:
        stats[behavior.id] = {
            'behavior_id': behavior.id,
            'name': behavior.name,
            'category': behavior.category.name if behavior.category else '',
            'mode': behavior.mode,
            'color': behavior.color,
            'point_count': 0,
            'start_count': 0,
            'stop_count': 0,
            'segment_count': 0,
            'total_duration_seconds': Decimal('0'),
            'occupancy_percent': 0.0,
            'is_open': False,
        }
        open_states[behavior.id] = None

    for event in events:
        item = stats[event.behavior_id]
        if event.event_kind == ObservationEvent.KIND_POINT:
            item['point_count'] += 1
            continue
        if event.event_kind == ObservationEvent.KIND_START:
            item['start_count'] += 1
            open_states[event.behavior_id] = event.timestamp_seconds
            item['is_open'] = True
            continue
        if event.event_kind == ObservationEvent.KIND_STOP:
            item['stop_count'] += 1
            start_time = open_states.get(event.behavior_id)
            if start_time is not None and event.timestamp_seconds >= start_time:
                item['segment_count'] += 1
                item['total_duration_seconds'] += event.timestamp_seconds - start_time
            open_states[event.behavior_id] = None
            item['is_open'] = False

    for behavior in behaviors:
        start_time = open_states.get(behavior.id)
        if (
            behavior.mode == Behavior.MODE_STATE
            and start_time is not None
            and end_time >= start_time
        ):
            stats[behavior.id]['segment_count'] += 1
            stats[behavior.id]['total_duration_seconds'] += end_time - start_time
            stats[behavior.id]['is_open'] = True

    rows = []
    total_duration = Decimal('0')
    total_points = 0
    open_count = 0
    for behavior in behaviors:
        item = stats[behavior.id]
        total_duration += item['total_duration_seconds']
        total_points += item['point_count']
        if item['is_open']:
            open_count += 1
        if end_time > 0 and behavior.mode == Behavior.MODE_STATE:
            item['occupancy_percent'] = round(
                float((item['total_duration_seconds'] / end_time) * 100), 2
            )
        rows.append({**item, 'total_duration_seconds': float(item['total_duration_seconds'])})

    return {
        'session_event_count': len(events),
        'annotation_count': session.annotations.count(),
        'point_event_count': total_points,
        'open_state_count': open_count,
        'observed_span_seconds': float(end_time),
        'state_duration_seconds': float(total_duration),
        'rows': rows,
    }


def build_timeline_buckets(
    session: ObservationSession,
    duration_hint: str | float | Decimal | None = None,
    bucket_seconds: int = 60,
) -> list[dict]:
    duration = _session_duration(session, duration_hint)
    if duration <= 0:
        return []

    bucket_map: dict[int, dict] = {}
    ordered_behaviors = list(session.project.behaviors.order_by('sort_order', 'name'))
    behavior_names = {behavior.id: behavior.name for behavior in ordered_behaviors}
    for event in session.events.all():
        bucket_index = int(float(event.timestamp_seconds) // bucket_seconds)
        bucket = bucket_map.setdefault(
            bucket_index,
            {
                'index': bucket_index,
                'start_seconds': bucket_index * bucket_seconds,
                'end_seconds': (bucket_index + 1) * bucket_seconds,
                'event_count': 0,
                'point_count': 0,
                'state_change_count': 0,
                'annotation_count': 0,
                'labels': defaultdict(int),
            },
        )
        bucket['event_count'] += 1
        if event.event_kind == ObservationEvent.KIND_POINT:
            bucket['point_count'] += 1
        else:
            bucket['state_change_count'] += 1
        bucket['labels'][behavior_names[event.behavior_id]] += 1

    for annotation in session.annotations.all():
        bucket_index = int(float(annotation.timestamp_seconds) // bucket_seconds)
        bucket = bucket_map.setdefault(
            bucket_index,
            {
                'index': bucket_index,
                'start_seconds': bucket_index * bucket_seconds,
                'end_seconds': (bucket_index + 1) * bucket_seconds,
                'event_count': 0,
                'point_count': 0,
                'state_change_count': 0,
                'annotation_count': 0,
                'labels': defaultdict(int),
            },
        )
        bucket['annotation_count'] += 1
        bucket['labels'][f'Note: {annotation.title}'] += 1

    results = []
    total_buckets = int((float(duration) // bucket_seconds) + 1)
    for index in range(total_buckets):
        bucket = bucket_map.get(index)
        if bucket is None:
            bucket = {
                'index': index,
                'start_seconds': index * bucket_seconds,
                'end_seconds': (index + 1) * bucket_seconds,
                'event_count': 0,
                'point_count': 0,
                'state_change_count': 0,
                'annotation_count': 0,
                'labels': {},
            }
        else:
            bucket['labels'] = dict(
                sorted(bucket['labels'].items(), key=lambda item: (-item[1], item[0]))[:5]
            )
        results.append(bucket)
    return results


def build_track_rows(
    session: ObservationSession, duration_hint: str | float | Decimal | None = None
) -> list[dict]:
    duration = _session_duration(session, duration_hint)
    behaviors = list(
        session.project.behaviors.select_related('category').order_by('sort_order', 'name')
    )
    tracks: dict[int, dict] = {
        behavior.id: {
            'behavior_id': behavior.id,
            'name': behavior.name,
            'category': behavior.category.name if behavior.category else '',
            'mode': behavior.mode,
            'color': behavior.color,
            'segments': [],
            'points': [],
            'total_duration_seconds': 0.0,
        }
        for behavior in behaviors
    }
    open_states: dict[int, Decimal | None] = {behavior.id: None for behavior in behaviors}
    for event in session.events.all():
        track = tracks[event.behavior_id]
        if event.event_kind == ObservationEvent.KIND_POINT:
            track['points'].append({
                'event_id': event.id,
                'seconds': float(event.timestamp_seconds),
                'label': event.behavior.name,
            })
            continue
        if event.event_kind == ObservationEvent.KIND_START:
            open_states[event.behavior_id] = event.timestamp_seconds
            continue
        start_time = open_states.get(event.behavior_id)
        if start_time is not None and event.timestamp_seconds >= start_time:
            segment = {
                'start_seconds': float(start_time),
                'end_seconds': float(event.timestamp_seconds),
                'start_event_id': next((item.id for item in session.events.filter(behavior_id=event.behavior_id, event_kind=ObservationEvent.KIND_START, timestamp_seconds=start_time).order_by('pk')), None),
                'stop_event_id': event.id,
                'open': False,
            }
            track['segments'].append(segment)
            track['total_duration_seconds'] += segment['end_seconds'] - segment['start_seconds']
        open_states[event.behavior_id] = None

    for behavior in behaviors:
        start_time = open_states.get(behavior.id)
        if (
            behavior.mode == Behavior.MODE_STATE
            and start_time is not None
            and duration >= start_time
        ):
            segment = {
                'start_seconds': float(start_time),
                'end_seconds': float(duration),
                'start_event_id': next((item.id for item in session.events.filter(behavior_id=behavior.id, event_kind=ObservationEvent.KIND_START, timestamp_seconds=start_time).order_by('pk')), None),
                'stop_event_id': None,
                'open': True,
            }
            tracks[behavior.id]['segments'].append(segment)
            tracks[behavior.id]['total_duration_seconds'] += (
                segment['end_seconds'] - segment['start_seconds']
            )

    return list(tracks.values())


def build_subject_statistics(
    session: ObservationSession, duration_hint: str | float | Decimal | None = None
) -> list[dict]:
    duration = _session_duration(session, duration_hint)
    rows: dict[tuple[int, int], dict] = {}
    open_states: dict[tuple[int, int], Decimal | None] = {}
    for event in session.events.all():
        related_subjects = event.all_subjects_ordered or []
        if not related_subjects:
            continue
        for subject in related_subjects:
            key = (subject.id, event.behavior_id)
            item = rows.setdefault(
                key,
                {
                    'subject': subject.name,
                    'behavior': event.behavior.name,
                    'mode': event.behavior.mode,
                    'point_count': 0,
                    'segment_count': 0,
                    'duration_seconds': Decimal('0'),
                },
            )
            open_states.setdefault(key, None)
            if event.event_kind == ObservationEvent.KIND_POINT:
                item['point_count'] += 1
            elif event.event_kind == ObservationEvent.KIND_START:
                open_states[key] = event.timestamp_seconds
            elif event.event_kind == ObservationEvent.KIND_STOP:
                start_time = open_states.get(key)
                if start_time is not None and event.timestamp_seconds >= start_time:
                    item['segment_count'] += 1
                    item['duration_seconds'] += event.timestamp_seconds - start_time
                open_states[key] = None

    for key, start_time in open_states.items():
        if start_time is not None and duration >= start_time:
            item = rows[key]
            item['segment_count'] += 1
            item['duration_seconds'] += duration - start_time

    results = []
    for item in rows.values():
        item['duration_seconds'] = round(float(item['duration_seconds']), 3)
        results.append(item)
    results.sort(key=lambda row: (row['subject'], row['behavior']))
    return results


def build_transition_rows(session: ObservationSession) -> list[dict]:
    event_rows = [event for event in session.events.all().order_by('timestamp_seconds', 'pk')]
    counters: dict[tuple[str, str], int] = defaultdict(int)
    previous_name = None
    for event in event_rows:
        current_name = event.behavior.name
        if previous_name is not None:
            counters[(previous_name, current_name)] += 1
        previous_name = current_name
    rows = [
        {'from_behavior': source, 'to_behavior': target, 'count': count}
        for (source, target), count in sorted(
            counters.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]
    return rows


def build_audit_rows(session: ObservationSession) -> list[dict]:
    return [
        {
            'action': item.action,
            'action_label': item.get_action_display(),
            'target_type': item.target_type,
            'target_type_label': item.get_target_type_display(),
            'target_id': item.target_id,
            'actor': item.actor.username if item.actor else '',
            'summary': item.summary,
            'payload': item.payload,
            'created_at': item.created_at.isoformat(),
        }
        for item in session.audit_logs.all()
    ]


def build_interval_rows(session: ObservationSession) -> list[dict]:
    rows = []
    for behavior in session.project.behaviors.order_by('sort_order', 'name'):
        timestamps = [
            float(item.timestamp_seconds)
            for item in session.events.filter(behavior=behavior).order_by('timestamp_seconds', 'pk')
        ]
        if len(timestamps) < 2:
            rows.append(
                {
                    'name': behavior.name,
                    'category': behavior.category.name if behavior.category else '',
                    'mode': behavior.mode,
                    'interval_count': 0,
                    'mean_interval_seconds': None,
                    'min_interval_seconds': None,
                    'max_interval_seconds': None,
                }
            )
            continue
        intervals = [
            round(timestamps[i + 1] - timestamps[i], 3) for i in range(len(timestamps) - 1)
        ]
        rows.append(
            {
                'name': behavior.name,
                'category': behavior.category.name if behavior.category else '',
                'mode': behavior.mode,
                'interval_count': len(intervals),
                'mean_interval_seconds': round(sum(intervals) / len(intervals), 3),
                'min_interval_seconds': min(intervals),
                'max_interval_seconds': max(intervals),
            }
        )
    return rows


def build_integrity_report(session: ObservationSession) -> dict:
    issues = []
    open_states: dict[int, Decimal | None] = {}
    for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE):
        open_states[behavior.id] = None

    for event in session.events.select_related('behavior').order_by('timestamp_seconds', 'pk'):
        if event.behavior.mode != Behavior.MODE_STATE:
            continue
        start_time = open_states[event.behavior_id]
        if event.event_kind == ObservationEvent.KIND_START:
            if start_time is not None:
                issues.append(
                    {
                        'severity': 'warning',
                        'message': f'Duplicate START for {event.behavior.name} at {event.timestamp_seconds}s.',
                    }
                )
            open_states[event.behavior_id] = event.timestamp_seconds
        elif event.event_kind == ObservationEvent.KIND_STOP:
            if start_time is None:
                issues.append(
                    {
                        'severity': 'warning',
                        'message': f'STOP without START for {event.behavior.name} at {event.timestamp_seconds}s.',
                    }
                )
            else:
                open_states[event.behavior_id] = None

    for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE):
        if open_states[behavior.id] is not None:
            issues.append(
                {
                    'severity': 'warning',
                    'message': f'Open state without STOP for {behavior.name}.',
                }
            )

    return {'issue_count': len(issues), 'issues': issues}


def build_project_statistics(project: Project) -> dict:
    sessions = list(
        project.sessions.select_related('observer', 'video').prefetch_related(
            Prefetch(
                'events',
                queryset=ObservationEvent.objects.select_related('behavior', 'behavior__category')
                .prefetch_related('modifiers')
                .order_by('timestamp_seconds', 'pk'),
            ),
            'annotations',
        )
    )
    aggregate: dict[int, dict] = {}
    session_rows = []
    total_events = 0
    total_annotations = 0
    total_span = 0.0

    for behavior in project.behaviors.select_related('category').order_by('sort_order', 'name'):
        aggregate[behavior.id] = {
            'name': behavior.name,
            'category': behavior.category.name if behavior.category else '',
            'mode': behavior.mode,
            'color': behavior.color,
            'session_count': 0,
            'point_count': 0,
            'start_count': 0,
            'stop_count': 0,
            'segment_count': 0,
            'duration_seconds': 0.0,
        }

    for session in sessions:
        stats = build_statistics(session)
        total_events += stats['session_event_count']
        total_annotations += stats['annotation_count']
        total_span += stats['observed_span_seconds']
        session_rows.append(
            {
                'session_id': session.id,
                'title': session.title,
                'observer': session.observer.username if session.observer else '',
                'video': session.primary_label,
                'synced_video_count': session.video_links.count(),
                'event_count': stats['session_event_count'],
                'annotation_count': stats['annotation_count'],
                'point_event_count': stats['point_event_count'],
                'open_state_count': stats['open_state_count'],
                'observed_span_seconds': stats['observed_span_seconds'],
                'state_duration_seconds': stats['state_duration_seconds'],
            }
        )
        for row in stats['rows']:
            item = aggregate[row['behavior_id']]
            if (
                row['point_count']
                or row['segment_count']
                or row['start_count']
                or row['stop_count']
            ):
                item['session_count'] += 1
            item['point_count'] += row['point_count']
            item['start_count'] += row['start_count']
            item['stop_count'] += row['stop_count']
            item['segment_count'] += row['segment_count']
            item['duration_seconds'] += row['total_duration_seconds']

    behavior_rows = []
    for item in aggregate.values():
        item['duration_seconds'] = round(item['duration_seconds'], 3)
        behavior_rows.append(item)

    behavior_rows.sort(key=lambda row: (row['category'], row['name']))
    session_rows.sort(key=lambda row: row['title'])
    subject_rows = []
    transition_rows = []
    for session in sessions:
        subject_rows.extend(build_subject_statistics(session))
        transition_rows.extend(build_transition_rows(session))

    return {
        'project_name': project.name,
        'session_count': len(sessions),
        'video_count': project.videos.count(),
        'behavior_count': project.behaviors.count(),
        'annotation_count': total_annotations,
        'event_count': total_events,
        'observed_span_seconds': round(total_span, 3),
        'session_rows': session_rows,
        'behavior_rows': behavior_rows,
        'subject_rows': subject_rows,
        'transition_rows': transition_rows,
    }




def build_keyboard_profile_payload(project: Project) -> dict[str, dict[str, str]]:
    """Snapshot the current project shortcut assignments into serializable mappings."""
    return {
        'behavior_bindings': {
            str(item.pk): item.key_binding.upper()
            for item in project.behaviors.order_by('sort_order', 'name')
            if item.key_binding
        },
        'modifier_bindings': {
            str(item.pk): item.key_binding.upper()
            for item in project.modifiers.order_by('sort_order', 'name')
            if item.key_binding
        },
        'subject_bindings': {
            str(item.pk): item.key_binding.upper()
            for item in project.subjects.order_by('sort_order', 'name')
            if item.key_binding
        },
    }


def _bucket_signature(session: ObservationSession, bucket_seconds: int = 1) -> list[str]:
    """Create a canonical state/point signature timeline for agreement analysis."""
    duration = int(max(1, float(_session_duration(session))))
    signatures: list[str] = []
    active_states: set[str] = set()
    events = list(session.events.select_related('behavior').order_by('timestamp_seconds', 'pk'))
    index = 0
    for bucket in range(duration + 1):
        bucket_start = Decimal(str(bucket * bucket_seconds))
        bucket_end = Decimal(str((bucket + 1) * bucket_seconds))
        point_labels: list[str] = []
        while index < len(events) and events[index].timestamp_seconds < bucket_end:
            event = events[index]
            label = event.behavior.name
            if event.behavior.mode == Behavior.MODE_STATE:
                if event.event_kind == ObservationEvent.KIND_START:
                    active_states.add(label)
                elif event.event_kind == ObservationEvent.KIND_STOP and label in active_states:
                    active_states.remove(label)
            else:
                if event.timestamp_seconds >= bucket_start:
                    point_labels.append(label)
            index += 1
        current = sorted(active_states)
        point_current = sorted(point_labels)
        signature_parts = current + [f'POINT:{label}' for label in point_current]
        signatures.append(' | '.join(signature_parts) if signature_parts else '∅')
    return signatures


def build_agreement_analysis(
    reference_session: ObservationSession,
    comparison_session: ObservationSession,
    bucket_seconds: int = 1,
) -> dict:
    """Compute a simple pairwise agreement summary and confusion counts."""
    reference = _bucket_signature(reference_session, bucket_seconds=bucket_seconds)
    comparison = _bucket_signature(comparison_session, bucket_seconds=bucket_seconds)
    bucket_count = min(len(reference), len(comparison))
    if bucket_count == 0:
        return {
            'bucket_seconds': bucket_seconds,
            'bucket_count': 0,
            'percent_agreement': 0.0,
            'cohen_kappa': None,
            'confusion_rows': [],
        }
    reference = reference[:bucket_count]
    comparison = comparison[:bucket_count]
    labels = sorted(set(reference) | set(comparison))
    matches = sum(1 for left, right in zip(reference, comparison, strict=False) if left == right)
    p0 = matches / bucket_count
    ref_counts = {label: reference.count(label) for label in labels}
    cmp_counts = {label: comparison.count(label) for label in labels}
    pe = sum((ref_counts[label] / bucket_count) * (cmp_counts[label] / bucket_count) for label in labels)
    kappa = None
    if pe < 1:
        kappa = round((p0 - pe) / (1 - pe), 4)
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    for left, right in zip(reference, comparison, strict=False):
        confusion[(left, right)] += 1
    confusion_rows = [
        {'reference_label': left, 'comparison_label': right, 'count': count}
        for (left, right), count in sorted(
            confusion.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]
    return {
        'bucket_seconds': bucket_seconds,
        'bucket_count': bucket_count,
        'percent_agreement': round(p0 * 100, 2),
        'cohen_kappa': kappa,
        'confusion_rows': confusion_rows,
    }


def build_project_boris_payload(project: Project) -> dict:
    """Build a richer BORIS-compatible project payload for exchange."""
    sessions = [
        build_boris_like_payload(session)
        for session in project.sessions.select_related('observer', 'video').prefetch_related(
            'events__behavior',
            'events__subjects',
            'events__modifiers',
            'annotations',
        )
    ]
    payload = build_ethogram_payload(project)
    payload.update(
        {
            'schema': 'boris-project-v1',
            'subjects': [
                {
                    'name': subject.name,
                    'description': subject.description,
                    'groups': [group.name for group in subject.groups.order_by('sort_order', 'name')],
                    'key_binding': subject.key_binding,
                    'color': subject.color,
                }
                for subject in project.subjects.prefetch_related('groups').order_by('sort_order', 'name')
            ],
            'subject_groups': [
                {
                    'name': group.name,
                    'description': group.description,
                    'color': group.color,
                }
                for group in project.subject_groups.order_by('sort_order', 'name')
            ],
            'variables': [
                {
                    'label': definition.label,
                    'description': definition.description,
                    'value_type': definition.value_type,
                    'set_values': definition.value_options,
                    'default_value': definition.default_value,
                }
                for definition in project.variable_definitions.order_by('sort_order', 'label')
            ],
            'observation_templates': [
                {
                    'name': template.name,
                    'description': template.description,
                    'default_session_kind': template.default_session_kind,
                    'behaviors': list(template.behaviors.order_by('sort_order', 'name').values_list('name', flat=True)),
                    'modifiers': list(template.modifiers.order_by('sort_order', 'name').values_list('name', flat=True)),
                    'subjects': list(template.subjects.order_by('sort_order', 'name').values_list('name', flat=True)),
                    'variable_definitions': list(template.variable_definitions.order_by('sort_order', 'label').values_list('label', flat=True)),
                }
                for template in project.observation_templates.prefetch_related(
                    'behaviors', 'modifiers', 'subjects', 'variable_definitions'
                ).order_by('name')
            ],
            'sessions': sessions,
        }
    )
    return payload


def build_reproducibility_bundle(project: Project) -> dict[str, bytes]:
    """Assemble a reproducible export bundle with checksums and rich metadata."""
    analytics = build_project_statistics(project)
    boris_payload = build_project_boris_payload(project)
    ethogram_payload = build_ethogram_payload(project)
    files: dict[str, bytes] = {
        'ethogram.json': json.dumps(ethogram_payload, indent=2, ensure_ascii=False).encode('utf-8'),
        'analytics.json': json.dumps(analytics, indent=2, ensure_ascii=False).encode('utf-8'),
        'boris_project.json': json.dumps(boris_payload, indent=2, ensure_ascii=False).encode('utf-8'),
    }
    session_meta = []
    for session in project.sessions.order_by('title'):
        filename = f'sessions/{slugify(session.title) or session.pk}.json'
        payload = build_boris_like_payload(get_accessible_session(project.owner, session.pk))
        files[filename] = json.dumps(payload, indent=2, ensure_ascii=False).encode('utf-8')
        session_meta.append({'id': session.pk, 'title': session.title, 'filename': filename})

    manifest = {
        'schema': 'pybehaviorlog-0.8.5-bundle',
        'version': '0.8.5',
        'project': {
            'name': project.name,
            'description': project.description,
            'owner': project.owner.username,
        },
        'exported_at': timezone.now().isoformat(),
        'sessions': session_meta,
        'checksums': {
            name: hashlib.sha256(content).hexdigest() for name, content in files.items()
        },
    }
    files['manifest.json'] = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
    return files





def _normalize_named_item(item, default_name: str | None = None, label_mode: bool = False) -> dict:
    """Return a normalized mapping for list/dict BORIS-like import items."""
    if isinstance(item, str):
        key = 'label' if label_mode else 'name'
        return {key: item}
    if not isinstance(item, dict):
        key = 'label' if label_mode else 'name'
        return {key: default_name or str(item)}
    normalized = dict(item)
    if label_mode:
        normalized.setdefault('label', normalized.get('name') or normalized.get('code') or default_name or '')
        normalized.setdefault('name', normalized['label'])
    else:
        normalized.setdefault('name', normalized.get('label') or normalized.get('code') or default_name or '')
        normalized.setdefault('label', normalized.get('name', ''))
    return normalized


def _coerce_named_items(value, *, label_mode: bool = False) -> list[dict]:
    """Accept either a list or a mapping keyed by names and normalize it to dict items."""
    items: list[dict] = []
    if isinstance(value, dict):
        for key, item in value.items():
            items.append(_normalize_named_item(item, default_name=str(key), label_mode=label_mode))
        return items
    if isinstance(value, list):
        for item in value:
            items.append(_normalize_named_item(item, label_mode=label_mode))
    return items


def _coerce_name_list(value) -> list[str]:
    """Convert list/dict/string inputs into a flat list of names for imports."""
    if value is None:
        return []
    if isinstance(value, dict):
        if all(isinstance(item, dict) for item in value.values()):
            results = []
            for key, item in value.items():
                normalized = _normalize_named_item(item, default_name=str(key))
                results.append(normalized.get('name') or normalized.get('label') or str(key))
            return [item for item in results if item]
        return [str(key) for key, item in value.items() if item]
    if isinstance(value, list):
        results = []
        for item in value:
            if isinstance(item, dict):
                normalized = _normalize_named_item(item)
                results.append(normalized.get('name') or normalized.get('label') or '')
            else:
                results.append(str(item))
        return [item for item in results if item]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r'[|,;]', value) if part.strip()]
    return [str(value)]


def _extract_observation_entries(payload: dict) -> list[dict]:
    """Extract project session/observation payloads from multiple BORIS-like shapes."""
    candidates = payload.get('sessions')
    if candidates is None:
        candidates = payload.get('observations')
    if candidates is None:
        candidates = payload.get('observation')
    if candidates is None:
        return []
    if isinstance(candidates, dict):
        rows = []
        for key, item in candidates.items():
            normalized = dict(item) if isinstance(item, dict) else {'title': str(key)}
            normalized.setdefault('title', normalized.get('description') or str(key))
            rows.append(normalized)
        return rows
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def _resolve_behavior_name(item: dict) -> str:
    return (
        item.get('behavior')
        or item.get('code')
        or item.get('behavior_code')
        or item.get('event')
        or ''
    )


def _resolve_event_kind_token(value: str | None) -> str | None:
    token = (value or '').strip().lower().replace('_', ' ')
    mapping = {
        'point': ObservationEvent.KIND_POINT,
        'instant': ObservationEvent.KIND_POINT,
        'start': ObservationEvent.KIND_START,
        'state start': ObservationEvent.KIND_START,
        'begin': ObservationEvent.KIND_START,
        'stop': ObservationEvent.KIND_STOP,
        'state stop': ObservationEvent.KIND_STOP,
        'end': ObservationEvent.KIND_STOP,
    }
    return mapping.get(token)


def _extract_media_labels(item: dict) -> list[str]:
    labels = []
    for key in ('synced_videos', 'media_files', 'media', 'media_paths'):
        labels.extend(_coerce_name_list(item.get(key)))
    primary = item.get('primary_video') or item.get('media_file') or item.get('media_path')
    if primary:
        labels.insert(0, str(primary))
    seen = set()
    results = []
    for label in labels:
        if label and label not in seen:
            seen.add(label)
            results.append(label)
    return results



def load_project_import_payload(uploaded_file) -> tuple[dict, dict[str, dict]]:
    """Load a JSON project payload from either a JSON file or a ZIP bundle."""
    raw_bytes = uploaded_file.read()
    buffer = io.BytesIO(raw_bytes)
    bundled_sessions: dict[str, dict] = {}
    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as archive:
            names = archive.namelist()
            candidate = 'boris_project.json' if 'boris_project.json' in names else None
            if candidate is None:
                candidate = next(
                    (
                        name
                        for name in names
                        if name.endswith('.json') and ('project' in name or 'bundle' in name)
                    ),
                    None,
                )
            if candidate is None:
                raise ValueError(_('The uploaded archive does not contain a project JSON file.'))
            payload = json.loads(archive.read(candidate).decode('utf-8'))
            for name in names:
                if name.startswith('sessions/') and name.endswith('.json'):
                    bundled_sessions[name] = json.loads(archive.read(name).decode('utf-8'))
            return payload, bundled_sessions
    try:
        return json.loads(raw_bytes.decode('utf-8')), bundled_sessions
    except UnicodeDecodeError as exc:
        raise ValueError(_('The uploaded file is not valid UTF-8 JSON.')) from exc


@transaction.atomic
def import_project_payload(
    project: Project,
    payload: dict,
    actor,
    import_sessions: bool = True,
    create_live_sessions: bool = True,
    bundled_sessions: dict[str, dict] | None = None,
) -> dict[str, int]:
    """Import a richer BORIS-like project payload into an existing project."""
    bundled_sessions = bundled_sessions or {}
    schema = payload.get('schema')
    if schema not in {
        'boris-project-v1',
        'boris-project-v2',
        'pybehaviorlog-0.8.3-bundle',
        'pybehaviorlog-0.8.5-bundle',
    }:
        raise ValueError(_('Unsupported project payload format.'))

    ethogram_payload = payload.get('ethogram') or payload
    categories_created, modifiers_created, behaviors_created = import_ethogram_payload(
        project,
        {
            **ethogram_payload,
            'schema': ethogram_payload.get('schema', 'pybehaviorlog-0.8.5-ethogram'),
        },
        replace_existing=False,
    )

    subject_group_map = {group.name: group for group in project.subject_groups.all()}
    subject_map = {subject.name: subject for subject in project.subjects.all()}
    variable_map = {item.label: item for item in project.variable_definitions.all()}
    behavior_map = {item.name: item for item in project.behaviors.all()}
    modifier_map = {item.name: item for item in project.modifiers.all()}

    subject_group_count = 0
    subject_count = 0
    variable_count = 0
    template_count = 0
    session_count = 0
    imported_event_count = 0
    imported_annotation_count = 0

    for item in _coerce_named_items(payload.get('subject_groups') or payload.get('groups')):
        group, created = SubjectGroup.objects.update_or_create(
            project=project,
            name=item.get('name') or item.get('code'),
            defaults={
                'description': item.get('description', ''),
                'color': item.get('color', '#7c3aed'),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        subject_group_map[group.name] = group
        subject_group_count += int(created)

    for item in _coerce_named_items(payload.get('subjects')):
        subject, created = Subject.objects.update_or_create(
            project=project,
            name=item.get('name') or item.get('code'),
            defaults={
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or '')[:1],
                'color': item.get('color', '#9333ea'),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        subject.groups.set(
            [
                subject_group_map[name]
                for name in item.get('groups', [])
                if name in subject_group_map
            ]
        )
        subject_map[subject.name] = subject
        subject_count += int(created)

    for item in _coerce_named_items(payload.get('variables') or payload.get('independent_variables'), label_mode=True):
        definition, created = IndependentVariableDefinition.objects.update_or_create(
            project=project,
            label=item.get('label') or item.get('name') or item.get('code'),
            defaults={
                'description': item.get('description', ''),
                'value_type': item.get(
                    'value_type', IndependentVariableDefinition.TYPE_TEXT
                ),
                'set_values': (
                    ', '.join(item.get('set_values', []))
                    if isinstance(item.get('set_values'), list)
                    else item.get('set_values', '')
                ),
                'default_value': str(item.get('default_value', '')),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        variable_map[definition.label] = definition
        variable_count += int(created)

    for item in _coerce_named_items(payload.get('observation_templates') or payload.get('templates')):
        template, created = ObservationTemplate.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'description': item.get('description', ''),
                'default_session_kind': item.get(
                    'default_session_kind', ObservationSession.KIND_MEDIA
                ),
            },
        )
        template.behaviors.set(
            [
                behavior_map[name]
                for name in _coerce_name_list(item.get('behaviors') or item.get('codes'))
                if name in behavior_map
            ]
        )
        template.modifiers.set(
            [
                modifier_map[name]
                for name in _coerce_name_list(item.get('modifiers'))
                if name in modifier_map
            ]
        )
        template.subjects.set(
            [subject_map[name] for name in _coerce_name_list(item.get('subjects')) if name in subject_map]
        )
        template.variable_definitions.set(
            [
                variable_map[name]
                for name in _coerce_name_list(item.get('variable_definitions') or item.get('variables'))
                if name in variable_map
            ]
        )
        template_count += int(created)

    if import_sessions:
        session_entries = _extract_observation_entries(payload)
        if not session_entries and bundled_sessions:
            session_entries = list(bundled_sessions.values())
        for index, session_payload in enumerate(session_entries, start=1):
            observation = (session_payload.get('observations') or [{}])[0]
            title = (
                observation.get('title')
                or observation.get('description')
                or session_payload.get('session')
                or session_payload.get('title')
                or _('Imported session %(index)s') % {'index': index}
            )
            synced_titles = _extract_media_labels(observation) or _extract_media_labels(session_payload)
            primary_label = synced_titles[0] if synced_titles else ''
            existing_video = (
                project.videos.filter(title=primary_label).first() if primary_label else None
            )
            if existing_video is None and not create_live_sessions and primary_label:
                continue
            session_kind = (
                ObservationSession.KIND_MEDIA
                if existing_video
                else ObservationSession.KIND_LIVE
            )
            notes_parts = [
                item
                for item in [
                    observation.get('note'),
                    session_payload.get('review_notes'),
                ]
                if item
            ]
            if synced_titles:
                notes_parts.append(
                    _('Imported media titles: %(titles)s')
                    % {'titles': ', '.join(dict.fromkeys(synced_titles))}
                )
            session, _created = ObservationSession.objects.update_or_create(
                project=project,
                title=title,
                defaults={
                    'observer': actor,
                    'video': existing_video,
                    'session_kind': session_kind,
                    'description': session_payload.get('description', ''),
                    'notes': '\n'.join(notes_parts).strip(),
                    'review_notes': session_payload.get('review_notes', ''),
                    'workflow_status': session_payload.get(
                        'workflow_status', ObservationSession.STATUS_DRAFT
                    ),
                },
            )
            matched_videos = list(project.videos.filter(title__in=synced_titles))
            if matched_videos:
                _sync_session_videos(session, matched_videos)
            event_count, annotation_count = import_session_payload(
                session, session_payload, clear_existing=True
            )
            _log_audit(
                session,
                actor=actor,
                action=ObservationAuditLog.ACTION_IMPORT,
                target_type=ObservationAuditLog.TARGET_IMPORT,
                target_id=session.id,
                summary=f'Imported project session {session.title}.',
                payload={
                    'source_schema': schema,
                    'event_count': event_count,
                    'annotation_count': annotation_count,
                },
            )
            session_count += 1
            imported_event_count += event_count
            imported_annotation_count += annotation_count

    return {
        'categories_created': categories_created,
        'modifiers_created': modifiers_created,
        'behaviors_created': behaviors_created,
        'subject_groups_created': subject_group_count,
        'subjects_created': subject_count,
        'variables_created': variable_count,
        'templates_created': template_count,
        'sessions_imported': session_count,
        'events_imported': imported_event_count,
        'annotations_imported': imported_annotation_count,
    }

def build_ethogram_payload(project: Project) -> dict:  # pragma: no cover
    return {
        'schema': 'pybehaviorlog-0.8.5-ethogram',
        'project': {
            'name': project.name,
            'description': project.description,
            'owner': project.owner.username,
        },
        'categories': [
            {
                'name': category.name,
                'color': category.color,
                'sort_order': category.sort_order,
            }
            for category in project.categories.order_by('sort_order', 'name')
        ],
        'modifiers': [
            {
                'name': modifier.name,
                'description': modifier.description,
                'key_binding': modifier.key_binding,
                'sort_order': modifier.sort_order,
            }
            for modifier in project.modifiers.order_by('sort_order', 'name')
        ],
        'subject_groups': [
            {
                'name': group.name,
                'description': group.description,
                'color': group.color,
                'sort_order': group.sort_order,
            }
            for group in project.subject_groups.order_by('sort_order', 'name')
        ],
        'subjects': [
            {
                'name': subject.name,
                'description': subject.description,
                'key_binding': subject.key_binding,
                'color': subject.color,
                'sort_order': subject.sort_order,
                'groups': [group.name for group in subject.groups.order_by('sort_order', 'name')],
            }
            for subject in project.subjects.order_by('sort_order', 'name')
        ],
        'variables': [
            {
                'label': definition.label,
                'description': definition.description,
                'value_type': definition.value_type,
                'set_values': definition.set_values,
                'default_value': definition.default_value,
                'sort_order': definition.sort_order,
            }
            for definition in project.variable_definitions.order_by('sort_order', 'label')
        ],
        'behaviors': [
            {
                'name': behavior.name,
                'description': behavior.description,
                'key_binding': behavior.key_binding,
                'color': behavior.color,
                'mode': behavior.mode,
                'sort_order': behavior.sort_order,
                'category': behavior.category.name if behavior.category else None,
            }
            for behavior in project.behaviors.select_related('category').order_by(
                'sort_order', 'name'
            )
        ],
    }


@transaction.atomic
def import_ethogram_payload(
    project: Project, payload: dict, replace_existing: bool = False
) -> tuple[int, int, int]:  # pragma: no cover
    if payload.get('schema') not in {
        'cowlog-django-v3-ethogram',
        'cowlog-django-v4-ethogram',
        'cowlog-django-v5-ethogram',
        'pybehaviorlog-0.8-ethogram',
        'pybehaviorlog-0.8.3-ethogram',
        'pybehaviorlog-0.8.5-ethogram',
    }:
        raise ValueError('Unsupported JSON schema.')

    if replace_existing and (
        project.sessions.exists()
        or ObservationEvent.objects.filter(session__project=project).exists()
    ):
        raise ValueError(
            'Full replacement is blocked because the project already contains sessions or events.'
        )

    if replace_existing:
        project.behaviors.all().delete()
        project.modifiers.all().delete()
        project.categories.all().delete()
        project.subjects.all().delete()
        project.subject_groups.all().delete()
        project.variable_definitions.all().delete()

    category_map: dict[str, BehaviorCategory] = {
        category.name: category for category in project.categories.all()
    }
    subject_group_map: dict[str, SubjectGroup] = {
        group.name: group for group in project.subject_groups.all()
    }
    modifier_count = 0
    behavior_count = 0
    category_count = 0

    for item in _coerce_named_items(payload.get('categories')):
        category, created = BehaviorCategory.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'color': item.get('color', '#0f766e'),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        category_map[category.name] = category
        if created:
            category_count += 1

    for item in _coerce_named_items(payload.get('subject_groups') or payload.get('groups')):
        group, created = SubjectGroup.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'description': item.get('description', ''),
                'color': item.get('color', '#7c3aed'),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        subject_group_map[group.name] = group

    for item in _coerce_named_items(payload.get('subjects')):
        subject, _ = Subject.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or '')[:1].upper(),
                'color': item.get('color', '#9333ea'),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        groups = [
            subject_group_map[name] for name in item.get('groups', []) if name in subject_group_map
        ]
        subject.groups.set(groups)

    for item in _coerce_named_items(payload.get('variables') or payload.get('independent_variables'), label_mode=True):
        IndependentVariableDefinition.objects.update_or_create(
            project=project,
            label=item.get('label') or item.get('name') or item.get('code'),
            defaults={
                'description': item.get('description', ''),
                'value_type': item.get('value_type', IndependentVariableDefinition.TYPE_TEXT),
                'set_values': (', '.join(item.get('set_values', [])) if isinstance(item.get('set_values'), list) else item.get('set_values', '')),
                'default_value': item.get('default_value', ''),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )

    for item in _coerce_named_items(payload.get('modifiers')):
        _, created = Modifier.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or item.get('key') or '')[0:1].upper(),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        if created:
            modifier_count += 1

    for item in _coerce_named_items(payload.get('behaviors')):
        category_name = item.get('category')
        if isinstance(category_name, dict):
            category_name = category_name.get('name')
        category = category_map.get(category_name) if category_name else None
        _, created = Behavior.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'category': category,
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or item.get('key') or '')[0:1].upper(),
                'color': item.get('color', '#2563eb'),
                'mode': item.get('mode', Behavior.MODE_POINT),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        if created:
            behavior_count += 1

    return category_count, modifier_count, behavior_count


def resolve_event_kind(
    session: ObservationSession, behavior: Behavior, explicit_kind: str | None
) -> str:
    if behavior.mode == Behavior.MODE_POINT:
        return ObservationEvent.KIND_POINT
    if explicit_kind in {ObservationEvent.KIND_START, ObservationEvent.KIND_STOP}:
        return explicit_kind
    is_open = False
    for event in session.events.filter(behavior=behavior).order_by('timestamp_seconds', 'pk'):
        if event.event_kind == ObservationEvent.KIND_START:
            is_open = True
        elif event.event_kind == ObservationEvent.KIND_STOP:
            is_open = False
    return ObservationEvent.KIND_STOP if is_open else ObservationEvent.KIND_START


def _sync_session_videos(session: ObservationSession, additional_videos):
    video_ids = []
    if session.video_id:
        video_ids.append(session.video_id)
    for video in additional_videos:
        if video.pk != session.video_id and video.pk not in video_ids:
            video_ids.append(video.pk)
    if not video_ids:
        SessionVideoLink.objects.filter(session=session).delete()
        return
    SessionVideoLink.objects.filter(session=session).exclude(video_id__in=video_ids).delete()
    for index, video_id in enumerate(video_ids):
        SessionVideoLink.objects.update_or_create(
            session=session,
            video_id=video_id,
            defaults={'sort_order': index},
        )


def _event_rows(session: ObservationSession):  # pragma: no cover
    linked_titles = ', '.join(video.title for video in session.all_videos_ordered)
    for event in session.events.all():
        yield [
            session.project.name,
            session.title,
            session.primary_label,
            linked_titles,
            session.observer.username if session.observer else '',
            event.behavior.category.name if event.behavior.category else '',
            event.behavior.name,
            event.behavior.mode,
            event.event_kind,
            str(event.timestamp_seconds),
            event.subjects_display,
            event.modifiers_display,
            event.comment,
            event.created_at.isoformat(),
        ]


def _annotation_rows(session: ObservationSession):  # pragma: no cover
    for annotation in session.annotations.all():
        yield [
            session.project.name,
            session.title,
            str(annotation.timestamp_seconds),
            annotation.title,
            annotation.note,
            annotation.color,
            annotation.created_by.username if annotation.created_by else '',
            annotation.created_at.isoformat(),
        ]


def _append_autosized_sheet(
    workbook: Workbook, title: str, headers: list[str], rows: list[list]
):  # pragma: no cover
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    return sheet


def _autosize_workbook(workbook: Workbook):  # pragma: no cover
    for sheet in workbook.worksheets:
        for column_cells in sheet.columns:
            max_len = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = '' if cell.value is None else str(cell.value)
                max_len = max(max_len, len(value))
            sheet.column_dimensions[column_letter].width = min(max_len + 2, 48)


def build_boris_like_payload(session: ObservationSession) -> dict:  # pragma: no cover
    return {
        'schema': 'boris-observation-v3',
        'project_name': session.project.name,
        'ethogram': build_ethogram_payload(session.project),
        'workflow_status': session.workflow_status,
        'review_notes': session.review_notes,
        'variables': {item.definition.label: item.value for item in session.variable_values.all()},
        'observations': [
            {
                'title': session.title,
                'primary_video': session.primary_label,
                'synced_videos': [video.title for video in session.all_videos_ordered],
                'observer': session.observer.username if session.observer else None,
                'events': [
                    {
                        'time': float(event.timestamp_seconds),
                        'behavior': event.behavior.name,
                        'event_kind': event.event_kind,
                        'modifiers': list(
                            event.modifiers.order_by('sort_order', 'name').values_list(
                                'name', flat=True
                            )
                        ),
                        'comment': event.comment,
                        'subjects': [subject.name for subject in event.all_subjects_ordered],
                    }
                    for event in session.events.all()
                ],
                'annotations': [serialize_annotation(item) for item in session.annotations.all()],
            }
        ],
    }


@transaction.atomic
def import_session_payload(
    session: ObservationSession, payload: dict, clear_existing: bool = False
) -> tuple[int, int]:
    if clear_existing:
        session.events.all().delete()
        session.annotations.all().delete()

    modifier_map = {item.name: item for item in session.project.modifiers.all()}
    behavior_map = {item.name: item for item in session.project.behaviors.all()}
    subject_map = {item.name: item for item in session.project.subjects.all()}
    variable_map = {item.label: item for item in session.project.variable_definitions.all()}

    event_items: list[dict] = []
    annotation_items: list[dict] = []
    variable_items = payload.get('variables', {}) or payload.get('independent_variables', {}) or {}

    if payload.get('schema') in {
        'cowlog-django-v5-session',
        'pybehaviorlog-v6-session',
        'pybehaviorlog-0.8-session',
        'pybehaviorlog-0.8.3-session',
        'pybehaviorlog-0.8.5-session',
    }:
        event_items = payload.get('events', [])
        annotation_items = payload.get('annotations', [])
    elif payload.get('schema') in {
        'boris-observation-v1',
        'boris-observation-v2',
        'boris-observation-v3',
    } or payload.get('observations') or payload.get('events'):
        observations = payload.get('observations', [])
        if isinstance(observations, dict):
            observations = list(observations.values())
        if observations:
            first = observations[0]
            event_items = first.get('events', [])
            annotation_items = first.get('annotations', [])
            if isinstance(first.get('variables'), dict):
                variable_items = first.get('variables')
        else:
            event_items = payload.get('events', [])
            annotation_items = payload.get('annotations', [])
    else:
        raise ValueError(_('Unsupported session payload format.'))

    event_count = 0
    annotation_count = 0
    for raw_item in event_items:
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        behavior_name = _resolve_behavior_name(item)
        behavior = behavior_map.get(behavior_name)
        if behavior is None:
            continue
        explicit_kind = _resolve_event_kind_token(item.get('event_kind') or item.get('type'))
        event = ObservationEvent.objects.create(
            session=session,
            behavior=behavior,
            event_kind=resolve_event_kind(session, behavior, explicit_kind),
            timestamp_seconds=_decimal(
                item.get('timestamp_seconds', item.get('time', item.get('timestamp'))), default='0'
            ),
            frame_index=item.get('frame_index') or item.get('frame') or None,
            comment=(item.get('comment') or item.get('note') or item.get('remarks') or '').strip(),
        )
        subject_names = _coerce_name_list(item.get('subjects'))
        if item.get('subject') and item.get('subject') not in subject_names:
            subject_names = [item.get('subject'), *subject_names]
        subjects = [subject_map[name] for name in subject_names if name in subject_map]
        if subjects:
            event.subject = subjects[0]
            event.save(update_fields=['subject'])
            event.subjects.set(subjects)
        modifier_names = _coerce_name_list(item.get('modifiers') or item.get('modifier'))
        modifiers = [modifier_map[name] for name in modifier_names if name in modifier_map]
        if modifiers:
            event.modifiers.set(modifiers)
        event_count += 1

    if not isinstance(variable_items, dict):
        variable_items = {item.get('label') or item.get('name'): item.get('value') for item in _coerce_named_items(variable_items, label_mode=True)}
    for label, value in variable_items.items():
        definition = variable_map.get(label)
        if definition is None:
            continue
        ObservationVariableValue.objects.update_or_create(
            session=session,
            definition=definition,
            defaults={'value': str(value)},
        )

    if payload.get('workflow_status') in {
        ObservationSession.STATUS_DRAFT,
        ObservationSession.STATUS_IN_REVIEW,
        ObservationSession.STATUS_VALIDATED,
        ObservationSession.STATUS_LOCKED,
    }:
        session.workflow_status = payload['workflow_status']
        session.review_notes = payload.get('review_notes', session.review_notes or '')
        session.save(update_fields=['workflow_status', 'review_notes'])

    for raw_item in annotation_items:
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        SessionAnnotation.objects.create(
            session=session,
            timestamp_seconds=_decimal(
                item.get('timestamp_seconds', item.get('time', item.get('timestamp'))), default='0'
            ),
            title=(item.get('title') or 'Note').strip()[:120] or 'Note',
            note=(item.get('note') or item.get('comment') or '').strip(),
            color=item.get('color', '#f59e0b'),
            created_by=session.observer,
        )
        annotation_count += 1
    return event_count, annotation_count



@login_required
def home(request):  # pragma: no cover
    projects = list(
        accessible_projects_qs(request.user).prefetch_related(
            'categories',
            'modifiers',
            'behaviors',
            'videos',
            'sessions__video',
            'sessions__video_links',
            'memberships__user',
        )
    )
    for project in projects:
        project.current_role = project.role_for_user(request.user)
    return render(request, 'tracker/home.html', {'projects': projects})


@login_required
def project_create(request):  # pragma: no cover
    form = ProjectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = form.save(commit=False)
        project.owner = request.user
        project.save()
        ProjectMembership.objects.update_or_create(
            project=project,
            user=request.user,
            defaults={'role': ProjectMembership.ROLE_OWNER},
        )
        messages.success(request, _('Project created successfully.'))
        return redirect(project)
    return render(request, 'tracker/project_form.html', {'form': form})


@login_required
def project_update(request, pk: int):  # pragma: no cover
    project = get_owned_project(request.user, pk)
    form = ProjectSettingsForm(request.POST or None, instance=project)
    membership_form = ProjectMembershipForm(project=project)
    keyboard_form = KeyboardProfileForm()
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Project settings updated.'))
        return redirect(project)
    memberships = project.memberships.select_related('user').order_by('role', 'user__username')
    return render(
        request,
        'tracker/project_settings.html',
        {
            'form': form,
            'project': project,
            'membership_form': membership_form,
            'memberships': memberships,
            'keyboard_form': keyboard_form,
            'keyboard_profiles': project.keyboard_profiles.order_by('name'),
        },
    )


@login_required
def project_detail(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    project = (
        accessible_projects_qs(request.user)
        .prefetch_related(
            'categories',
            'modifiers',
            'behaviors__category',
            'videos',
            'sessions__video',
            'sessions__video_links',
            'subjects__groups',
            'subject_groups',
            'variable_definitions',
            'observation_templates',
            'memberships__user',
            'keyboard_profiles',
        )
        .get(pk=project.pk)
    )
    analytics = build_project_statistics(project)
    return render(
        request,
        'tracker/project_detail.html',
        {
            'project': project,
            'is_owner': project.owner_id == request.user.id,
            'current_role': project_role(request.user, project),
            'can_edit_project': project.can_edit(request.user),
            'can_review_project': project.can_review(request.user),
            'can_manage_members': project.can_manage_members(request.user),
            'analytics': analytics,
            'memberships': project.memberships.select_related('user').order_by('role', 'user__username'),
            'keyboard_profiles': project.keyboard_profiles.order_by('name'),
        },
    )


@login_required
def project_analytics(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    analytics = build_project_statistics(project)
    agreement = None
    comparison_session_id = request.GET.get('comparison_session')
    reference_session_id = request.GET.get('reference_session')
    if reference_session_id and comparison_session_id:
        reference_session = get_accessible_session(request.user, int(reference_session_id))
        comparison_session = get_accessible_session(request.user, int(comparison_session_id))
        if reference_session.project_id == project.pk and comparison_session.project_id == project.pk:
            agreement = build_agreement_analysis(reference_session, comparison_session)
    return render(
        request,
        'tracker/project_analytics.html',
        {
            'project': project,
            'analytics': analytics,
            'agreement': agreement,
            'session_options': project.sessions.order_by('title'),
            'reference_session_id': reference_session_id,
            'comparison_session_id': comparison_session_id,
        },
    )


@login_required
def project_export_xlsx(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    analytics = build_project_statistics(project)
    workbook = Workbook()
    overview = workbook.active
    overview.title = 'Overview'
    overview.append(['Project', project.name])
    overview.append(['Sessions', analytics['session_count']])
    overview.append(['Videos', analytics['video_count']])
    overview.append(['Behaviors', analytics['behavior_count']])
    overview.append(['Annotations', analytics['annotation_count']])
    overview.append(['Events', analytics['event_count']])
    overview.append(['Observed span seconds', analytics['observed_span_seconds']])

    _append_autosized_sheet(
        workbook,
        'Sessions',
        [
            'Session',
            'Observer',
            'Primary video',
            'Synced videos',
            'Event count',
            'Annotations',
            'Point count',
            'Open states',
            'Observed span seconds',
            'State duration seconds',
        ],
        [
            [
                row['title'],
                row['observer'],
                row['video'],
                row['synced_video_count'],
                row['event_count'],
                row['annotation_count'],
                row['point_event_count'],
                row['open_state_count'],
                row['observed_span_seconds'],
                row['state_duration_seconds'],
            ]
            for row in analytics['session_rows']
        ],
    )
    _append_autosized_sheet(
        workbook,
        'Behaviors',
        [
            'Category',
            'Behavior',
            'Mode',
            'Sessions used',
            'Point count',
            'Start count',
            'Stop count',
            'Segments',
            'Duration seconds',
        ],
        [
            [
                row['category'],
                row['name'],
                row['mode'],
                row['session_count'],
                row['point_count'],
                row['start_count'],
                row['stop_count'],
                row['segment_count'],
                row['duration_seconds'],
            ]
            for row in analytics['behavior_rows']
        ],
    )
    _append_autosized_sheet(
        workbook,
        'Subjects',
        ['Subject', 'Behavior', 'Mode', 'Point count', 'Segment count', 'Duration seconds'],
        [
            [
                row['subject'],
                row['behavior'],
                row['mode'],
                row['point_count'],
                row['segment_count'],
                row['duration_seconds'],
            ]
            for row in analytics['subject_rows']
        ],
    )
    _append_autosized_sheet(
        workbook,
        'Transitions',
        ['From behavior', 'To behavior', 'Count'],
        [
            [row['from_behavior'], row['to_behavior'], row['count']]
            for row in analytics['transition_rows']
        ],
    )
    reference_session_id = request.GET.get('reference_session')
    comparison_session_id = request.GET.get('comparison_session')
    if reference_session_id and comparison_session_id:
        reference_session = get_accessible_session(request.user, int(reference_session_id))
        comparison_session = get_accessible_session(request.user, int(comparison_session_id))
        if reference_session.project_id == project.pk and comparison_session.project_id == project.pk:
            agreement = build_agreement_analysis(reference_session, comparison_session)
            agreement_sheet = workbook.create_sheet('Agreement')
            agreement_sheet.append(['Reference session', reference_session.title])
            agreement_sheet.append(['Comparison session', comparison_session.title])
            agreement_sheet.append(['Bucket seconds', agreement['bucket_seconds']])
            agreement_sheet.append(['Bucket count', agreement['bucket_count']])
            agreement_sheet.append(['Percent agreement', agreement['percent_agreement']])
            agreement_sheet.append(['Cohen kappa', agreement['cohen_kappa']])
            agreement_sheet.append([])
            agreement_sheet.append(['Reference label', 'Comparison label', 'Count'])
            for row in agreement['confusion_rows']:
                agreement_sheet.append([row['reference_label'], row['comparison_label'], row['count']])

    _autosize_workbook(workbook)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = (
        f'attachment; filename="{slugify(project.name) or "project"}_analytics.xlsx"'
    )
    workbook.save(response)
    return response


@login_required
def project_export_bundle(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    bundle_files = build_reproducibility_bundle(project)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in bundle_files.items():
            archive.writestr(name, content)
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = (
        f'attachment; filename="{slugify(project.name) or "project"}_bundle.zip"'
    )
    return response


@login_required
def project_export_boris_json(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    payload = build_project_boris_payload(project)
    filename = f'{slugify(project.name) or "project"}_boris_project.json'
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def project_export_ethogram(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    payload = build_ethogram_payload(project)
    filename = f'{slugify(project.name) or "project"}_ethogram.json'
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def project_import_ethogram(request, pk: int):  # pragma: no cover
    project = get_owned_project(request.user, pk)
    form = EthogramImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['file']
        replace_existing = form.cleaned_data['replace_existing']
        try:
            payload = json.loads(uploaded.read().decode('utf-8'))
            category_count, modifier_count, behavior_count = import_ethogram_payload(
                project, payload, replace_existing=replace_existing
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            messages.error(request, _('The uploaded file is not valid JSON.'))
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _('Import complete. New categories: %(categories)s, modifiers: %(modifiers)s, behaviors: %(behaviors)s.') % {'categories': category_count, 'modifiers': modifier_count, 'behaviors': behavior_count},
            )
            return redirect(project)
    return render(request, 'tracker/ethogram_import.html', {'form': form, 'project': project})




@login_required
def project_import_boris_json(request, pk: int):  # pragma: no cover
    project = get_owned_project(request.user, pk)
    form = ProjectBORISImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['file']
        import_sessions = form.cleaned_data['import_sessions']
        create_live_sessions = form.cleaned_data['create_live_sessions']
        try:
            payload, bundled_sessions = load_project_import_payload(uploaded)
            summary = import_project_payload(
                project,
                payload,
                actor=request.user,
                import_sessions=import_sessions,
                create_live_sessions=create_live_sessions,
                bundled_sessions=bundled_sessions,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _(
                    'Project import complete. Categories: %(categories)s, modifiers: %(modifiers)s, behaviors: %(behaviors)s, subject groups: %(subject_groups)s, subjects: %(subjects)s, variables: %(variables)s, templates: %(templates)s, sessions: %(sessions)s.'
                )
                % {
                    'categories': summary['categories_created'],
                    'modifiers': summary['modifiers_created'],
                    'behaviors': summary['behaviors_created'],
                    'subject_groups': summary['subject_groups_created'],
                    'subjects': summary['subjects_created'],
                    'variables': summary['variables_created'],
                    'templates': summary['templates_created'],
                    'sessions': summary['sessions_imported'],
                },
            )
            return redirect(project)
    return render(
        request,
        'tracker/project_boris_import.html',
        {'form': form, 'project': project},
    )


@login_required
def project_membership_create(request, pk: int):  # pragma: no cover
    project = get_owned_project(request.user, pk)
    form = ProjectMembershipForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        membership = form.save(commit=False)
        membership.project = project
        membership.save()
        messages.success(request, _('Project membership added.'))
        return redirect('tracker:project_update', pk=project.pk)
    return render(
        request,
        'tracker/project_membership_form.html',
        {'form': form, 'project': project, 'mode': 'create'},
    )


@login_required
def project_membership_update(request, pk: int):  # pragma: no cover
    membership = get_object_or_404(ProjectMembership.objects.select_related('project', 'user'), pk=pk)
    _require_project_owner(request.user, membership.project)
    form = ProjectMembershipForm(request.POST or None, instance=membership, project=membership.project)
    form.fields['user'].disabled = True
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Project membership updated.'))
        return redirect('tracker:project_update', pk=membership.project.pk)
    return render(
        request,
        'tracker/project_membership_form.html',
        {'form': form, 'project': membership.project, 'membership': membership, 'mode': 'update'},
    )


@login_required
def project_membership_delete(request, pk: int):  # pragma: no cover
    membership = get_object_or_404(ProjectMembership.objects.select_related('project', 'user'), pk=pk)
    _require_project_owner(request.user, membership.project)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = membership.project
        membership.delete()
        messages.success(request, _('Project membership deleted.'))
        return redirect('tracker:project_update', pk=project.pk)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the membership for “{membership.user.username}”',
            'project': membership.project,
        },
    )


@login_required
def keyboard_profile_create(request, pk: int):  # pragma: no cover
    project = get_owned_project(request.user, pk)
    form = KeyboardProfileForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        profile = form.save(commit=False)
        profile.project = project
        snapshot = build_keyboard_profile_payload(project)
        profile.behavior_bindings = snapshot['behavior_bindings']
        profile.modifier_bindings = snapshot['modifier_bindings']
        profile.subject_bindings = snapshot['subject_bindings']
        profile.save()
        messages.success(request, _('Keyboard profile created from the current project bindings.'))
        return redirect('tracker:project_update', pk=project.pk)
    return render(
        request,
        'tracker/keyboard_profile_form.html',
        {'form': form, 'project': project, 'mode': 'create'},
    )


@login_required
def keyboard_profile_update(request, pk: int):  # pragma: no cover
    profile = get_object_or_404(KeyboardProfile.objects.select_related('project'), pk=pk)
    _require_project_owner(request.user, profile.project)
    form = KeyboardProfileForm(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        profile = form.save(commit=False)
        snapshot = build_keyboard_profile_payload(profile.project)
        profile.behavior_bindings = snapshot['behavior_bindings']
        profile.modifier_bindings = snapshot['modifier_bindings']
        profile.subject_bindings = snapshot['subject_bindings']
        profile.save()
        messages.success(request, _('Keyboard profile refreshed from the current project bindings.'))
        return redirect('tracker:project_update', pk=profile.project.pk)
    return render(
        request,
        'tracker/keyboard_profile_form.html',
        {'form': form, 'project': profile.project, 'profile': profile, 'mode': 'update'},
    )


@login_required
def keyboard_profile_delete(request, pk: int):  # pragma: no cover
    profile = get_object_or_404(KeyboardProfile.objects.select_related('project'), pk=pk)
    _require_project_owner(request.user, profile.project)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = profile.project
        profile.delete()
        messages.success(request, _('Keyboard profile deleted.'))
        return redirect('tracker:project_update', pk=project.pk)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the keyboard profile “{profile.name}”',
            'project': profile.project,
        },
    )


@login_required
def category_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = BehaviorCategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save(commit=False)
        category.project = project
        category.save()
        messages.success(request, _('Category created.'))
        return redirect(project)
    return render(
        request, 'tracker/category_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def category_update(request, pk: int):  # pragma: no cover
    category = _get_owned_category(request.user, pk)
    form = BehaviorCategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Category updated.'))
        return redirect(category.project)
    return render(
        request,
        'tracker/category_form.html',
        {'form': form, 'project': category.project, 'mode': 'update', 'object': category},
    )


@login_required
def category_delete(request, pk: int):  # pragma: no cover
    category = _get_owned_category(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = category.project
        category.delete()
        messages.success(request, _('Category deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the category “{category.name}”',
            'project': category.project,
        },
    )


@login_required
def modifier_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = ModifierForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        modifier = form.save(commit=False)
        modifier.project = project
        modifier.save()
        messages.success(request, _('Modifier created.'))
        return redirect(project)
    return render(
        request, 'tracker/modifier_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def modifier_update(request, pk: int):  # pragma: no cover
    modifier = _get_owned_modifier(request.user, pk)
    form = ModifierForm(request.POST or None, instance=modifier)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Modifier updated.'))
        return redirect(modifier.project)
    return render(
        request,
        'tracker/modifier_form.html',
        {'form': form, 'project': modifier.project, 'mode': 'update', 'object': modifier},
    )


@login_required
def modifier_delete(request, pk: int):  # pragma: no cover
    modifier = _get_owned_modifier(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = modifier.project
        modifier.delete()
        messages.success(request, _('Modifier deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the modifier “{modifier.name}”',
            'project': modifier.project,
        },
    )


@login_required
def subject_group_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = SubjectGroupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        group = form.save(commit=False)
        group.project = project
        group.save()
        messages.success(request, _('Subject group created.'))
        return redirect(project)
    return render(
        request,
        'tracker/subject_group_form.html',
        {'form': form, 'project': project, 'mode': 'create'},
    )


@login_required
def subject_group_update(request, pk: int):  # pragma: no cover
    group = get_object_or_404(SubjectGroup.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, group.project, _('You need editor permissions to edit subject groups.'))
    form = SubjectGroupForm(request.POST or None, instance=group)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Subject group updated.'))
        return redirect(group.project)
    return render(
        request,
        'tracker/subject_group_form.html',
        {'form': form, 'project': group.project, 'mode': 'update', 'object': group},
    )


@login_required
def subject_group_delete(request, pk: int):  # pragma: no cover
    group = get_object_or_404(SubjectGroup.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, group.project, _('You need editor permissions to delete subject groups.'))
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid() and form.cleaned_data['confirm']:
        project = group.project
        group.delete()
        messages.success(request, _('Subject group deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the subject group “{group.name}”',
            'project': group.project,
        },
    )


@login_required
def subject_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = SubjectForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        subject = form.save(commit=False)
        subject.project = project
        subject.save()
        form.save_m2m()
        messages.success(request, _('Subject created.'))
        return redirect(project)
    return render(
        request, 'tracker/subject_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def subject_update(request, pk: int):  # pragma: no cover
    subject = get_object_or_404(Subject.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, subject.project, _('You need editor permissions to edit subjects.'))
    form = SubjectForm(request.POST or None, instance=subject, project=subject.project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Subject updated.'))
        return redirect(subject.project)
    return render(
        request,
        'tracker/subject_form.html',
        {'form': form, 'project': subject.project, 'mode': 'update', 'object': subject},
    )


@login_required
def subject_delete(request, pk: int):  # pragma: no cover
    subject = get_object_or_404(Subject.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, subject.project, _('You need editor permissions to delete subjects.'))
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid() and form.cleaned_data['confirm']:
        project = subject.project
        subject.delete()
        messages.success(request, _('Subject deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {'form': form, 'object_label': f'the subject “{subject.name}”', 'project': subject.project},
    )


@login_required
def independent_variable_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = IndependentVariableDefinitionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.project = project
        item.save()
        messages.success(request, _('Independent variable created.'))
        return redirect(project)
    return render(
        request,
        'tracker/independent_variable_form.html',
        {'form': form, 'project': project, 'mode': 'create'},
    )


@login_required
def independent_variable_update(request, pk: int):  # pragma: no cover
    definition = get_object_or_404(
        IndependentVariableDefinition.objects.select_related('project'), pk=pk
    )
    _require_project_editor(request.user, definition.project, _('You need editor permissions to edit independent variables.'))
    form = IndependentVariableDefinitionForm(request.POST or None, instance=definition)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Independent variable updated.'))
        return redirect(definition.project)
    return render(
        request,
        'tracker/independent_variable_form.html',
        {'form': form, 'project': definition.project, 'mode': 'update', 'object': definition},
    )


@login_required
def independent_variable_delete(request, pk: int):  # pragma: no cover
    definition = get_object_or_404(
        IndependentVariableDefinition.objects.select_related('project'), pk=pk
    )
    _require_project_editor(request.user, definition.project, _('You need editor permissions to delete independent variables.'))
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid() and form.cleaned_data['confirm']:
        project = definition.project
        definition.delete()
        messages.success(request, _('Independent variable deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the independent variable “{definition.label}”',
            'project': definition.project,
        },
    )


@login_required
def observation_template_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = ObservationTemplateForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        template = form.save(commit=False)
        template.project = project
        template.save()
        form.save_m2m()
        messages.success(request, _('Observation template created.'))
        return redirect(project)
    return render(
        request,
        'tracker/observation_template_form.html',
        {'form': form, 'project': project, 'mode': 'create'},
    )


@login_required
def observation_template_update(request, pk: int):  # pragma: no cover
    template = get_object_or_404(ObservationTemplate.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, template.project, _('You need editor permissions to edit observation templates.'))
    form = ObservationTemplateForm(
        request.POST or None, instance=template, project=template.project
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Observation template updated.'))
        return redirect(template.project)
    return render(
        request,
        'tracker/observation_template_form.html',
        {'form': form, 'project': template.project, 'mode': 'update', 'object': template},
    )


@login_required
def observation_template_delete(request, pk: int):  # pragma: no cover
    template = get_object_or_404(ObservationTemplate.objects.select_related('project'), pk=pk)
    _require_project_editor(request.user, template.project, _('You need editor permissions to delete observation templates.'))
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid() and form.cleaned_data['confirm']:
        project = template.project
        template.delete()
        messages.success(request, _('Observation template deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the observation template “{template.name}”',
            'project': template.project,
        },
    )


@login_required
def behavior_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = BehaviorForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        behavior = form.save(commit=False)
        behavior.project = project
        behavior.save()
        messages.success(request, _('Behavior created.'))
        return redirect(project)
    return render(
        request, 'tracker/behavior_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def behavior_update(request, pk: int):  # pragma: no cover
    behavior = _get_owned_behavior(request.user, pk)
    form = BehaviorForm(request.POST or None, instance=behavior, project=behavior.project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Behavior updated.'))
        return redirect(behavior.project)
    return render(
        request,
        'tracker/behavior_form.html',
        {'form': form, 'project': behavior.project, 'mode': 'update', 'object': behavior},
    )


@login_required
def behavior_delete(request, pk: int):  # pragma: no cover
    behavior = _get_owned_behavior(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = behavior.project
        behavior.delete()
        messages.success(request, _('Behavior deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the behavior “{behavior.name}”',
            'project': behavior.project,
        },
    )


@login_required
def video_create(request, pk: int):  # pragma: no cover
    project = get_accessible_project(request.user, pk)
    _require_project_editor(request.user, project)
    form = VideoAssetForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        video = form.save(commit=False)
        video.project = project
        video.save()
        messages.success(request, _('Video added.'))
        return redirect(project)
    return render(
        request, 'tracker/video_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def video_update(request, pk: int):  # pragma: no cover
    video = _get_owned_video(request.user, pk)
    form = VideoAssetForm(request.POST or None, request.FILES or None, instance=video)
    if request.method == 'POST' and form.is_valid():
        video = form.save(commit=False)
        video.project = video.project
        video.save()
        messages.success(request, _('Video updated.'))
        return redirect(video.project)
    return render(
        request,
        'tracker/video_form.html',
        {'form': form, 'project': video.project, 'mode': 'update', 'object': video},
    )


@login_required
def video_delete(request, pk: int):  # pragma: no cover
    video = _get_owned_video(request.user, pk)
    if video.sessions.exists() or video.session_links.exists():
        messages.error(request, _('This video is still linked to one or more sessions.'))
        return redirect(video.project)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = video.project
        video.delete()
        messages.success(request, _('Video deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {'form': form, 'object_label': f'the video “{video.title}”', 'project': video.project},
    )


@login_required
def session_create(request, pk: int):  # pragma: no cover
    project = get_object_or_404(
        accessible_projects_qs(request.user).prefetch_related('videos', 'keyboard_profiles'), pk=pk
    )
    _require_project_editor(request.user, project, _('You need editor permissions to create sessions.'))
    form = ObservationSessionForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        session = form.save(commit=False)
        session.project = project
        session.observer = request.user
        session.save()
        if session.template_id and not session.title:
            session.title = session.template.name
            session.save(update_fields=['title'])
        form.save_variable_values(session)
        _sync_session_videos(session, form.cleaned_data['additional_videos'])
        messages.success(request, _('Session created.'))
        return redirect(session)
    return render(
        request, 'tracker/session_form.html', {'form': form, 'project': project, 'mode': 'create'}
    )


@login_required
def session_update(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    _require_project_editor(request.user, session.project, _('You need editor permissions to update sessions.'))
    form = ObservationSessionForm(request.POST or None, instance=session, project=session.project)
    if request.method == 'POST' and form.is_valid():
        session = form.save()
        form.save_variable_values(session)
        _sync_session_videos(session, form.cleaned_data['additional_videos'])
        messages.success(request, _('Session updated.'))
        return redirect(session)
    return render(
        request,
        'tracker/session_form.html',
        {'form': form, 'project': session.project, 'session': session, 'mode': 'update'},
    )


@login_required
def session_delete(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    if not session.project.can_edit(request.user) and session.observer_id != request.user.id:
        raise PermissionDenied(_('Only editors or the assigned observer can delete the session.'))
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = session.project
        session.delete()
        messages.success(request, _('Session deleted.'))
        return redirect(project)
    return render(
        request,
        'tracker/delete_confirm.html',
        {
            'form': form,
            'object_label': f'the session “{session.title}”',
            'project': session.project,
        },
    )


@login_required
def session_import_json(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    _require_editable_session(session, request.user)
    form = SessionImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            payload = json.loads(form.cleaned_data['file'].read().decode('utf-8'))
            event_count, annotation_count = import_session_payload(
                session, payload, clear_existing=form.cleaned_data['clear_existing']
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            messages.error(request, _('The uploaded file is not valid JSON.'))
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            _log_audit(
                session,
                actor=request.user,
                action=ObservationAuditLog.ACTION_IMPORT,
                target_type=ObservationAuditLog.TARGET_IMPORT,
                target_id=session.id,
                summary=f'Imported {event_count} events and {annotation_count} annotations.',
                payload={'event_count': event_count, 'annotation_count': annotation_count},
            )
            messages.success(
                request,
                _('Import complete. Imported events: %(events)s. Imported annotations: %(annotations)s.') % {'events': event_count, 'annotations': annotation_count},
            )
            return redirect(session)
    return render(
        request,
        'tracker/session_import.html',
        {'form': form, 'session': session, 'project': session.project},
    )


def close_open_state_events(session: ObservationSession, actor, timestamp_seconds=None) -> int:
    """Insert STOP events at the end of the session for still-open state events."""
    if timestamp_seconds is None:
        timestamp_seconds = _session_duration(session)
    stop_at = _decimal(timestamp_seconds, default='0')
    open_states: dict[int, bool] = {
        behavior.id: False for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE)
    }
    for event in session.events.select_related('behavior').order_by('timestamp_seconds', 'pk'):
        if event.behavior.mode != Behavior.MODE_STATE:
            continue
        if event.event_kind == ObservationEvent.KIND_START:
            open_states[event.behavior_id] = True
        elif event.event_kind == ObservationEvent.KIND_STOP:
            open_states[event.behavior_id] = False

    created = 0
    for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE).order_by('sort_order', 'name'):
        if not open_states.get(behavior.id):
            continue
        event = ObservationEvent.objects.create(
            session=session,
            behavior=behavior,
            event_kind=ObservationEvent.KIND_STOP,
            timestamp_seconds=stop_at,
            comment=_('Automatically inserted STOP for an open state.'),
        )
        _log_audit(
            session,
            actor=actor,
            action=ObservationAuditLog.ACTION_UPDATE,
            target_type=ObservationAuditLog.TARGET_EVENT,
            target_id=event.id,
            summary=f'Inserted STOP for open state {behavior.name}.',
            payload=serialize_event(event),
        )
        created += 1
    return created




@login_required
@require_POST
def session_workflow_action(request, pk: int):
    session = get_accessible_session(request.user, pk)
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST.dict()
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': _('Invalid JSON: %(error)s') % {'error': exc}}, status=400)
    action = payload.get('action')
    review_notes = (payload.get('review_notes') or session.review_notes or '').strip()
    status_map = {
        'submit': ObservationSession.STATUS_IN_REVIEW,
        'validate': ObservationSession.STATUS_VALIDATED,
        'lock': ObservationSession.STATUS_LOCKED,
        'unlock': ObservationSession.STATUS_DRAFT,
        'reopen': ObservationSession.STATUS_DRAFT,
        'save_notes': None,
        'fix_unpaired_states': None,
    }
    if action not in status_map:
        return JsonResponse({'error': _('Invalid workflow action.')}, status=400)
    if action == 'submit':
        if not session.project.can_edit(request.user):
            return JsonResponse({'error': _('You need editor permissions to submit a session for review.')}, status=403)
    elif action == 'fix_unpaired_states':
        if not session.project.can_edit(request.user):
            return JsonResponse({'error': _('You need editor permissions to fix unpaired states.')}, status=403)
    else:
        if not session.project.can_review(request.user):
            return JsonResponse({'error': _('You need reviewer permissions to change workflow status.')}, status=403)
    if action == 'fix_unpaired_states':
        fixed_count = close_open_state_events(session, actor=request.user, timestamp_seconds=payload.get('timestamp_seconds'))
        return JsonResponse({
            'ok': True,
            'fixed_count': fixed_count,
            'workflow_status': session.workflow_status,
            'review_notes': session.review_notes,
        })
    if action == 'save_notes':
        session.review_notes = review_notes
        session.save(update_fields=['review_notes'])
        _log_audit(
            session,
            actor=request.user,
            action=ObservationAuditLog.ACTION_UPDATE,
            target_type=ObservationAuditLog.TARGET_SESSION,
            target_id=session.id,
            summary='Review notes updated.',
            payload={'review_notes': review_notes},
        )
        return JsonResponse({
            'ok': True,
            'workflow_status': session.workflow_status,
            'review_notes': session.review_notes,
        })
    session.workflow_status = status_map[action]
    session.review_notes = review_notes
    now = timezone.now()
    if session.workflow_status in {
        ObservationSession.STATUS_IN_REVIEW,
        ObservationSession.STATUS_VALIDATED,
    }:
        session.reviewed_by = request.user
        session.reviewed_at = now
    if session.workflow_status == ObservationSession.STATUS_LOCKED:
        session.locked_at = now
    elif action == 'unlock':
        session.locked_at = None
    session.save(
        update_fields=['workflow_status', 'review_notes', 'reviewed_by', 'reviewed_at', 'locked_at']
    )
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_STATUS,
        target_type=ObservationAuditLog.TARGET_SESSION,
        target_id=session.id,
        summary=f'Workflow changed to {session.workflow_status}.',
        payload={'workflow_status': session.workflow_status, 'review_notes': review_notes},
    )
    return JsonResponse(
        {
            'ok': True,
            'workflow_status': session.workflow_status,
            'review_notes': session.review_notes,
        }
    )


@login_required
@require_GET
def session_audit_json(request, pk: int):
    session = get_accessible_session(request.user, pk)
    return JsonResponse({'audit_rows': build_audit_rows(session)})


@login_required
@ensure_csrf_cookie
@require_GET
def session_player(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    synced_videos = list(session.video_links.select_related('video').order_by('sort_order', 'pk'))
    if not synced_videos:
        _sync_session_videos(session, [])
        synced_videos = list(
            session.video_links.select_related('video').order_by('sort_order', 'pk')
        )
    active_profile = session.effective_keyboard_profile
    return render(
        request,
        'tracker/session_player.html',
        {
            'session': session,
            'behaviors': session.project.behaviors.select_related('category').all(),
            'modifiers': session.project.modifiers.all(),
            'subjects': session.project.subjects.prefetch_related('groups').all(),
            'subject_groups': session.project.subject_groups.all(),
            'state_status': compute_state_status(session),
            'stats': build_statistics(session),
            'timeline_buckets': build_timeline_buckets(session),
            'track_rows': build_track_rows(session),
            'subject_rows': build_subject_statistics(session),
            'transition_rows': build_transition_rows(session),
            'audit_rows': build_audit_rows(session),
            'interval_rows': build_interval_rows(session),
            'integrity_report': build_integrity_report(session),
            'annotations': session.annotations.all(),
            'variable_values': session.variable_values.all(),
            'synced_videos': synced_videos,
            'can_code_session': session.project.can_edit(request.user),
            'can_review_session': session.project.can_review(request.user),
            'active_keyboard_profile': active_profile,
            'keyboard_profiles': session.project.keyboard_profiles.order_by('name'),
            'keyboard_profile_payload': {
                'behaviors': active_profile.behavior_bindings if active_profile else {},
                'modifiers': active_profile.modifier_bindings if active_profile else {},
                'subjects': active_profile.subject_bindings if active_profile else {},
            },
        },
    )


@login_required
@require_GET
def session_events_json(request, pk: int):
    session = get_accessible_session(request.user, pk)
    duration_hint = request.GET.get('duration')
    events = [serialize_event(event) for event in session.events.all()]
    return JsonResponse(
        {
            'events': events,
            'annotations': [serialize_annotation(item) for item in session.annotations.all()],
            'state_status': compute_state_status(session),
            'stats': build_statistics(session, duration_hint=duration_hint),
            'timeline_buckets': build_timeline_buckets(session, duration_hint=duration_hint),
            'track_rows': build_track_rows(session, duration_hint=duration_hint),
            'subject_rows': build_subject_statistics(session, duration_hint=duration_hint),
            'transition_rows': build_transition_rows(session),
            'audit_rows': build_audit_rows(session),
            'interval_rows': build_interval_rows(session),
            'integrity_report': build_integrity_report(session),
            'workflow_status': session.workflow_status,
            'review_notes': session.review_notes,
            'synced_videos': [
                {
                    'id': link.video_id,
                    'title': link.video.title,
                    'url': link.video.file.url,
                    'sort_order': link.sort_order,
                }
                for link in session.video_links.select_related('video').order_by('sort_order', 'pk')
            ],
        }
    )


@login_required
@require_POST
def event_create_api(request, pk: int):
    session = get_accessible_session(request.user, pk)
    _require_editable_session(session, request.user)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': _('Invalid JSON: %(error)s') % {'error': exc}}, status=400)

    behavior = get_object_or_404(Behavior, pk=payload.get('behavior_id'), project=session.project)
    timestamp_seconds = _decimal(payload.get('timestamp_seconds'), default='0')
    modifier_ids = payload.get('modifier_ids') or []
    subject_ids = payload.get('subject_ids') or []
    if not isinstance(modifier_ids, list):
        return JsonResponse({'error': _('modifier_ids must be a list.')}, status=400)
    if not isinstance(subject_ids, list):
        return JsonResponse({'error': _('subject_ids must be a list.')}, status=400)
    try:
        normalized_modifier_ids = [int(value) for value in modifier_ids]
        normalized_subject_ids = [int(value) for value in subject_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': _('Invalid modifier_ids or subject_ids.')}, status=400)
    modifiers = list(
        Modifier.objects.filter(project=session.project, pk__in=normalized_modifier_ids)
    )
    subjects = list(
        Subject.objects.filter(
            project=session.project, pk__in=normalized_subject_ids
        ).prefetch_related('groups')
    )
    if {modifier.pk for modifier in modifiers} != set(normalized_modifier_ids):
        return JsonResponse({'error': _('One or more modifiers are invalid.')}, status=400)
    if {subject.pk for subject in subjects} != set(normalized_subject_ids):
        return JsonResponse({'error': _('One or more subjects are invalid.')}, status=400)

    event = ObservationEvent.objects.create(
        session=session,
        behavior=behavior,
        subject=subjects[0] if subjects else None,
        event_kind=resolve_event_kind(session, behavior, payload.get('event_kind')),
        timestamp_seconds=timestamp_seconds,
        comment=(payload.get('comment') or '').strip(),
        frame_index=payload.get('frame_index') or None,
    )
    if modifiers:
        event.modifiers.set(modifiers)
    if subjects:
        event.subjects.set(subjects)
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_CREATE,
        target_type=ObservationAuditLog.TARGET_EVENT,
        target_id=event.id,
        summary=f'Created event {event.behavior.name} at {event.timestamp_seconds}s.',
        payload=serialize_event(event),
    )
    return JsonResponse(
        {'event': serialize_event(event), 'state_status': compute_state_status(session)}, status=201
    )


@login_required
@require_POST
def event_update_api(request, pk: int):
    event = get_object_or_404(
        ObservationEvent.objects.select_related('session__project', 'behavior'), pk=pk
    )
    session = get_accessible_session(request.user, event.session_id)
    _require_editable_session(session, request.user)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': _('Invalid JSON: %(error)s') % {'error': exc}}, status=400)

    behavior = get_object_or_404(
        Behavior, pk=payload.get('behavior_id', event.behavior_id), project=session.project
    )
    timestamp_seconds = _decimal(
        payload.get('timestamp_seconds', event.timestamp_seconds), default='0'
    )
    modifier_ids = payload.get('modifier_ids', list(event.modifiers.values_list('id', flat=True)))
    subject_ids = payload.get(
        'subject_ids',
        list(event.subjects.values_list('id', flat=True))
        or ([event.subject_id] if event.subject_id else []),
    )
    if not isinstance(modifier_ids, list):
        return JsonResponse({'error': _('modifier_ids must be a list.')}, status=400)
    if not isinstance(subject_ids, list):
        return JsonResponse({'error': _('subject_ids must be a list.')}, status=400)
    try:
        normalized_modifier_ids = [int(value) for value in modifier_ids]
        normalized_subject_ids = [int(value) for value in subject_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': _('Invalid modifier_ids or subject_ids.')}, status=400)
    modifiers = list(
        Modifier.objects.filter(project=session.project, pk__in=normalized_modifier_ids)
    )
    subjects = list(
        Subject.objects.filter(
            project=session.project, pk__in=normalized_subject_ids
        ).prefetch_related('groups')
    )
    if {modifier.pk for modifier in modifiers} != set(normalized_modifier_ids):
        return JsonResponse({'error': _('One or more modifiers are invalid.')}, status=400)
    if {subject.pk for subject in subjects} != set(normalized_subject_ids):
        return JsonResponse({'error': _('One or more subjects are invalid.')}, status=400)

    explicit_kind = payload.get('event_kind', event.event_kind)
    if behavior.mode == Behavior.MODE_POINT:
        explicit_kind = ObservationEvent.KIND_POINT
    elif explicit_kind not in {ObservationEvent.KIND_START, ObservationEvent.KIND_STOP}:
        return JsonResponse({'error': _('Invalid event_kind for a state behavior.')}, status=400)

    event.behavior = behavior
    event.event_kind = explicit_kind
    event.timestamp_seconds = timestamp_seconds
    event.comment = (payload.get('comment') or '').strip()
    event.frame_index = payload.get('frame_index', event.frame_index)
    event.subject = subjects[0] if subjects else None
    event.save(
        update_fields=[
            'behavior',
            'event_kind',
            'timestamp_seconds',
            'comment',
            'frame_index',
            'subject',
        ]
    )
    event.modifiers.set(modifiers)
    event.subjects.set(subjects)
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_UPDATE,
        target_type=ObservationAuditLog.TARGET_EVENT,
        target_id=event.id,
        summary=f'Updated event {event.behavior.name} at {event.timestamp_seconds}s.',
        payload=serialize_event(event),
    )
    return JsonResponse(
        {'event': serialize_event(event), 'state_status': compute_state_status(session)}
    )


@login_required
@require_POST
def event_delete_api(request, pk: int):
    event = get_object_or_404(ObservationEvent.objects.select_related('session__project'), pk=pk)
    if event.session.project_id not in set(
        accessible_projects_qs(request.user).values_list('id', flat=True)
    ):
        raise Http404(_('Event not found.'))
    session = get_accessible_session(request.user, event.session_id)
    _require_editable_session(session, request.user)
    payload = serialize_event(event)
    event.delete()
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_DELETE,
        target_type=ObservationAuditLog.TARGET_EVENT,
        target_id=payload['id'],
        summary=f'Deleted event {payload["behavior"]} at {payload["timestamp_seconds"]}s.',
        payload=payload,
    )
    return JsonResponse({'ok': True, 'state_status': compute_state_status(session)})


@login_required
@require_POST
def annotation_create_api(request, pk: int):
    session = get_accessible_session(request.user, pk)
    _require_project_reviewer(request.user, session.project, _('You need reviewer permissions to create annotations.'))
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': _('Invalid JSON: %(error)s') % {'error': exc}}, status=400)
    annotation = SessionAnnotation.objects.create(
        session=session,
        timestamp_seconds=_decimal(payload.get('timestamp_seconds'), default='0'),
        title=(payload.get('title') or 'Note').strip()[:120] or 'Note',
        note=(payload.get('note') or '').strip(),
        color=(payload.get('color') or '#f59e0b')[:7],
        created_by=request.user,
    )
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_CREATE,
        target_type=ObservationAuditLog.TARGET_ANNOTATION,
        target_id=annotation.id,
        summary=f'Created annotation {annotation.title} at {annotation.timestamp_seconds}s.',
        payload=serialize_annotation(annotation),
    )
    return JsonResponse({'annotation': serialize_annotation(annotation)}, status=201)


@login_required
@require_POST
def annotation_update_api(request, pk: int):
    annotation = get_object_or_404(
        SessionAnnotation.objects.select_related('session__project'), pk=pk
    )
    session = get_accessible_session(request.user, annotation.session_id)
    _require_project_reviewer(request.user, session.project, _('You need reviewer permissions to update annotations.'))
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': _('Invalid JSON: %(error)s') % {'error': exc}}, status=400)
    annotation.timestamp_seconds = _decimal(
        payload.get('timestamp_seconds', annotation.timestamp_seconds), default='0'
    )
    annotation.title = (payload.get('title') or annotation.title).strip()[:120] or 'Note'
    annotation.note = (payload.get('note') or '').strip()
    annotation.color = (payload.get('color') or annotation.color)[:7]
    annotation.save(update_fields=['timestamp_seconds', 'title', 'note', 'color'])
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_UPDATE,
        target_type=ObservationAuditLog.TARGET_ANNOTATION,
        target_id=annotation.id,
        summary=f'Updated annotation {annotation.title} at {annotation.timestamp_seconds}s.',
        payload=serialize_annotation(annotation),
    )
    return JsonResponse({'annotation': serialize_annotation(annotation), 'session_id': session.id})


@login_required
@require_POST
def annotation_delete_api(request, pk: int):
    annotation = get_object_or_404(
        SessionAnnotation.objects.select_related('session__project'), pk=pk
    )
    if annotation.session.project_id not in set(
        accessible_projects_qs(request.user).values_list('id', flat=True)
    ):
        raise Http404(_('Annotation not found.'))
    _require_editable_session(annotation.session)
    payload = serialize_annotation(annotation)
    session = annotation.session
    annotation.delete()
    _log_audit(
        session,
        actor=request.user,
        action=ObservationAuditLog.ACTION_DELETE,
        target_type=ObservationAuditLog.TARGET_ANNOTATION,
        target_id=payload['id'],
        summary=f'Deleted annotation {payload["title"]} at {payload["timestamp_seconds"]}s.',
        payload=payload,
    )
    return JsonResponse({'ok': True})


@login_required
def session_export_csv(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.csv"'
    response.write('﻿')
    writer = csv.writer(response, delimiter=';')
    writer.writerow(
        [
            'project',
            'session',
            'primary_video',
            'synced_videos',
            'observer',
            'category',
            'behavior',
            'behavior_mode',
            'event_kind',
            'timestamp_seconds',
            'subjects',
            'modifiers',
            'comment',
            'created_at',
        ]
    )
    for row in _event_rows(session):
        writer.writerow(row)
    return response


@login_required
def session_export_tsv(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    response = HttpResponse(content_type='text/tab-separated-values; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.tsv"'
    writer = csv.writer(response, delimiter='\t')
    writer.writerow(['time', 'behavior', 'event_kind', 'subjects', 'modifiers', 'comment'])
    for event in session.events.all():
        writer.writerow(
            [
                str(event.timestamp_seconds),
                event.behavior.name,
                event.event_kind,
                event.subjects_display,
                event.modifiers_display,
                event.comment,
            ]
        )
    return response


@login_required
def session_export_json(request, pk: int):
    session = get_accessible_session(request.user, pk)
    payload = {
        'schema': 'pybehaviorlog-0.8.5-session',
        'project': session.project.name,
        'session': session.title,
        'video': session.primary_label,
        'synced_videos': [video.title for video in session.all_videos_ordered],
        'observer': session.observer.username if session.observer else None,
        'statistics': build_statistics(session),
        'integrity_report': build_integrity_report(session),
        'interval_rows': build_interval_rows(session),
        'timeline_buckets': build_timeline_buckets(session),
        'track_rows': build_track_rows(session),
        'subject_rows': build_subject_statistics(session),
        'transition_rows': build_transition_rows(session),
        'audit_rows': build_audit_rows(session),
        'workflow_status': session.workflow_status,
        'review_notes': session.review_notes,
        'variables': {item.definition.label: item.value for item in session.variable_values.all()},
        'events': [serialize_event(event) for event in session.events.all()],
        'annotations': [serialize_annotation(item) for item in session.annotations.all()],
    }
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.json"'
    return response


@login_required
def session_export_boris_json(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    payload = build_boris_like_payload(session)
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_boris_like.json"'
    return response


@login_required
def session_export_xlsx(request, pk: int):  # pragma: no cover
    session = get_accessible_session(request.user, pk)
    workbook = Workbook()
    events_sheet = workbook.active
    events_sheet.title = 'Events'
    events_sheet.append(
        [
            'Project',
            'Session',
            'Primary video',
            'Synced videos',
            'Observer',
            'Category',
            'Behavior',
            'Behavior mode',
            'Event kind',
            'Timestamp seconds',
            'Modifiers',
            'Comment',
            'Created at',
        ]
    )
    for row in _event_rows(session):
        events_sheet.append(row)

    annotations_sheet = workbook.create_sheet('Annotations')
    annotations_sheet.append(
        [
            'Project',
            'Session',
            'Timestamp seconds',
            'Title',
            'Note',
            'Color',
            'Created by',
            'Created at',
        ]
    )
    for row in _annotation_rows(session):
        annotations_sheet.append(row)

    stats = build_statistics(session)
    stats_sheet = workbook.create_sheet('Summary')
    stats_sheet.append(['Session', session.title])
    stats_sheet.append(['Observed span seconds', stats['observed_span_seconds']])
    stats_sheet.append(['Event count', stats['session_event_count']])
    stats_sheet.append(['Annotation count', stats['annotation_count']])
    stats_sheet.append(['Point count', stats['point_event_count']])
    stats_sheet.append(['Open state count', stats['open_state_count']])
    stats_sheet.append(['State duration seconds', stats['state_duration_seconds']])
    stats_sheet.append(
        ['Synced videos', ', '.join(video.title for video in session.all_videos_ordered)]
    )
    stats_sheet.append([])
    stats_sheet.append(
        [
            'Category',
            'Behavior',
            'Mode',
            'Point count',
            'Start count',
            'Stop count',
            'Segments',
            'Total duration seconds',
            'Occupancy %',
            'Open',
        ]
    )
    for row in stats['rows']:
        stats_sheet.append(
            [
                row['category'],
                row['name'],
                row['mode'],
                row['point_count'],
                row['start_count'],
                row['stop_count'],
                row['segment_count'],
                row['total_duration_seconds'],
                row['occupancy_percent'],
                'yes' if row['is_open'] else 'no',
            ]
        )

    intervals_sheet = workbook.create_sheet('Intervals')
    intervals_sheet.append(
        [
            'Category',
            'Behavior',
            'Mode',
            'Interval count',
            'Mean interval seconds',
            'Min interval seconds',
            'Max interval seconds',
        ]
    )
    for row in build_interval_rows(session):
        intervals_sheet.append(
            [
                row['category'],
                row['name'],
                row['mode'],
                row['interval_count'],
                row['mean_interval_seconds'],
                row['min_interval_seconds'],
                row['max_interval_seconds'],
            ]
        )

    integrity_sheet = workbook.create_sheet('Integrity')
    integrity = build_integrity_report(session)
    integrity_sheet.append(['Issue count', integrity['issue_count']])
    integrity_sheet.append([])
    integrity_sheet.append(['Severity', 'Message'])
    for item in integrity['issues']:
        integrity_sheet.append([item['severity'], item['message']])

    buckets_sheet = workbook.create_sheet('Timeline')
    buckets_sheet.append(
        [
            'Start seconds',
            'End seconds',
            'Events',
            'Point events',
            'State changes',
            'Annotations',
            'Top labels',
        ]
    )
    for bucket in build_timeline_buckets(session):
        buckets_sheet.append(
            [
                bucket['start_seconds'],
                bucket['end_seconds'],
                bucket['event_count'],
                bucket['point_count'],
                bucket['state_change_count'],
                bucket['annotation_count'],
                ', '.join(f'{name} ({count})' for name, count in bucket['labels'].items()),
            ]
        )

    _autosize_workbook(workbook)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.xlsx"'
    workbook.save(response)
    return response
