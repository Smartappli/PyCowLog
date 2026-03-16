from django.db import migrations


def forwards(apps, schema_editor):
    Project = apps.get_model('tracker', 'Project')
    ProjectMembership = apps.get_model('tracker', 'ProjectMembership')

    through = Project.collaborators.through
    existing = set(
        ProjectMembership.objects.values_list('project_id', 'user_id')
    )

    memberships = []
    for project in Project.objects.all().iterator():
        owner_key = (project.id, project.owner_id)
        if owner_key not in existing:
            memberships.append(
                ProjectMembership(
                    project_id=project.id,
                    user_id=project.owner_id,
                    role='owner',
                )
            )
            existing.add(owner_key)

    ProjectMembership.objects.bulk_create(memberships, ignore_conflicts=True)

    editor_memberships = []
    collaborator_rows = through.objects.all().values_list('project_id', 'user_id')
    for project_id, user_id in collaborator_rows.iterator():
        key = (project_id, user_id)
        if key not in existing:
            editor_memberships.append(
                ProjectMembership(
                    project_id=project_id,
                    user_id=user_id,
                    role='editor',
                )
            )
            existing.add(key)

    ProjectMembership.objects.bulk_create(editor_memberships, ignore_conflicts=True)


def backwards(apps, schema_editor):
    ProjectMembership = apps.get_model('tracker', 'ProjectMembership')
    ProjectMembership.objects.filter(role__in=['owner', 'editor']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0005_keyboardprofile_observationsession_keyboard_profile_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
