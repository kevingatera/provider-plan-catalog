import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("update", Path(__file__).parents[1] / "scripts" / "update.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


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
        header = "<tr>" + "".join(f"<th>{h}</th>" for h in ["Model", "Input", "Output", "Cached Read", "Cached Write", "Monthly limit"]) + "</tr>"
        tables = []
        for budget in (15, 60):
            rows = "".join(f"<tr><td>Model {i}</td><td>$3</td><td>$15</td><td>$0.30</td><td>-</td><td>${budget}</td></tr>" for i in range(10))
            tables.append("<table>" + header + rows + "</table>")
        plans = update.parse_opencode("5-hour — 20% of monthly; weekly — 50%; monthly — 100%." + "".join(tables))
        self.assertEqual(plans[0]["models"][0]["monthly_allowance_usd"], 15)
        self.assertEqual(plans[1]["models"][0]["monthly_allowance_usd"], 60)


if __name__ == "__main__":
    unittest.main()
