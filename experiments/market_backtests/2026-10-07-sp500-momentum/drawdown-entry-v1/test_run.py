"""Hand-calculated execution and calibration checks; no network or market data."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("drawdown_entry_run", Path(__file__).with_name("run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def bars_for(*rows):
    return {
        date: {"open": opening, "close": closing, "adjclose": closing}
        for date, opening, closing in rows
    }


class DrawdownEntryChecks(unittest.TestCase):
    def test_close_signal_fills_next_session_open_despite_gap(self):
        bars = bars_for(
            ("2026-01-02", 100, 95),
            ("2026-01-05", 95, 80),
            ("2026-01-06", 110, 121),
        )
        result = run.simulate_entry(bars, sorted(bars), 0.20, "year_open")
        self.assertEqual(result["signal"]["date"], "2026-01-05")
        self.assertEqual(result["fill"]["date"], "2026-01-06")
        self.assertEqual(result["fill"]["adjusted_open"], 110)
        self.assertEqual(result["nav"]["2026-01-05"], 1)
        self.assertAlmostEqual(result["return_total"], 0.10)

    def test_pullback_from_new_high_can_buy_above_year_open(self):
        bars = bars_for(
            ("2026-01-02", 100, 150),
            ("2026-01-05", 140, 120),
            ("2026-01-06", 125, 130),
        )
        moving = run.simulate_entry(bars, sorted(bars), 0.20, "running_peak")
        fixed = run.simulate_entry(bars, sorted(bars), 0.20, "year_open")
        self.assertEqual(moving["signal"]["anchor"], 150)
        self.assertEqual(moving["signal"]["date"], "2026-01-05")
        self.assertAlmostEqual(moving["entry_vs_year_open"], 0.25)
        self.assertEqual(fixed["status"], "no_signal")

    def test_no_signal_and_final_session_signal_keep_all_cash(self):
        for final_close, status in [(95, "no_signal"), (80, "signal_unfilled")]:
            with self.subTest(status=status):
                bars = bars_for(("2026-01-02", 100, 100), ("2026-10-06", 95, final_close))
                result = run.simulate_entry(bars, sorted(bars), 0.20, "year_open")
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["fill"])
                self.assertEqual(result["return_total"], 0)
                self.assertEqual(list(result["nav"].values()), [1, 1])

    def test_unrecovered_episode_keeps_deepest_observed_drawdown(self):
        episodes = run.drawdown_episodes({
            "2025-01-02": 100, "2025-02-03": 90, "2025-03-03": 100,
            "2025-04-01": 120, "2025-05-01": 60, "2025-12-31": 90,
        })
        self.assertEqual(len(episodes), 2)
        self.assertTrue(episodes[0]["recovered"])
        self.assertAlmostEqual(episodes[0]["depth"], 0.10)
        self.assertFalse(episodes[1]["recovered"])
        self.assertIsNone(episodes[1]["recovery_date"])
        self.assertEqual(episodes[1]["trough_date"], "2025-05-01")
        self.assertAlmostEqual(episodes[1]["depth"], 0.50)

    def test_max_drawdown_orders_year_open_before_same_day_close(self):
        result = run.maximum_drawdown({
            "2026-01-02": 0.80, "2026-01-05": 0.90, "2026-01-02 open": 1,
        })
        self.assertAlmostEqual(result["depth"], 0.20)
        self.assertEqual(result["peak_date"], "2026-01-02 open")
        self.assertEqual(result["trough_date"], "2026-01-02")

    def test_future_prices_do_not_change_frozen_historical_thresholds(self):
        cfg = {"history_start": "2020-12-31", "history_end": "2025-12-31"}
        prices = {"2020-12-31": 100}
        for year in range(2021, 2026):
            prices[f"{year}-01-04"] = 100
            prices[f"{year}-12-31"] = 80
        expected = run.historical_stats("SYNTHETIC", prices, prices, cfg)
        future = {**prices, "2026-01-02": 1000, "2026-01-05": 1}
        actual = run.historical_stats("SYNTHETIC", future, future, cfg)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["full_years"], [2021, 2022, 2023, 2024, 2025])
        self.assertAlmostEqual(actual["half_max"], 0.10)
        self.assertAlmostEqual(actual["mean_annual"], 0.20)

    def test_listing_partial_year_is_excluded_from_annual_mean(self):
        cfg = {"history_start": "2020-12-31", "history_end": "2025-12-31"}
        prices = {"2021-07-01": 100, "2021-12-31": 50}
        for year, closing in [(2022, 90), (2023, 80), (2024, 70), (2025, 60)]:
            prices[f"{year}-01-04"] = 100
            prices[f"{year}-12-31"] = closing
        calendar = {"2020-12-31": 1, "2021-01-04": 1, **prices}
        actual = run.historical_stats("NEW_LISTING", prices, calendar, cfg)
        self.assertEqual(actual["full_years"], [2022, 2023, 2024, 2025])
        self.assertAlmostEqual(actual["mean_annual"], 0.25)
        self.assertAlmostEqual(actual["max_drawdown"], 0.50)


if __name__ == "__main__":
    unittest.main()
