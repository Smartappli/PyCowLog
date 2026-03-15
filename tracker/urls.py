from django.urls import path

from . import views

app_name = 'tracker'

urlpatterns = [
    path('', views.home, name='home'),
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/settings/', views.project_update, name='project_update'),
    path('projects/<int:pk>/analytics/', views.project_analytics, name='project_analytics'),
    path('projects/<int:pk>/analytics/xlsx/', views.project_export_xlsx, name='project_export_xlsx'),
    path('projects/<int:pk>/ethogram/export/', views.project_export_ethogram, name='project_export_ethogram'),
    path('projects/<int:pk>/ethogram/import/', views.project_import_ethogram, name='project_import_ethogram'),
    path('projects/<int:pk>/categories/new/', views.category_create, name='category_create'),
    path('projects/<int:pk>/modifiers/new/', views.modifier_create, name='modifier_create'),
    path('projects/<int:pk>/behaviors/new/', views.behavior_create, name='behavior_create'),
    path('projects/<int:pk>/videos/new/', views.video_create, name='video_create'),
    path('projects/<int:pk>/sessions/new/', views.session_create, name='session_create'),
    path('categories/<int:pk>/edit/', views.category_update, name='category_update'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('modifiers/<int:pk>/edit/', views.modifier_update, name='modifier_update'),
    path('modifiers/<int:pk>/delete/', views.modifier_delete, name='modifier_delete'),
    path('behaviors/<int:pk>/edit/', views.behavior_update, name='behavior_update'),
    path('behaviors/<int:pk>/delete/', views.behavior_delete, name='behavior_delete'),
    path('videos/<int:pk>/edit/', views.video_update, name='video_update'),
    path('videos/<int:pk>/delete/', views.video_delete, name='video_delete'),
    path('sessions/<int:pk>/', views.session_player, name='session_player'),
    path('sessions/<int:pk>/edit/', views.session_update, name='session_update'),
    path('sessions/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('sessions/<int:pk>/events/', views.session_events_json, name='session_events_json'),
    path('sessions/<int:pk>/events/add/', views.event_create_api, name='event_create_api'),
    path('events/<int:pk>/update/', views.event_update_api, name='event_update_api'),
    path('events/<int:pk>/delete/', views.event_delete_api, name='event_delete_api'),
    path('sessions/<int:pk>/export/csv/', views.session_export_csv, name='session_export_csv'),
    path('sessions/<int:pk>/export/json/', views.session_export_json, name='session_export_json'),
    path('sessions/<int:pk>/export/xlsx/', views.session_export_xlsx, name='session_export_xlsx'),
]
