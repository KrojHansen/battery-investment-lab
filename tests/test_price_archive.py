"""Offline tests for the historical price archive builder."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.update_price_archive import requested_chunks


class ArchivePlanningTests(unittest.TestCase):
    def test_backfill_has_correct_hourly_and_quarter_hourly_blocks(self):
        chunks = requested_chunks("backfill", 2016, date(2026, 11, 5))
        self.assertEqual(len(chunks), 23)
        old = [c for c in chunks if c[0] == "Elspotprices"]
        new = [c for c in chunks if c[0] == "DayAheadPrices"]
        self.assertEqual(len(old), 10)
        self.assertEqual(len(new), 13)
        self.assertEqual(old[-1][3:], (date(2025, 1, 1), date(2025, 10, 1)))
        self.assertEqual(new[0][3:], (date(2025, 10, 1), date(2025, 11, 1)))
        self.assertEqual(new[-1][3:], (date(2026, 10, 1), date(2026, 11, 1)))

    def test_monthly_never_uses_current_incomplete_month(self):
        self.assertEqual(
            requested_chunks("monthly", 2016, date(2026, 11, 5))[0][3:],
            (date(2026, 10, 1), date(2026, 11, 1)),
        )
        self.assertEqual(
            requested_chunks("monthly", 2016, date(2025, 10, 2))[0][3:],
            (date(2025, 1, 1), date(2025, 10, 1)),
        )

    def test_leap_year_and_dst_are_validated_by_existing_loader(self):
        from scripts.update_price_archive import validate_cached
        p = Path(__file__).resolve().parents[1] / "data_cache/energy_prices_v2/Elspotprices_DK1_2024.csv"
        if p.exists():
            self.assertTrue(validate_cached("Elspotprices", "DK1", 2024, 1, date(2024, 1, 1), date(2025, 1, 1)))


if __name__ == "__main__":
    unittest.main()
