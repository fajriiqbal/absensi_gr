from django.db import migrations


def promote_superusers(apps, schema_editor):
    UserGuru = apps.get_model("accounts", "UserGuru")
    UserGuru.objects.filter(is_superuser=True, role="guru").update(role="admin")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_userguru_managers"),
    ]

    operations = [
        migrations.RunPython(promote_superusers, migrations.RunPython.noop),
    ]