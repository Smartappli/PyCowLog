from __future__ import annotations

import csv
import json
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
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from openpyxl import Workbook

from .forms import (
    BehaviorCategoryForm,
    BehaviorForm,
    DeleteConfirmForm,
    EthogramImportForm,
    ModifierForm,
    ObservationSessionForm,
    ProjectForm,
    ProjectSettingsForm,
    SignUpForm,
    VideoAssetForm,
)
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


def signup(request):
    if request.user.is_authenticated:
        return redirect('tracker:home')

    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Compte créé avec succès.')
        return redirect('tracker:home')
    return render(request, 'registration/signup.html', {'form': form})


def accessible_projects_qs(user):
    return (
        Project.objects.filter(Q(owner=user) | Q(collaborators=user))
        .distinct()
        .select_related('owner')
        .prefetch_related('collaborators')
    )


def get_accessible_project(user, pk: int) -> Project:
    return get_object_or_404(accessible_projects_qs(user), pk=pk)


def get_owned_project(user, pk: int) -> Project:
    project = get_accessible_project(user, pk)
    if project.owner_id != user.id:
        raise PermissionDenied('Seul le propriétaire du projet peut modifier sa configuration.')
    return project


def accessible_sessions_qs(user):
    return (
        ObservationSession.objects.filter(Q(project__owner=user) | Q(project__collaborators=user))
        .distinct()
        .select_related('project', 'video', 'observer', 'project__owner')
    )


def get_accessible_session(user, pk: int) -> ObservationSession:
    session_qs = accessible_sessions_qs(user).prefetch_related(
        'project__behaviors__category',
        'project__modifiers',
        'project__categories',
        'video_links__video',
        Prefetch(
            'events',
            queryset=ObservationEvent.objects.select_related('behavior', 'behavior__category').prefetch_related('modifiers').order_by('timestamp_seconds', 'pk'),
        ),
    )
    return get_object_or_404(session_qs, pk=pk)


def _get_owned_category(user, pk: int) -> BehaviorCategory:
    category = get_object_or_404(BehaviorCategory.objects.select_related('project'), pk=pk)
    if category.project.owner_id != user.id:
        raise PermissionDenied('Seul le propriétaire du projet peut modifier les catégories.')
    return category


def _get_owned_modifier(user, pk: int) -> Modifier:
    modifier = get_object_or_404(Modifier.objects.select_related('project'), pk=pk)
    if modifier.project.owner_id != user.id:
        raise PermissionDenied('Seul le propriétaire du projet peut modifier les modificateurs.')
    return modifier


def _get_owned_behavior(user, pk: int) -> Behavior:
    behavior = get_object_or_404(Behavior.objects.select_related('project', 'category'), pk=pk)
    if behavior.project.owner_id != user.id:
        raise PermissionDenied('Seul le propriétaire du projet peut modifier les comportements.')
    return behavior


def _get_owned_video(user, pk: int) -> VideoAsset:
    video = get_object_or_404(VideoAsset.objects.select_related('project'), pk=pk)
    if video.project.owner_id != user.id:
        raise PermissionDenied('Seul le propriétaire du projet peut modifier les vidéos.')
    return video


def _decimal(value, default: str = '0') -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def serialize_event(event: ObservationEvent) -> dict:
    modifiers = list(event.modifiers.order_by('sort_order', 'name').values('id', 'name', 'key_binding'))
    return {
        'id': event.pk,
        'behavior': event.behavior.name,
        'behavior_id': event.behavior_id,
        'behavior_mode': event.behavior.mode,
        'category': event.behavior.category.name if event.behavior.category else '',
        'color': event.behavior.color,
        'event_kind': event.event_kind,
        'timestamp_seconds': float(event.timestamp_seconds),
        'comment': event.comment,
        'modifiers': modifiers,
        'created_at': event.created_at.isoformat(),
    }


def compute_state_status(session: ObservationSession) -> dict[int, bool]:
    state_map: dict[int, bool] = {}
    state_behaviors = {behavior.id for behavior in session.project.behaviors.filter(mode=Behavior.MODE_STATE)}
    for behavior_id in state_behaviors:
        state_map[behavior_id] = False

    event_qs = ObservationEvent.objects.filter(session=session).select_related('behavior').order_by('timestamp_seconds', 'pk')
    for event in event_qs:
        if event.behavior.mode != Behavior.MODE_STATE:
            continue
        if event.event_kind == ObservationEvent.KIND_START:
            state_map[event.behavior_id] = True
        elif event.event_kind == ObservationEvent.KIND_STOP:
            state_map[event.behavior_id] = False
    return state_map


