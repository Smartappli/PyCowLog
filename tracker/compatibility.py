from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _normalize_time(value: Any) -> float:
    try:
        return round(float(Decimal(str(value))), 3)
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split('|') if item.strip()]
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict):
                values.append(str(item.get('name') or item.get('label') or key))
            elif item:
                values.append(str(key))
        return sorted({item for item in values if item})
    if isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                values.append(str(item.get('name') or item.get('label') or ''))
            else:
                values.append(str(item))
        return sorted({item for item in values if item})
    return [str(value)]


def _resolve_event_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    schema = payload.get('schema', '')
    if schema in {
        'cowlog-results-v1',
        'pybehaviorlog-0.9-session',
        'pybehaviorlog-0.8.3-session',
        'pybehaviorlog-0.8-session',
        'boris-tabular-csv-v1',
        'boris-tabular-tsv-v1',
        'boris-tabular-xlsx-v1',
        'boris-tabular-spreadsheet-v2',
    }:
        return [item for item in payload.get('events', []) if isinstance(item, dict)]
    observations = payload.get('observations')
    if isinstance(observations, dict):
        observations = list(observations.values())
    if isinstance(observations, list) and observations:
        first = observations[0]
        if isinstance(first, dict):
            return [item for item in first.get('events', []) if isinstance(item, dict)]
    if isinstance(payload.get('events'), list):
        return [item for item in payload['events'] if isinstance(item, dict)]
    return []


def _resolve_annotation_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get('schema', '').startswith('pybehaviorlog-'):
        return [item for item in payload.get('annotations', []) if isinstance(item, dict)]
    observations = payload.get('observations')
    if isinstance(observations, dict):
        observations = list(observations.values())
    if isinstance(observations, list) and observations:
        first = observations[0]
        if isinstance(first, dict):
            return [item for item in first.get('annotations', []) if isinstance(item, dict)]
    return []


def normalize_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize BORIS / PyBehaviorLog / CowLog session-like payloads for round-trip checks."""
    events = []
    for item in _resolve_event_items(payload):
        behavior = (
            item.get('behavior')
            or item.get('code')
            or item.get('behavior_code')
            or item.get('event')
            or ''
        )
        event_kind = str(item.get('event_kind') or item.get('type') or 'point').lower()
        events.append(
            {
                'time': _normalize_time(item.get('time') or item.get('timestamp_seconds') or item.get('start')),
                'behavior': str(behavior),
                'event_kind': event_kind,
                'modifiers': _string_list(item.get('modifiers')),
                'subjects': _string_list(item.get('subjects') or item.get('subject')),
                'comment': str(item.get('comment') or item.get('comment_start') or item.get('image_path') or ''),
                'frame_index': int(item.get('frame_index') or item.get('frame') or 0) if str(item.get('frame_index') or item.get('frame') or '').strip() else None,
            }
        )
    events.sort(key=lambda item: (item['time'], item['behavior'], item['event_kind']))
    annotations = []
    for item in _resolve_annotation_items(payload):
        annotations.append(
            {
                'time': _normalize_time(item.get('timestamp_seconds') or item.get('time')),
                'text': str(item.get('text') or item.get('note') or ''),
            }
        )
    annotations.sort(key=lambda item: (item['time'], item['text']))
    variables = payload.get('variables') or payload.get('independent_variables') or {}
    if not isinstance(variables, dict):
        variables = {}
    return {
        'schema_family': str(payload.get('schema') or 'unknown'),
        'events': events,
        'annotations': annotations,
        'variables': {str(key): str(value) for key, value in sorted(variables.items())},
        'media_paths': sorted(_string_list(payload.get('media_paths') or payload.get('image_paths'))),
    }


def compare_session_payloads(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Compare two normalized session payloads and return a compact diff report."""
    expected_normalized = normalize_session_payload(expected)
    actual_normalized = normalize_session_payload(actual)
    mismatches: list[str] = []
    if expected_normalized['events'] != actual_normalized['events']:
        mismatches.append('events')
    if expected_normalized['annotations'] != actual_normalized['annotations']:
        mismatches.append('annotations')
    if expected_normalized['variables'] != actual_normalized['variables']:
        mismatches.append('variables')
    if expected_normalized.get('media_paths') != actual_normalized.get('media_paths'):
        mismatches.append('media_paths')
    return {
        'equivalent': not mismatches,
        'mismatches': mismatches,
        'expected': expected_normalized,
        'actual': actual_normalized,
    }


def normalize_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize project-like payloads for BORIS/PyBehaviorLog round-trip comparisons."""
    def _item_names(value: Any, *, key: str = 'name', fallback: str = 'label') -> list[str]:
        results = []
        if isinstance(value, dict):
            iterator = value.values()
        elif isinstance(value, list):
            iterator = value
        else:
            iterator = []
        for item in iterator:
            if isinstance(item, dict):
                results.append(str(item.get(key) or item.get(fallback) or ''))
            else:
                results.append(str(item))
        return sorted(item for item in results if item)

    sessions = payload.get('sessions') or payload.get('observations') or []
    if isinstance(sessions, dict):
        sessions = list(sessions.values())
    session_titles = []
    for item in sessions:
        if not isinstance(item, dict):
            continue
        if item.get('title') or item.get('description'):
            session_titles.append(str(item.get('title') or item.get('description') or ''))
            continue
        observations = item.get('observations')
        if isinstance(observations, dict):
            observations = list(observations.values())
        if isinstance(observations, list):
            for observation in observations:
                if isinstance(observation, dict):
                    session_titles.append(str(observation.get('title') or observation.get('description') or ''))
    return {
        'schema_family': str(payload.get('schema') or 'unknown'),
        'categories': _item_names(payload.get('categories')),
        'behaviors': _item_names(payload.get('behaviors')),
        'modifiers': _item_names(payload.get('modifiers')),
        'subject_groups': _item_names(payload.get('subject_groups')),
        'subjects': _item_names(payload.get('subjects')),
        'variables': _item_names(payload.get('variables') or payload.get('independent_variables'), key='label', fallback='name'),
        'templates': _item_names(payload.get('observation_templates')),
        'sessions': sorted(item for item in session_titles if item),
    }


def compare_project_payloads(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_normalized = normalize_project_payload(expected)
    actual_normalized = normalize_project_payload(actual)
    mismatches = [
        key
        for key in ('categories', 'behaviors', 'modifiers', 'subject_groups', 'subjects', 'variables', 'templates', 'sessions')
        if expected_normalized[key] != actual_normalized[key]
    ]
    return {
        'equivalent': not mismatches,
        'mismatches': mismatches,
        'expected': expected_normalized,
        'actual': actual_normalized,
    }


def build_roundtrip_report(expected: dict[str, Any], actual: dict[str, Any], family: str) -> dict[str, Any]:
    """Build a machine-readable round-trip report for CI and fixture certification."""
    comparator = compare_project_payloads if family == 'project' else compare_session_payloads
    comparison = comparator(expected, actual)
    return {
        'family': family,
        'equivalent': comparison['equivalent'],
        'mismatches': comparison['mismatches'],
        'expected': comparison['expected'],
        'actual': comparison['actual'],
    }
