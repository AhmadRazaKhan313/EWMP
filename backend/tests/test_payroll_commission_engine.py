from decimal import Decimal

from app.services.payroll_commission import calculate_tiered_commission, CommissionTierData

TIERS = [
    CommissionTierData(Decimal("0"), Decimal("100000"), Decimal("2")),
    CommissionTierData(Decimal("100000"), Decimal("500000"), Decimal("5")),
    CommissionTierData(Decimal("500000"), None, Decimal("8")),
]


class TestTieredCommission:
    def test_sales_within_first_tier(self):
        assert calculate_tiered_commission(Decimal("50000"), TIERS) == Decimal("1000.00")

    def test_sales_spanning_two_tiers(self):
        # 300000: 2%*100000=2000, 5%*200000=10000 -> 12000
        assert calculate_tiered_commission(Decimal("300000"), TIERS) == Decimal("12000.00")

    def test_sales_spanning_all_three_tiers(self):
        assert calculate_tiered_commission(Decimal("600000"), TIERS) == Decimal("30000.00")

    def test_zero_sales_pays_zero(self):
        assert calculate_tiered_commission(Decimal("0"), TIERS) == Decimal("0.00")

    def test_negative_sales_pays_zero(self):
        assert calculate_tiered_commission(Decimal("-100"), TIERS) == Decimal("0.00")

    def test_no_tiers_configured_pays_zero(self):
        assert calculate_tiered_commission(Decimal("600000"), []) == Decimal("0.00")

    def test_flat_single_tier_acts_as_flat_rate(self):
        flat = [CommissionTierData(Decimal("0"), None, Decimal("3"))]
        assert calculate_tiered_commission(Decimal("100000"), flat) == Decimal("3000.00")
