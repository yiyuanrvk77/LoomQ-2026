import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "starter_kit" / "evidence" / "validate_hardware_result.py"


class HardwareEvidenceValidatorTests(unittest.TestCase):
    def valid_result(self):
        return {
            "backend": "spinq_gemini_vp",
            "job_id": "G-123",
            "shots": 4,
            "counts": {"00": 3, "11": 1},
            "bit_order": "little",
            "timestamp": "2026-08-20T03:00:00Z",
            "meta": {"is_hardware": True, "platform_device_id": "gemini_vp"},
        }

    def run_validator(self, data):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_valid_result_passes(self):
        self.assertEqual(self.run_validator(self.valid_result()).returncode, 0)

    def test_count_mismatch_is_rejected(self):
        data = self.valid_result()
        data["counts"]["11"] = 2
        self.assertNotEqual(self.run_validator(data).returncode, 0)

    def test_local_job_and_missing_device_are_rejected(self):
        data = self.valid_result()
        data["job_id"] = "local-spinq-123"
        data["meta"].pop("platform_device_id")
        result = self.run_validator(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local job IDs", result.stdout)


if __name__ == "__main__":
    unittest.main()