def build_statistics(session: ObservationSession, duration_hint: str | float | Decimal | None = None) -> dict:
    end_time = _decimal(duration_hint, default='0')
    if end_time <= 0:
        last_event = ObservationEvent.objects.filter(session=session).order_by('-timestamp_seconds').first()
        if last_event is not None:
            end_time = last_event.timestamp_seconds

    behaviors = list(session.project.behaviors.select_related('category').order_by('sort_order', 'name'))
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
        if behavior.mode == Behavior.MODE_STATE and start_time is not None and end_time >= start_time:
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
            item['occupancy_percent'] = round(float((item['total_duration_seconds'] / end_time) * 100), 2)
        rows.append({
            **item,
            'total_duration_seconds': float(item['total_duration_seconds']),
        })

    return {
        'session_event_count': len(events),
        'point_event_count': total_points,
        'open_state_count': open_count,
        'observed_span_seconds': float(end_time),
        'state_duration_seconds': float(total_duration),
        'rows': rows,
    }


def build_timeline_buckets(session: ObservationSession, duration_hint: str | float | Decimal | None = None, bucket_seconds: int = 60) -> list[dict]:
    duration = _decimal(duration_hint, default='0')
    if duration <= 0:
        last_event = ObservationEvent.objects.filter(session=session).order_by('-timestamp_seconds').first()
        if last_event is not None:
            duration = last_event.timestamp_seconds
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
                'labels': defaultdict(int),
            },
        )
        bucket['event_count'] += 1
        if event.event_kind == ObservationEvent.KIND_POINT:
            bucket['point_count'] += 1
        else:
            bucket['state_change_count'] += 1
        bucket['labels'][behavior_names[event.behavior_id]] += 1

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
                'labels': {},
            }
        else:
            bucket['labels'] = dict(sorted(bucket['labels'].items(), key=lambda item: (-item[1], item[0]))[:5])
        results.append(bucket)
    return results


def build_project_statistics(project: Project) -> dict:
    sessions = list(
        project.sessions.select_related('observer', 'video').prefetch_related(
            Prefetch(
                'events',
                queryset=ObservationEvent.objects.select_related('behavior', 'behavior__category').prefetch_related('modifiers').order_by('timestamp_seconds', 'pk'),
            )
        )
    )
    aggregate: dict[int, dict] = {}
    session_rows = []
    total_events = 0
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
        total_span += stats['observed_span_seconds']
        session_rows.append({
            'session_id': session.id,
            'title': session.title,
            'observer': session.observer.username if session.observer else '',
            'video': session.video.title,
            'synced_video_count': session.video_links.count(),
            'event_count': stats['session_event_count'],
            'point_event_count': stats['point_event_count'],
            'open_state_count': stats['open_state_count'],
            'observed_span_seconds': stats['observed_span_seconds'],
            'state_duration_seconds': stats['state_duration_seconds'],
        })
        for row in stats['rows']:
            item = aggregate[row['behavior_id']]
            if row['point_count'] or row['segment_count'] or row['start_count'] or row['stop_count']:
                item['session_count'] += 1
            item['point_count'] += row['point_count']
            item['start_count'] += row['start_count']
            item['stop_count'] += row['stop_count']
            item['segment_count'] += row['segment_count']
            item['duration_seconds'] += row['total_duration_seconds']

    behavior_rows = []
    for behavior_id, item in aggregate.items():
        del behavior_id
        item['duration_seconds'] = round(item['duration_seconds'], 3)
        behavior_rows.append(item)

    behavior_rows.sort(key=lambda row: (row['category'], row['name']))
    session_rows.sort(key=lambda row: row['title'])

    return {
        'project_name': project.name,
        'session_count': len(sessions),
        'video_count': project.videos.count(),
        'behavior_count': project.behaviors.count(),
        'event_count': total_events,
        'observed_span_seconds': round(total_span, 3),
        'session_rows': session_rows,
        'behavior_rows': behavior_rows,
    }


def build_ethogram_payload(project: Project) -> dict:
    return {
        'schema': 'cowlog-django-v4-ethogram',
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
            for behavior in project.behaviors.select_related('category').order_by('sort_order', 'name')
        ],
    }


