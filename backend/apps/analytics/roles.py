"""Роли доступа к дашборду."""

from django.contrib.auth.models import Group

GROUP_DIRECTOR = "dashboard_director"
GROUP_MANAGER = "dashboard_manager"
GROUP_ADMIN = "dashboard_admin"
GROUP_PANORAMA = "dashboard_panorama"
GROUP_RO = "dashboard_ro"

GROUP_DEFINITIONS = {
    GROUP_DIRECTOR: "Руководитель — полный доступ ко всем данным дашборда",
    GROUP_MANAGER: "Менеджер — видит только свои показатели",
    GROUP_ADMIN: "Администратор — дашборд + техническая админка",
    GROUP_PANORAMA: "Панорама — доступ только к направлению Панорама",
    GROUP_RO: "Русские окна — доступ только к направлению Русские окна",
}


def ensure_dashboard_groups() -> dict[str, Group]:
    groups = {}
    for name, description in GROUP_DEFINITIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        groups[name] = group
    return groups


def user_in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=group_name).exists()


def user_is_admin(user) -> bool:
    return user.is_authenticated and (user.is_superuser or user.is_staff or user_in_group(user, GROUP_ADMIN))


def user_is_director(user) -> bool:
    return user.is_authenticated and (
        user.is_superuser or user_in_group(user, GROUP_DIRECTOR) or user_in_group(user, GROUP_ADMIN)
    )


def user_is_manager_only(user) -> bool:
    if not user.is_authenticated or user.is_superuser:
        return False
    if user_in_group(user, GROUP_DIRECTOR) or user_in_group(user, GROUP_ADMIN):
        return False
    return user_in_group(user, GROUP_MANAGER)


def get_linked_crm_user(user):
    profile = getattr(user, "dashboard_profile", None)
    if profile and profile.crm_user_id:
        return profile.crm_user
    return None


def resolve_manager_filters(user, manager_ids: list[int], exclude_manager_ids: list[int]) -> tuple[list[int], list[int]]:
    """Менеджер с ролью dashboard_manager видит только себя."""
    if not user_is_manager_only(user):
        return manager_ids, exclude_manager_ids

    crm_user = get_linked_crm_user(user)
    if not crm_user:
        return [-1], exclude_manager_ids
    return [crm_user.id], exclude_manager_ids


def can_force_sync(user) -> bool:
    return user_is_director(user) or user_is_admin(user)


def get_user_allowed_directions(user):
    from .models import BusinessDirection

    active_directions = BusinessDirection.objects.filter(is_active=True).exclude(code=BusinessDirection.Code.B2B)

    if not user or not user.is_authenticated:
        return active_directions.none()

    # Superusers, Admins, Directors have access to all directions
    if user.is_superuser or user_is_admin(user) or user_in_group(user, GROUP_DIRECTOR):
        return active_directions

    # Explicit allowed directions on user profile
    profile = getattr(user, "dashboard_profile", None)
    if profile and profile.pk and profile.allowed_directions.exists():
        return profile.allowed_directions.filter(is_active=True).exclude(code=BusinessDirection.Code.B2B)

    # Group-based direction restrictions
    is_panorama = user_in_group(user, GROUP_PANORAMA)
    is_ro = user_in_group(user, GROUP_RO)

    if is_panorama and not is_ro:
        return active_directions.filter(code=BusinessDirection.Code.PANORAMA)
    if is_ro and not is_panorama:
        return active_directions.filter(code=BusinessDirection.Code.RO)

    return active_directions

