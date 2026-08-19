from django.db import migrations


def create_direction_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    group_names = [
        "dashboard_director",
        "dashboard_manager",
        "dashboard_admin",
        "dashboard_panorama",
        "dashboard_ro",
    ]
    for name in group_names:
        Group.objects.get_or_create(name=name)


def reverse_direction_groups(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0012_alter_businessdirection_options_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_direction_groups, reverse_code=reverse_direction_groups),
    ]
