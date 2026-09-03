from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase, SimpleTestCase, override_settings

from .models import BusinessDirection, DashboardUserProfile
from .roles import (
    GROUP_ADMIN,
    GROUP_PANORAMA,
    GROUP_RO,
    get_user_allowed_directions,
)
from .services import contract_date_from_deal


BITRIX24_TEST_SETTINGS = {
    "DEAL_CONTRACT_DATE_FIELD": "UF_STANDARD_DATE",
    "RO_DEAL_CONTRACT_DATE_FIELD": "UF_RO_DATE",
    "RO_PIPELINE_ID": "5",
}


@override_settings(BITRIX24=BITRIX24_TEST_SETTINGS)
class ContractDateMappingTests(SimpleTestCase):
    def test_ro_deal_uses_ro_contract_date(self):
        raw = {
            "CATEGORY_ID": "5",
            "UF_STANDARD_DATE": "",
            "UF_RO_DATE": "2026-08-13T03:00:00+03:00",
        }
        self.assertEqual(contract_date_from_deal(raw), date(2026, 8, 13))

    def test_ro_deal_falls_back_to_standard_contract_date(self):
        raw = {
            "CATEGORY_ID": "5",
            "UF_STANDARD_DATE": "2026-08-14",
            "UF_RO_DATE": "",
        }
        self.assertEqual(contract_date_from_deal(raw), date(2026, 8, 14))

    def test_non_ro_deal_uses_standard_contract_date(self):
        raw = {
            "CATEGORY_ID": "0",
            "UF_STANDARD_DATE": "2026-08-15",
            "UF_RO_DATE": "2026-08-16",
        }
        self.assertEqual(contract_date_from_deal(raw), date(2026, 8, 15))


class DirectionRoleTests(TestCase):
    def setUp(self):
        self.panorama, _ = BusinessDirection.objects.get_or_create(code=BusinessDirection.Code.PANORAMA, defaults={"name": "Панорама"})
        self.ro, _ = BusinessDirection.objects.get_or_create(code=BusinessDirection.Code.RO, defaults={"name": "Русские окна"})
        self.b2b, _ = BusinessDirection.objects.get_or_create(code=BusinessDirection.Code.B2B, defaults={"name": "B2B", "is_active": False})

        self.group_panorama, _ = Group.objects.get_or_create(name=GROUP_PANORAMA)
        self.group_ro, _ = Group.objects.get_or_create(name=GROUP_RO)
        self.group_admin, _ = Group.objects.get_or_create(name=GROUP_ADMIN)


    def test_superuser_sees_all_active_directions(self):
        user = User.objects.create_superuser("admin", "admin@test.com", "pass")
        allowed = list(get_user_allowed_directions(user).values_list("code", flat=True))
        self.assertIn("panorama", allowed)
        self.assertIn("ro", allowed)
        self.assertNotIn("b2b", allowed)

    def test_panorama_group_sees_only_panorama(self):
        user = User.objects.create_user("p_user", "p@test.com", "pass")
        user.groups.add(self.group_panorama)
        allowed = list(get_user_allowed_directions(user).values_list("code", flat=True))
        self.assertEqual(allowed, ["panorama"])

    def test_ro_group_sees_only_ro(self):
        user = User.objects.create_user("ro_user", "ro@test.com", "pass")
        user.groups.add(self.group_ro)
        allowed = list(get_user_allowed_directions(user).values_list("code", flat=True))
        self.assertEqual(allowed, ["ro"])

    def test_user_profile_allowed_directions_override(self):
        user = User.objects.create_user("custom_user", "c@test.com", "pass")
        profile = DashboardUserProfile.objects.create(user=user)
        profile.allowed_directions.add(self.ro)
        allowed = list(get_user_allowed_directions(user).values_list("code", flat=True))
        self.assertEqual(allowed, ["ro"])

    def test_unassigned_user_has_no_directions(self):
        user = User.objects.create_user("plain_user", "plain@test.com", "pass")
        allowed = list(get_user_allowed_directions(user).values_list("code", flat=True))
        self.assertEqual(allowed, [])


class ReconciliationTests(TestCase):
    def test_reconcile_deleted_deals_removes_missing_deals(self):
        from django.utils import timezone
        from unittest.mock import MagicMock
        from .models import CrmDeal
        from .services import reconcile_deleted_deals

        now = timezone.now()
        # Create local deals
        deal1 = CrmDeal.objects.create(bitrix_id=100, title="Deal 100", created_time=now)
        deal2 = CrmDeal.objects.create(bitrix_id=101, title="Deal 101", created_time=now)
        deal_deleted = CrmDeal.objects.create(bitrix_id=999, title="Deleted Deal 999", created_time=now)


        # Mock client returning batch response with live IDs [100, 101]
        mock_client = MagicMock()
        mock_client.batch.return_value = {
            "result": {
                "c_0": [{"ID": "100"}, {"ID": "101"}]
            }
        }

        removed_count = reconcile_deleted_deals(mock_client)


        self.assertEqual(removed_count, 1)
        self.assertTrue(CrmDeal.objects.filter(bitrix_id=100).exists())
        self.assertTrue(CrmDeal.objects.filter(bitrix_id=101).exists())
        self.assertFalse(CrmDeal.objects.filter(bitrix_id=999).exists())



