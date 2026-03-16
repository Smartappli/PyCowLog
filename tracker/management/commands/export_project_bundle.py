from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Project
from tracker.views import build_reproducibility_bundle


class Command(BaseCommand):
    help = "Export a PyBehaviorLog reproducibility bundle for a project."

    def add_arguments(self, parser):
        parser.add_argument('project_id', type=int)
        parser.add_argument('--output', type=Path, required=True)

    def handle(self, *args, **options):
        try:
            project = Project.objects.select_related('owner').get(pk=options['project_id'])
        except Project.DoesNotExist as exc:
            raise CommandError('Project not found.') from exc

        output: Path = options['output']
        output.parent.mkdir(parents=True, exist_ok=True)
        bundle = build_reproducibility_bundle(project)

        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in bundle.items():
                archive.writestr(name, content)
        output.write_bytes(buffer.getvalue())
        self.stdout.write(self.style.SUCCESS(f'Bundle written to {output}'))
