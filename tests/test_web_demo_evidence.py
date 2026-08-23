import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

import web_demo  # noqa: E402


class RealEvidenceValidationTests(unittest.TestCase):
    def valid_evidence(self, **overrides):
        data = {
            "backend": "test_qpu",
            "job_id": "job-123",
            "timestamp": "2026-08-20T00:00:00+00:00",
            "bit_order": "little",
            "shots": 4,
            "counts": {"00": 3, "11": 1},
            "meta": {},
        }
        data.update(overrides)
        return data

    def test_current_incomplete_evidence_is_not_displayed(self):
        self.assertIsNone(web_demo._load_real_bell())

    def test_complete_traceable_counts_are_normalized(self):
        self.assertEqual(
            web_demo._validated_real_probabilities(self.valid_evidence()),
            {"00": 0.75, "11": 0.25},
        )

    def test_malformed_or_out_of_window_timestamp_is_rejected(self):
        self.assertIsNone(
            web_demo._validated_real_probabilities(self.valid_evidence(timestamp="not-a-time"))
        )
        self.assertIsNone(
            web_demo._validated_real_probabilities(
                self.valid_evidence(timestamp="2026-08-25T04:00:01Z")
            )
        )
        self.assertIsNone(
            web_demo._validated_real_probabilities(
                self.valid_evidence(timestamp="2026-07-31T15:59:59Z")
            )
        )

    def test_non_bell_peak_is_rejected(self):
        self.assertIsNone(
            web_demo._validated_real_probabilities(
                self.valid_evidence(counts={"00": 1, "01": 3})
            )
        )

    def test_invalid_tied_peak_and_mock_are_rejected(self):
        self.assertIsNone(
            web_demo._validated_real_probabilities(
                self.valid_evidence(counts={"00": 2, "01": 2})
            )
        )
        self.assertIsNone(
            web_demo._validated_real_probabilities(
                self.valid_evidence(meta={"is_mock": True})
            )
        )

    def test_missing_official_schema_field_is_rejected(self):
        for field in ("backend", "job_id", "timestamp", "bit_order", "shots", "counts"):
            with self.subTest(field=field):
                data = self.valid_evidence()
                data.pop(field)
                self.assertIsNone(web_demo._validated_real_probabilities(data))


class VisualizationContentTypeTests(unittest.TestCase):
    def test_css_is_served_as_stylesheet(self):
        self.assertEqual(
            web_demo._visualization_content_type(Path("qec-games.css")),
            "text/css; charset=utf-8",
        )

    def test_unknown_visualization_asset_is_not_served_as_text(self):
        self.assertEqual(
            web_demo._visualization_content_type(Path("payload.unknown")),
            "application/octet-stream",
        )


if __name__ == "__main__":
    unittest.main()
