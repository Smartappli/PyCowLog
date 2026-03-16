from django.urls import path

from . import views

app_name = 'tracker'

urlpatterns = [
    path('health/', views.healthcheck, name='healthcheck'),
    path('release.json', views.release_metadata_json, name='release_metadata_json'),
    path('', views.home, name='home'),
    path('projects/import/', views.project_import_create, name='project_import_create'),
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/settings/', views.project_update, name='project_update'),
    path('projects/<int:pk>/clone/', views.project_clone, name='project_clone'),
    path('projects/<int:pk>/analytics/', views.project_analytics, name='project_analytics'),
    path(
        'projects/<int:pk>/analytics/xlsx/', views.project_export_xlsx, name='project_export_xlsx'
    ),
    path(
        'projects/<int:pk>/export/bundle/', views.project_export_bundle, name='project_export_bundle'
    ),
    path(
        'projects/<int:pk>/export/boris-json/', views.project_export_boris_json, name='project_export_boris_json'
    ),
    path(
        'projects/<int:pk>/export/compatibility-report/',
        views.project_export_compatibility_report,
        name='project_export_compatibility_report',
    ),
    path(
        'projects/<int:pk>/import/boris-project/',
        views.project_import_boris_json,
        name='project_import_boris_json',
    ),
    path(
        'projects/<int:pk>/ethogram/export/',
        views.project_export_ethogram,
        name='project_export_ethogram',
    ),
    path(
        'projects/<int:pk>/ethogram/import/',
        views.project_import_ethogram,
        name='project_import_ethogram',
    ),
    path('projects/<int:pk>/categories/new/', views.category_create, name='category_create'),
    path('projects/<int:pk>/modifiers/new/', views.modifier_create, name='modifier_create'),
    path(
        'projects/<int:pk>/subject-groups/new/',
        views.subject_group_create,
        name='subject_group_create',
    ),
    path('projects/<int:pk>/subjects/new/', views.subject_create, name='subject_create'),
    path(
        'projects/<int:pk>/variables/new/',
        views.independent_variable_create,
        name='independent_variable_create',
    ),
    path(
        'projects/<int:pk>/templates/new/',
        views.observation_template_create,
        name='observation_template_create',
    ),
    path('projects/<int:pk>/behaviors/new/', views.behavior_create, name='behavior_create'),
    path('projects/<int:pk>/videos/new/', views.video_create, name='video_create'),
    path('projects/<int:pk>/sessions/new/', views.session_create, name='session_create'),
    path('projects/<int:pk>/memberships/new/', views.project_membership_create, name='project_membership_create'),
    path('memberships/<int:pk>/edit/', views.project_membership_update, name='project_membership_update'),
    path('memberships/<int:pk>/delete/', views.project_membership_delete, name='project_membership_delete'),
    path('projects/<int:pk>/keyboard-profiles/new/', views.keyboard_profile_create, name='keyboard_profile_create'),
    path('keyboard-profiles/<int:pk>/edit/', views.keyboard_profile_update, name='keyboard_profile_update'),
    path('keyboard-profiles/<int:pk>/delete/', views.keyboard_profile_delete, name='keyboard_profile_delete'),
    path('categories/<int:pk>/edit/', views.category_update, name='category_update'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('modifiers/<int:pk>/edit/', views.modifier_update, name='modifier_update'),
    path('modifiers/<int:pk>/delete/', views.modifier_delete, name='modifier_delete'),
    path('subject-groups/<int:pk>/edit/', views.subject_group_update, name='subject_group_update'),
    path(
        'subject-groups/<int:pk>/delete/', views.subject_group_delete, name='subject_group_delete'
    ),
    path('subjects/<int:pk>/edit/', views.subject_update, name='subject_update'),
    path('subjects/<int:pk>/delete/', views.subject_delete, name='subject_delete'),
    path(
        'variables/<int:pk>/edit/',
        views.independent_variable_update,
        name='independent_variable_update',
    ),
    path(
        'variables/<int:pk>/delete/',
        views.independent_variable_delete,
        name='independent_variable_delete',
    ),
    path(
        'templates/<int:pk>/edit/',
        views.observation_template_update,
        name='observation_template_update',
    ),
    path(
        'templates/<int:pk>/delete/',
        views.observation_template_delete,
        name='observation_template_delete',
    ),
    path('behaviors/<int:pk>/edit/', views.behavior_update, name='behavior_update'),
    path('behaviors/<int:pk>/delete/', views.behavior_delete, name='behavior_delete'),
    path('videos/<int:pk>/edit/', views.video_update, name='video_update'),
    path('videos/<int:pk>/delete/', views.video_delete, name='video_delete'),
    path('sessions/<int:pk>/', views.session_player, name='session_player'),
    path('sessions/<int:pk>/edit/', views.session_update, name='session_update'),
    path('sessions/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('sessions/<int:pk>/import/json/', views.session_import_json, name='session_import_json'),
    path(
        'sessions/<int:pk>/workflow/', views.session_workflow_action, name='session_workflow_action'
    ),
    path('sessions/<int:pk>/audit/', views.session_audit_json, name='session_audit_json'),
    path('sessions/<int:pk>/events/', views.session_events_json, name='session_events_json'),
    path('sessions/<int:pk>/media-analysis/', views.session_media_analysis_json, name='session_media_analysis_json'),
    path('sessions/<int:pk>/undo/', views.session_undo_api, name='session_undo_api'),
    path('sessions/<int:pk>/redo/', views.session_redo_api, name='session_redo_api'),
    path('sessions/<int:pk>/events/add/', views.event_create_api, name='event_create_api'),
    path('events/<int:pk>/update/', views.event_update_api, name='event_update_api'),
    path('events/<int:pk>/delete/', views.event_delete_api, name='event_delete_api'),
    path(
        'sessions/<int:pk>/annotations/add/',
        views.annotation_create_api,
        name='annotation_create_api',
    ),
    path('annotations/<int:pk>/update/', views.annotation_update_api, name='annotation_update_api'),
    path('annotations/<int:pk>/delete/', views.annotation_delete_api, name='annotation_delete_api'),
    path('sessions/<int:pk>/export/compatibility-report/', views.session_export_compatibility_report, name='session_export_compatibility_report'),
    path('sessions/<int:pk>/export/cowlog-txt/', views.session_export_cowlog_txt, name='session_export_cowlog_txt'),
    path('sessions/<int:pk>/export/html/', views.session_export_html, name='session_export_html'),
    path('sessions/<int:pk>/export/sql/', views.session_export_sql, name='session_export_sql'),
    path('sessions/<int:pk>/export/behavioral-sequences/', views.session_export_behavioral_sequences, name='session_export_behavioral_sequences'),
    path('sessions/<int:pk>/export/textgrid/', views.session_export_textgrid, name='session_export_textgrid'),
    path('sessions/<int:pk>/export/binary-table/', views.session_export_binary_table_tsv, name='session_export_binary_table_tsv'),
    path('sessions/<int:pk>/export/csv/', views.session_export_csv, name='session_export_csv'),
    path('sessions/<int:pk>/export/tsv/', views.session_export_tsv, name='session_export_tsv'),
    path('sessions/<int:pk>/export/json/', views.session_export_json, name='session_export_json'),
    path(
        'sessions/<int:pk>/export/boris-json/',
        views.session_export_boris_json,
        name='session_export_boris_json',
    ),
    path('sessions/<int:pk>/export/xlsx/', views.session_export_xlsx, name='session_export_xlsx'),
]
