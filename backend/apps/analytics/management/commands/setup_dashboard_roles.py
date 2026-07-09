from django.core.management.base import BaseCommand

from apps.analytics.roles import GROUP_DEFINITIONS, ensure_dashboard_groups


class Command(BaseCommand):
    help = "Создаёт группы ролей дашборда (director / manager / admin)."

    def handle(self, *args, **options):
        groups = ensure_dashboard_groups()
        self.stdout.write(self.style.SUCCESS("Группы ролей:"))
        for name, description in GROUP_DEFINITIONS.items():
            self.stdout.write(f"  • {name} — {description} (id={groups[name].id})")
        self.stdout.write("")
        self.stdout.write("Назначение роли пользователю:")
        self.stdout.write("  python manage.py shell -c \"from django.contrib.auth import get_user_model; from django.contrib.auth.models import Group; u=get_user_model().objects.get(username='USER'); u.groups.add(Group.objects.get(name='dashboard_director'))\"")
        self.stdout.write("")
        self.stdout.write("Для менеджера также привяжите CrmUser в админке: Профили дашборда.")