@transaction.atomic
def import_ethogram_payload(project: Project, payload: dict, replace_existing: bool = False) -> tuple[int, int, int]:
    if payload.get('schema') not in {'cowlog-django-v3-ethogram', 'cowlog-django-v4-ethogram'}:
        raise ValueError('Schéma JSON non reconnu.')

    if replace_existing and (project.sessions.exists() or ObservationEvent.objects.filter(session__project=project).exists()):
        raise ValueError(
            'Le remplacement complet est bloqué car le projet contient déjà des sessions ou des événements.'
        )

    if replace_existing:
        project.behaviors.all().delete()
        project.modifiers.all().delete()
        project.categories.all().delete()

    category_map: dict[str, BehaviorCategory] = {category.name: category for category in project.categories.all()}
    modifier_count = 0
    behavior_count = 0
    category_count = 0

    for item in payload.get('categories', []):
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

    for item in payload.get('modifiers', []):
        _, created = Modifier.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or '')[0:1].upper(),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        if created:
            modifier_count += 1

    for item in payload.get('behaviors', []):
        category = None
        category_name = item.get('category')
        if category_name:
            category = category_map.get(category_name)
        _, created = Behavior.objects.update_or_create(
            project=project,
            name=item['name'],
            defaults={
                'category': category,
                'description': item.get('description', ''),
                'key_binding': (item.get('key_binding') or '')[0:1].upper(),
                'color': item.get('color', '#2563eb'),
                'mode': item.get('mode', Behavior.MODE_POINT),
                'sort_order': int(item.get('sort_order', 0)),
            },
        )
        if created:
            behavior_count += 1

    return category_count, modifier_count, behavior_count


def resolve_event_kind(session: ObservationSession, behavior: Behavior, explicit_kind: str | None) -> str:
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
    video_ids = [session.video_id]
    for video in additional_videos:
        if video.pk != session.video_id and video.pk not in video_ids:
            video_ids.append(video.pk)
    SessionVideoLink.objects.filter(session=session).exclude(video_id__in=video_ids).delete()
    for index, video_id in enumerate(video_ids):
        SessionVideoLink.objects.update_or_create(
            session=session,
            video_id=video_id,
            defaults={'sort_order': index},
        )


def _event_rows(session: ObservationSession):
    linked_titles = ', '.join(video.title for video in session.all_videos_ordered)
    for event in session.events.all():
        yield [
            session.project.name,
            session.title,
            session.video.title,
            linked_titles,
            session.observer.username if session.observer else '',
            event.behavior.category.name if event.behavior.category else '',
            event.behavior.name,
            event.behavior.mode,
            event.event_kind,
            str(event.timestamp_seconds),
            event.modifiers_display,
            event.comment,
            event.created_at.isoformat(),
        ]


def _append_autosized_sheet(workbook: Workbook, title: str, headers: list[str], rows: list[list]):
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    return sheet


def _autosize_workbook(workbook: Workbook):
    for sheet in workbook.worksheets:
        for column_cells in sheet.columns:
            max_len = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = '' if cell.value is None else str(cell.value)
                max_len = max(max_len, len(value))
            sheet.column_dimensions[column_letter].width = min(max_len + 2, 48)


@login_required
def home(request):
    projects = accessible_projects_qs(request.user).prefetch_related(
        'categories',
        'modifiers',
        'behaviors',
        'videos',
        'sessions__video',
        'sessions__video_links',
    )
    return render(request, 'tracker/home.html', {'projects': projects})


@login_required
def project_create(request):
    form = ProjectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = form.save(commit=False)
        project.owner = request.user
        project.save()
        messages.success(request, 'Projet créé avec succès.')
        return redirect(project)
    return render(request, 'tracker/project_form.html', {'form': form})


