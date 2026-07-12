from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills" / "auto-research" / "assets" / "review-optimization"
P0 = ASSETS / "smoke-prompt.md"
P1 = ASSETS / "smoke-prompt-calibration-v2.md"


class PromptCandidateContractTest(unittest.TestCase):
    def test_p1_preserves_p0_and_adds_one_calibration_module(self) -> None:
        baseline = P0.read_text(encoding="utf-8")
        candidate = P1.read_text(encoding="utf-8")

        self.assertTrue(candidate.startswith(baseline))
        addition = candidate[len(baseline) :]
        self.assertEqual(addition.count("## Evidence-to-ordinal calibration pass"), 1)
        normalized_addition = " ".join(addition.split())
        for required in (
            "strongest supporting evidence",
            "most decision-relevant deficiency",
            "material flaw affecting a central claim",
            "mostly solid",
            "only minor limitations",
            "not a mechanical average",
            "evaluator certainty",
            "section, table, figure, equation, or reported result",
        ):
            self.assertIn(required, normalized_addition)


if __name__ == "__main__":
    unittest.main()
