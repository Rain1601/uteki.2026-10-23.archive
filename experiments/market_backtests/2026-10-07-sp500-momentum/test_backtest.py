"""Hand-calculated checks for the frozen momentum experiment's arithmetic."""

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest import adjusted_open, portfolio_nav, select_groups, total_return


class BacktestArithmeticTests(unittest.TestCase):
    def test_total_return_uses_ratio_and_preserves_losses(self):
        self.assertAlmostEqual(total_return(100.0, 125.0), 0.25)
        self.assertAlmostEqual(total_return(80.0, 60.0), -0.25)

    def test_adjusted_open_uses_the_same_scale_as_adjusted_close(self):
        # A 0.5 adjustment factor converts the actual $100 entry to $50.
        bar = {"open": 100.0, "close": 110.0, "adjclose": 55.0}
        entry = adjusted_open(bar)
        self.assertAlmostEqual(entry, 50.0)
        nav = portfolio_nav({"A": {"2026-01-02": 55.0}}, {"A": entry})
        # Opening purchase captures the first trading day's 10% gain.
        self.assertAlmostEqual(nav["2026-01-02"], 1.10)

    def test_initial_equal_weight_hold_does_not_rebalance_each_day(self):
        paths = {
            "A": {"2026-01-02": 200.0, "2026-01-05": 100.0},
            "B": {"2026-01-02": 50.0, "2026-01-05": 100.0},
        }
        nav = portfolio_nav(paths, {"A": 100.0, "B": 100.0})
        self.assertAlmostEqual(nav["2026-01-02"], 1.25)
        self.assertAlmostEqual(nav["2026-01-05"], 1.00)
        # Daily equal-weight rebalancing would instead finish at 1.5625.
        self.assertNotAlmostEqual(nav["2026-01-05"], 1.5625)

    def test_one_missing_stock_date_is_not_silently_dropped(self):
        paths = {
            "A": {"2026-01-02": 100.0, "2026-01-05": 110.0},
            "B": {"2026-01-02": 100.0},
        }
        with self.assertRaises(ValueError):
            portfolio_nav(paths, {"A": 100.0, "B": 100.0})

    def test_equal_length_paths_with_different_dates_are_rejected(self):
        paths = {
            "A": {"2026-01-02": 100.0, "2026-01-05": 110.0},
            "B": {"2026-01-02": 100.0, "2026-01-06": 120.0},
        }
        with self.assertRaises(ValueError):
            portfolio_nav(paths, {"A": 100.0, "B": 100.0})

    def test_odd_universe_rounds_top_half_up_and_preserves_every_rank(self):
        # Deliberately not alphabetical: the caller's ranking is authoritative.
        ranked = ["E", "C", "A", "D", "B"]
        original = list(ranked)
        groups = select_groups(ranked, top_n=2, fraction=0.5)
        self.assertEqual(groups["top_n"], ["E", "C"])
        self.assertEqual(groups["top_half"], ["E", "C", "A"])
        self.assertEqual(groups["bottom_half"], ["D", "B"])
        self.assertEqual(groups["all_rankable"], original)
        self.assertEqual(groups["top_half"] + groups["bottom_half"], original)
        self.assertTrue(set(groups["top_half"]).isdisjoint(groups["bottom_half"]))
        self.assertEqual(ranked, original)


if __name__ == "__main__":
    unittest.main()
