from django.test import SimpleTestCase

from apps.analytics.services import _unwrap_bitrix_scalar, measure_datetime_from_deal


class BitrixFieldHelpersTests(SimpleTestCase):
    def test_unwrap_scalar_from_list(self):
        self.assertEqual(_unwrap_bitrix_scalar(["21"]), "21")
        self.assertEqual(_unwrap_bitrix_scalar([["21"]]), "21")
        self.assertIsNone(_unwrap_bitrix_scalar([]))
        self.assertIsNone(_unwrap_bitrix_scalar(None))
        self.assertIsNone(_unwrap_bitrix_scalar(""))
        self.assertIsNone(_unwrap_bitrix_scalar("0"))

    def test_measure_datetime_prefers_ro_field(self):
        raw = {
            "CATEGORY_ID": "5",
            "UF_CRM_1759323130": "2026-07-01T10:00:00+03:00",
            "UF_CRM_1784883397748": "2026-07-02T11:00:00+03:00",
        }
        value = measure_datetime_from_deal(raw)
        self.assertIsNotNone(value)
        self.assertEqual(value.day, 2)

    def test_measure_datetime_fallback_to_default(self):
        raw = {
            "CATEGORY_ID": "5",
            "UF_CRM_1759323130": "2026-07-01T10:00:00+03:00",
            "UF_CRM_1784883397748": None,
        }
        value = measure_datetime_from_deal(raw)
        self.assertIsNotNone(value)
        self.assertEqual(value.day, 1)
