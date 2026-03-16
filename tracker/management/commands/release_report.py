import json

from django.core.management.base import BaseCommand

from tracker.views import build_release_metadata


class Command(BaseCommand):
    help = "Print machine-readable release metadata for PyBehaviorLog."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(build_release_metadata(), indent=2, ensure_ascii=False))
