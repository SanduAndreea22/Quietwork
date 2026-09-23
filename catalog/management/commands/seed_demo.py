from django.core.management.base import BaseCommand

from catalog.demo_content import ensure_demo_content


class Command(BaseCommand):
    help = "Create or refresh the Quietwork demo content (safe to run again)."

    def handle(self, *args, **options):
        ensure_demo_content(refresh=True)
        self.stdout.write(self.style.SUCCESS("Demo content ready."))
