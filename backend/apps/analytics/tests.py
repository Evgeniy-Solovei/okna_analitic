from datetime import date

from django.test import SimpleTestCase, override_settings

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
