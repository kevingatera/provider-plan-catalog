import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("update", Path(__file__).parents[1] / "scripts" / "update.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)

FIXTURE = Path(__file__).parent / "fixtures" / "opencode_go.html"
HEADER = "<tr>" + "".join(f"<th>{h}</th>" for h in update.PRICE_HEADER) + "</tr>"


def price_table(rows):
    return "<table>" + HEADER + "".join(rows) + "</table>"


class CatalogTests(unittest.TestCase):
    def test_unrecognized_layout_fails(self):
        with self.assertRaises(ValueError):
            update.parse_opencode("<table><tr><td>Model</td></tr></table>")

    def test_currency_validation(self):
        self.assertEqual(update.money("$0.15"), 0.15)
        self.assertEqual(update.money("Free"), 0)
        self.assertIsNone(update.money("-"))
        for value in ("$NaN", "-1", "$-1", "$Infinity", "unknown"):
            with self.assertRaises(ValueError):
                update.money(value)

    def test_separate_plan_budgets(self):
        tables = []
        for budget in (15, 60):
            rows = [f"<tr><td>Model {i}</td><td>$3</td><td>$15</td><td>$0.30</td><td>-</td><td>${budget}</td></tr>" for i in range(10)]
            tables.append(price_table(rows))
        plans = update.parse_opencode("5-hour — 20% of monthly; weekly — 50%; monthly — 100%." + "".join(tables))
        self.assertEqual(plans[0]["models"][0]["monthly_allowance_usd"], 15)
        self.assertEqual(plans[1]["models"][0]["monthly_allowance_usd"], 60)
        self.assertIsNone(plans[0]["models"][0]["variant"])

    def test_current_page_fixture(self):
        plans = update.parse_opencode(FIXTURE.read_text(encoding="utf-8"))
        go, go_plus = plans[0]["models"], plans[1]["models"]

        # 36 price rows per plan, which is 29 distinct models once tier and peak splits are grouped.
        self.assertEqual(len(go), 36)
        self.assertEqual(len(go_plus), 36)
        self.assertEqual(len({m["base_name"] for m in go}), 29)
        self.assertEqual(plans[0]["windows"], {"five_hour_fraction": 0.2, "weekly_fraction": 0.5, "monthly_fraction": 1.0})

        by_name = {m["name"]: m for m in go}
        plus_by_name = {m["name"]: m for m in go_plus}

        flash = by_name["GLM-5.3-Flash"]
        self.assertEqual(flash["token_prices_usd_per_million"], {"input": 0.15, "output": 0.5, "cache_read": 0.03, "cache_write": None})
        self.assertEqual(flash["monthly_allowance_usd"], 60.0)
        self.assertIsNone(flash["base_monthly_allowance_usd"])
        self.assertIsNone(flash["limited_time_multiplier"])
        self.assertEqual(plus_by_name["GLM-5.3-Flash"]["monthly_allowance_usd"], 180.0)

        # Tier split: both rows survive with their own prices and a shared base name.
        short = by_name["Qwen3.7 Plus (≤ 256K tokens)"]
        long = by_name["Qwen3.7 Plus (> 256K tokens)"]
        self.assertEqual((short["base_name"], short["variant"]), ("Qwen3.7 Plus", "≤ 256K tokens"))
        self.assertEqual(short["token_prices_usd_per_million"]["input"], 0.4)
        self.assertEqual(short["token_prices_usd_per_million"]["cache_write"], 0.5)
        self.assertEqual(long["token_prices_usd_per_million"]["input"], 1.2)
        self.assertEqual(long["token_prices_usd_per_million"]["cache_write"], 1.5)

        # Peak split.
        peak = by_name["DeepSeek V4.1 Flash (Peak)"]
        off_peak = by_name["DeepSeek V4.1 Flash (Off-Peak)"]
        self.assertEqual((peak["base_name"], peak["variant"]), ("DeepSeek V4.1 Flash", "Peak"))
        self.assertEqual(peak["token_prices_usd_per_million"]["input"], 0.3)
        self.assertEqual(off_peak["token_prices_usd_per_million"]["input"], 0.15)

        # Limited-time promotions: the promoted limit is current, the struck-through limit is kept.
        step = by_name["Step 5 Preview"]
        self.assertEqual((step["monthly_allowance_usd"], step["base_monthly_allowance_usd"], step["limited_time_multiplier"]), (60.0, 15.0, 4))
        step_plus = plus_by_name["Step 5 Preview"]
        self.assertEqual((step_plus["monthly_allowance_usd"], step_plus["base_monthly_allowance_usd"], step_plus["limited_time_multiplier"]), (240.0, 60.0, 4))
        gemini = plus_by_name["Gemini 4 Argon Contributor"]
        self.assertEqual((gemini["monthly_allowance_usd"], gemini["base_monthly_allowance_usd"], gemini["limited_time_multiplier"]), (240.0, 120.0, 2))

        # Unlimited promotion rows have no dollar allowance.
        beam = by_name["Beam Free"]
        self.assertTrue(beam["unlimited_promotion"])
        self.assertIsNone(beam["monthly_allowance_usd"])
        self.assertEqual(beam["token_prices_usd_per_million"]["input"], 0)

    def test_promotion_must_match_its_label(self):
        row = ("<tr><td>Example</td><td>$1</td><td>$2</td><td>-</td><td>-</td>"
               "<td><del>$30</del> <strong>$60</strong><br/><small>3x · Limited time</small></td></tr>")
        with self.assertRaisesRegex(ValueError, "does not match"):
            update.parse_opencode("5-hour — 20%; weekly — 50%; monthly — 100%." + price_table([row]) + price_table([row]))

    def test_unrecognized_promotion_label_fails(self):
        row = ("<tr><td>Example</td><td>$1</td><td>$2</td><td>-</td><td>-</td>"
               "<td><del>$30</del> <strong>$60</strong><br/><small>Sale</small></td></tr>")
        with self.assertRaisesRegex(ValueError, "unrecognized promotion label"):
            update.parse_opencode("5-hour — 20%; weekly — 50%; monthly — 100%." + price_table([row]) + price_table([row]))


if __name__ == "__main__":
    unittest.main()