@login_required
def project_update(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = ProjectSettingsForm(request.POST or None, instance=project, owner=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Paramètres du projet mis à jour.')
        return redirect(project)
    return render(request, 'tracker/project_settings.html', {'form': form, 'project': project})


@login_required
def project_detail(request, pk: int):
    project = get_accessible_project(request.user, pk)
    project = (
        accessible_projects_qs(request.user)
        .prefetch_related('categories', 'modifiers', 'behaviors__category', 'videos', 'sessions__video', 'sessions__video_links')
        .get(pk=project.pk)
    )
    analytics = build_project_statistics(project)
    return render(
        request,
        'tracker/project_detail.html',
        {
            'project': project,
            'is_owner': project.owner_id == request.user.id,
            'analytics': analytics,
        },
    )


@login_required
def project_analytics(request, pk: int):
    project = get_accessible_project(request.user, pk)
    analytics = build_project_statistics(project)
    return render(request, 'tracker/project_analytics.html', {'project': project, 'analytics': analytics})


@login_required
def project_export_xlsx(request, pk: int):
    project = get_accessible_project(request.user, pk)
    analytics = build_project_statistics(project)
    workbook = Workbook()
    overview = workbook.active
    overview.title = 'Overview'
    overview.append(['Project', project.name])
    overview.append(['Sessions', analytics['session_count']])
    overview.append(['Videos', analytics['video_count']])
    overview.append(['Behaviors', analytics['behavior_count']])
    overview.append(['Events', analytics['event_count']])
    overview.append(['Observed span seconds', analytics['observed_span_seconds']])

    _append_autosized_sheet(
        workbook,
        'Sessions',
        ['Session', 'Observer', 'Primary video', 'Synced videos', 'Event count', 'Point count', 'Open states', 'Observed span seconds', 'State duration seconds'],
        [
            [
                row['title'],
                row['observer'],
                row['video'],
                row['synced_video_count'],
                row['event_count'],
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
        ['Category', 'Behavior', 'Mode', 'Sessions used', 'Point count', 'Start count', 'Stop count', 'Segments', 'Duration seconds'],
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

    _autosize_workbook(workbook)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{slugify(project.name) or "project"}_analytics.xlsx"'
    workbook.save(response)
    return response


@login_required
def project_export_ethogram(request, pk: int):
    project = get_accessible_project(request.user, pk)
    payload = build_ethogram_payload(project)
    filename = f"{slugify(project.name) or 'project'}_ethogram.json"
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def project_import_ethogram(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = EthogramImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['file']
        replace_existing = form.cleaned_data['replace_existing']
        try:
            payload = json.loads(uploaded.read().decode('utf-8'))
            category_count, modifier_count, behavior_count = import_ethogram_payload(
                project,
                payload,
                replace_existing=replace_existing,
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            messages.error(request, "Le fichier fourni n'est pas un JSON valide.")
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                (
                    f'Import terminé. Nouvelles catégories : {category_count}, '
                    f'modificateurs : {modifier_count}, comportements : {behavior_count}.'
                ),
            )
            return redirect(project)
    return render(request, 'tracker/ethogram_import.html', {'form': form, 'project': project})


@login_required
def category_create(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = BehaviorCategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save(commit=False)
        category.project = project
        category.save()
        messages.success(request, 'Catégorie ajoutée.')
        return redirect(project)
    return render(request, 'tracker/category_form.html', {'form': form, 'project': project, 'mode': 'create'})


@login_required
def category_update(request, pk: int):
    category = _get_owned_category(request.user, pk)
    form = BehaviorCategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Catégorie mise à jour.')
        return redirect(category.project)
    return render(request, 'tracker/category_form.html', {'form': form, 'project': category.project, 'mode': 'update', 'object': category})


@login_required
def category_delete(request, pk: int):
    category = _get_owned_category(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = category.project
        category.delete()
        messages.success(request, 'Catégorie supprimée.')
        return redirect(project)
    return render(request, 'tracker/delete_confirm.html', {'form': form, 'object_label': f'la catégorie « {category.name} »', 'project': category.project})


@login_required
def modifier_create(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = ModifierForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        modifier = form.save(commit=False)
        modifier.project = project
        modifier.save()
        messages.success(request, 'Modificateur ajouté.')
        return redirect(project)
    return render(request, 'tracker/modifier_form.html', {'form': form, 'project': project, 'mode': 'create'})


@login_required
def modifier_update(request, pk: int):
    modifier = _get_owned_modifier(request.user, pk)
    form = ModifierForm(request.POST or None, instance=modifier)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Modificateur mis à jour.')
        return redirect(modifier.project)
    return render(request, 'tracker/modifier_form.html', {'form': form, 'project': modifier.project, 'mode': 'update', 'object': modifier})


@login_required
def modifier_delete(request, pk: int):
    modifier = _get_owned_modifier(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = modifier.project
        modifier.delete()
        messages.success(request, 'Modificateur supprimé.')
        return redirect(project)
    return render(request, 'tracker/delete_confirm.html', {'form': form, 'object_label': f'le modificateur « {modifier.name} »', 'project': modifier.project})


@login_required
def behavior_create(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = BehaviorForm(request.POST or None, project=project)
    if request.method == 'POST' and form.is_valid():
        behavior = form.save(commit=False)
        behavior.project = project
        behavior.save()
        messages.success(request, 'Comportement ajouté.')
        return redirect(project)
    return render(request, 'tracker/behavior_form.html', {'form': form, 'project': project, 'mode': 'create'})


@login_required
def behavior_update(request, pk: int):
    behavior = _get_owned_behavior(request.user, pk)
    form = BehaviorForm(request.POST or None, instance=behavior, project=behavior.project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Comportement mis à jour.')
        return redirect(behavior.project)
    return render(request, 'tracker/behavior_form.html', {'form': form, 'project': behavior.project, 'mode': 'update', 'object': behavior})


@login_required
def behavior_delete(request, pk: int):
    behavior = _get_owned_behavior(request.user, pk)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = behavior.project
        behavior.delete()
        messages.success(request, 'Comportement supprimé.')
        return redirect(project)
    return render(request, 'tracker/delete_confirm.html', {'form': form, 'object_label': f'le comportement « {behavior.name} »', 'project': behavior.project})


@login_required
def video_create(request, pk: int):
    project = get_owned_project(request.user, pk)
    form = VideoAssetForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        video = form.save(commit=False)
        video.project = project
        video.save()
        messages.success(request, 'Vidéo ajoutée.')
        return redirect(project)
    return render(request, 'tracker/video_form.html', {'form': form, 'project': project, 'mode': 'create'})


@login_required
def video_update(request, pk: int):
    video = _get_owned_video(request.user, pk)
    form = VideoAssetForm(request.POST or None, request.FILES or None, instance=video)
    if request.method == 'POST' and form.is_valid():
        video = form.save(commit=False)
        video.project = video.project
        video.save()
        messages.success(request, 'Vidéo mise à jour.')
        return redirect(video.project)
    return render(request, 'tracker/video_form.html', {'form': form, 'project': video.project, 'mode': 'update', 'object': video})


@login_required
def video_delete(request, pk: int):
    video = _get_owned_video(request.user, pk)
    if video.sessions.exists() or video.session_links.exists():
        messages.error(request, 'Cette vidéo est encore utilisée par une ou plusieurs sessions.')
        return redirect(video.project)
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = video.project
        video.delete()
        messages.success(request, 'Vidéo supprimée.')
        return redirect(project)
    return render(request, 'tracker/delete_confirm.html', {'form': form, 'object_label': f'la vidéo « {video.title} »', 'project': video.project})


@login_required
def session_create(request, pk: int):
    project = get_object_or_404(accessible_projects_qs(request.user).prefetch_related('videos'), pk=pk)
    form = ObservationSessionForm(request.POST or None, project=project)
    if not project.videos.exists():
        messages.warning(request, "Ajoute d'abord une vidéo au projet.")
        return redirect(project)

    if request.method == 'POST' and form.is_valid():
        session = form.save(commit=False)
        session.project = project
        session.observer = request.user
        session.save()
        _sync_session_videos(session, form.cleaned_data['additional_videos'])
        messages.success(request, 'Session créée.')
        return redirect(session)
    return render(request, 'tracker/session_form.html', {'form': form, 'project': project, 'mode': 'create'})


@login_required
def session_update(request, pk: int):
    session = get_accessible_session(request.user, pk)
    form = ObservationSessionForm(request.POST or None, instance=session, project=session.project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _sync_session_videos(session, form.cleaned_data['additional_videos'])
        messages.success(request, 'Session mise à jour.')
        return redirect(session)
    return render(request, 'tracker/session_form.html', {'form': form, 'project': session.project, 'session': session, 'mode': 'update'})


@login_required
def session_delete(request, pk: int):
    session = get_accessible_session(request.user, pk)
    if session.project.owner_id != request.user.id and (session.observer_id != request.user.id):
        raise PermissionDenied('Seul le propriétaire du projet ou l’observateur peut supprimer la session.')
    form = DeleteConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        project = session.project
        session.delete()
        messages.success(request, 'Session supprimée.')
        return redirect(project)
    return render(request, 'tracker/delete_confirm.html', {'form': form, 'object_label': f'la session « {session.title} »', 'project': session.project})


@login_required
@ensure_csrf_cookie
@require_GET
def session_player(request, pk: int):
    session = get_accessible_session(request.user, pk)
    synced_videos = list(session.video_links.select_related('video').order_by('sort_order', 'pk'))
    if not synced_videos:
        _sync_session_videos(session, [])
        synced_videos = list(session.video_links.select_related('video').order_by('sort_order', 'pk'))
    return render(
        request,
        'tracker/session_player.html',
        {
            'session': session,
            'behaviors': session.project.behaviors.select_related('category').all(),
            'modifiers': session.project.modifiers.all(),
            'state_status': compute_state_status(session),
            'stats': build_statistics(session),
            'timeline_buckets': build_timeline_buckets(session),
            'synced_videos': synced_videos,
        },
    )


@login_required
@require_GET
def session_events_json(request, pk: int):
    session = get_accessible_session(request.user, pk)
    duration_hint = request.GET.get('duration')
    events = [serialize_event(event) for event in session.events.all()]
    return JsonResponse({
        'events': events,
        'state_status': compute_state_status(session),
        'stats': build_statistics(session, duration_hint=duration_hint),
        'timeline_buckets': build_timeline_buckets(session, duration_hint=duration_hint),
        'synced_videos': [
            {
                'id': link.video_id,
                'title': link.video.title,
                'url': link.video.file.url,
                'sort_order': link.sort_order,
            }
            for link in session.video_links.select_related('video').order_by('sort_order', 'pk')
        ],
    })


@login_required
@require_POST
def event_create_api(request, pk: int):
    session = get_accessible_session(request.user, pk)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': f'JSON invalide: {exc}'}, status=400)

    behavior_id = payload.get('behavior_id')
    timestamp_raw = payload.get('timestamp_seconds')
    comment = (payload.get('comment') or '').strip()
    explicit_kind = payload.get('event_kind')
    modifier_ids = payload.get('modifier_ids') or []

    behavior = get_object_or_404(Behavior, pk=behavior_id, project=session.project)

    try:
        timestamp_seconds = Decimal(str(timestamp_raw))
    except (InvalidOperation, TypeError):
        return JsonResponse({'error': 'timestamp_seconds invalide.'}, status=400)

    if not isinstance(modifier_ids, list):
        return JsonResponse({'error': 'modifier_ids doit être une liste.'}, status=400)

    try:
        normalized_modifier_ids = [int(value) for value in modifier_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': 'modifier_ids invalide.'}, status=400)

    modifiers = list(Modifier.objects.filter(project=session.project, pk__in=normalized_modifier_ids))
    if {modifier.pk for modifier in modifiers} != set(normalized_modifier_ids):
        return JsonResponse({'error': 'Un ou plusieurs modificateurs sont invalides.'}, status=400)

    event = ObservationEvent.objects.create(
        session=session,
        behavior=behavior,
        event_kind=resolve_event_kind(session, behavior, explicit_kind),
        timestamp_seconds=timestamp_seconds,
        comment=comment,
    )
    if modifiers:
        event.modifiers.set(modifiers)

    return JsonResponse({'event': serialize_event(event), 'state_status': compute_state_status(session)}, status=201)


@login_required
@require_POST
def event_update_api(request, pk: int):
    event = get_object_or_404(ObservationEvent.objects.select_related('session__project', 'behavior'), pk=pk)
    session = get_accessible_session(request.user, event.session_id)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError as exc:
        return JsonResponse({'error': f'JSON invalide: {exc}'}, status=400)

    behavior_id = payload.get('behavior_id', event.behavior_id)
    behavior = get_object_or_404(Behavior, pk=behavior_id, project=session.project)

    try:
        timestamp_seconds = Decimal(str(payload.get('timestamp_seconds', event.timestamp_seconds)))
    except (InvalidOperation, TypeError):
        return JsonResponse({'error': 'timestamp_seconds invalide.'}, status=400)

    modifier_ids = payload.get('modifier_ids', list(event.modifiers.values_list('id', flat=True)))
    if not isinstance(modifier_ids, list):
        return JsonResponse({'error': 'modifier_ids doit être une liste.'}, status=400)

    try:
        normalized_modifier_ids = [int(value) for value in modifier_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': 'modifier_ids invalide.'}, status=400)

    modifiers = list(Modifier.objects.filter(project=session.project, pk__in=normalized_modifier_ids))
    if {modifier.pk for modifier in modifiers} != set(normalized_modifier_ids):
        return JsonResponse({'error': 'Un ou plusieurs modificateurs sont invalides.'}, status=400)

    explicit_kind = payload.get('event_kind', event.event_kind)
    if behavior.mode == Behavior.MODE_POINT:
        explicit_kind = ObservationEvent.KIND_POINT
    elif explicit_kind not in {ObservationEvent.KIND_START, ObservationEvent.KIND_STOP}:
        return JsonResponse({'error': "event_kind invalide pour un comportement d'état."}, status=400)

    event.behavior = behavior
    event.event_kind = explicit_kind
    event.timestamp_seconds = timestamp_seconds
    event.comment = (payload.get('comment') or '').strip()
    event.save(update_fields=['behavior', 'event_kind', 'timestamp_seconds', 'comment'])
    event.modifiers.set(modifiers)

    return JsonResponse({'event': serialize_event(event), 'state_status': compute_state_status(session)})


@login_required
@require_POST
def event_delete_api(request, pk: int):
    event = get_object_or_404(ObservationEvent.objects.select_related('session__project'), pk=pk)
    project_ids = set(accessible_projects_qs(request.user).values_list('id', flat=True))
    if event.session.project_id not in project_ids:
        raise Http404('Événement introuvable.')
    session = get_accessible_session(request.user, event.session_id)
    event.delete()
    return JsonResponse({'ok': True, 'state_status': compute_state_status(session)})


@login_required
def session_export_csv(request, pk: int):
    session = get_accessible_session(request.user, pk)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.csv"'
    response.write('﻿')

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
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
        'modifiers',
        'comment',
        'created_at',
    ])
    for row in _event_rows(session):
        writer.writerow(row)
    return response


@login_required
def session_export_json(request, pk: int):
    session = get_accessible_session(request.user, pk)
    payload = {
        'project': session.project.name,
        'session': session.title,
        'video': session.video.title,
        'synced_videos': [video.title for video in session.all_videos_ordered],
        'observer': session.observer.username if session.observer else None,
        'statistics': build_statistics(session),
        'timeline_buckets': build_timeline_buckets(session),
        'events': [serialize_event(event) for event in session.events.all()],
    }
    response = HttpResponse(json.dumps(payload, indent=2, ensure_ascii=False), content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.json"'
    return response


@login_required
def session_export_xlsx(request, pk: int):
    session = get_accessible_session(request.user, pk)
    workbook = Workbook()

    events_sheet = workbook.active
    events_sheet.title = 'Events'
    event_headers = [
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
    events_sheet.append(event_headers)
    for row in _event_rows(session):
        events_sheet.append(row)

    stats = build_statistics(session)
    stats_sheet = workbook.create_sheet('Summary')
    stats_sheet.append(['Session', session.title])
    stats_sheet.append(['Observed span seconds', stats['observed_span_seconds']])
    stats_sheet.append(['Event count', stats['session_event_count']])
    stats_sheet.append(['Point count', stats['point_event_count']])
    stats_sheet.append(['Open state count', stats['open_state_count']])
    stats_sheet.append(['State duration seconds', stats['state_duration_seconds']])
    stats_sheet.append(['Synced videos', ', '.join(video.title for video in session.all_videos_ordered)])
    stats_sheet.append([])
    stats_sheet.append([
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
    ])
    for row in stats['rows']:
        stats_sheet.append([
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
        ])

    buckets_sheet = workbook.create_sheet('Timeline')
    buckets_sheet.append(['Start seconds', 'End seconds', 'Events', 'Point events', 'State changes', 'Top labels'])
    for bucket in build_timeline_buckets(session):
        top_labels = ', '.join(f'{name} ({count})' for name, count in bucket['labels'].items())
        buckets_sheet.append([
            bucket['start_seconds'],
            bucket['end_seconds'],
            bucket['event_count'],
            bucket['point_count'],
            bucket['state_change_count'],
            top_labels,
        ])

    _autosize_workbook(workbook)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="session_{session.pk}_events.xlsx"'
    workbook.save(response)
    return response
