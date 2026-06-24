from __future__ import annotations

from pathlib import Path
import unittest


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


class QuoteSummaryCostCurrencyTest(unittest.TestCase):
    def test_summary_system_cost_stays_cny_when_fob_is_enabled(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        start = text.index("const systemCostDisplay")
        chunk = text[start : start + 260]

        self.assertIn('quote.system_cost_text || "-"', chunk)
        self.assertNotIn("fmtUsd(toUsd(tier0CostNum))", chunk)


if __name__ == "__main__":
    unittest.main()
