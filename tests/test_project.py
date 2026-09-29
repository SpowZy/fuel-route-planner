from django.core.management import call_command


def test_project_passes_django_system_checks():
    call_command("check")
