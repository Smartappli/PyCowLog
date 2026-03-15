# Generated manually for the CowLog Django V4 starter project.

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BehaviorCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('color', models.CharField(default='#0f766e', max_length=7)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('collaborators', models.ManyToManyField(blank=True, related_name='shared_cowlog_projects', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='owned_cowlog_projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='behaviorcategory',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='categories', to='tracker.project'),
        ),
        migrations.CreateModel(
            name='Modifier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('key_binding', models.CharField(max_length=1)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='modifiers', to='tracker.project')),
            ],
            options={
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Behavior',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('key_binding', models.CharField(max_length=1)),
                ('color', models.CharField(default='#2563eb', max_length=7)),
                ('mode', models.CharField(choices=[('point', 'Point'), ('state', 'State')], default='point', max_length=10)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='behaviors', to='tracker.behaviorcategory')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='behaviors', to='tracker.project')),
            ],
            options={
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='VideoAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('file', models.FileField(upload_to='videos/')),
                ('notes', models.TextField(blank=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='videos', to='tracker.project')),
            ],
            options={
                'ordering': ['title', '-uploaded_at'],
            },
        ),
        migrations.CreateModel(
            name='ObservationSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('playback_rate', models.DecimalField(decimal_places=2, default=1.0, max_digits=4, validators=[django.core.validators.MinValueValidator(0.25), django.core.validators.MaxValueValidator(4.0)])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('observer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cowlog_sessions', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='tracker.project')),
                ('video', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='tracker.videoasset')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SessionVideoLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='video_links', to='tracker.observationsession')),
                ('video', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='session_links', to='tracker.videoasset')),
            ],
            options={
                'ordering': ['sort_order', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='ObservationEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_kind', models.CharField(choices=[('point', 'Point'), ('start', 'Start'), ('stop', 'Stop')], max_length=10)),
                ('timestamp_seconds', models.DecimalField(decimal_places=3, max_digits=10)),
                ('comment', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('behavior', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='tracker.behavior')),
                ('modifiers', models.ManyToManyField(blank=True, related_name='events', to='tracker.modifier')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='tracker.observationsession')),
            ],
            options={
                'ordering': ['timestamp_seconds', 'pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.UniqueConstraint(fields=('owner', 'name'), name='unique_project_name_per_owner'),
        ),
        migrations.AddConstraint(
            model_name='behaviorcategory',
            constraint=models.UniqueConstraint(fields=('project', 'name'), name='unique_category_name_per_project'),
        ),
        migrations.AddConstraint(
            model_name='modifier',
            constraint=models.UniqueConstraint(fields=('project', 'name'), name='unique_modifier_name_per_project'),
        ),
        migrations.AddConstraint(
            model_name='modifier',
            constraint=models.UniqueConstraint(fields=('project', 'key_binding'), name='unique_modifier_key_per_project'),
        ),
        migrations.AddConstraint(
            model_name='behavior',
            constraint=models.UniqueConstraint(fields=('project', 'name'), name='unique_behavior_name_per_project_v2'),
        ),
        migrations.AddConstraint(
            model_name='behavior',
            constraint=models.UniqueConstraint(fields=('project', 'key_binding'), name='unique_behavior_key_per_project_v2'),
        ),
        migrations.AddConstraint(
            model_name='videoasset',
            constraint=models.UniqueConstraint(fields=('project', 'title'), name='unique_video_title_per_project'),
        ),
        migrations.AddConstraint(
            model_name='sessionvideolink',
            constraint=models.UniqueConstraint(fields=('session', 'video'), name='unique_video_per_session'),
        ),
    ]
