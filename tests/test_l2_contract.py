import importlib
import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "starter_kit" / "llm_client.py"
POLICY = ROOT / "starter_kit" / "l2_policy.json"


def load_client():
    spec = importlib.util.spec_from_file_location("loomq_public_llm_client", CLIENT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CompatibleAPIHandler(BaseHTTPRequestHandler):
    request_payload = None

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(length))
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PublicL2ContractTests(unittest.TestCase):
    def test_adapter_supports_standard_package_import(self):
        adapter = importlib.import_module("starter_kit.adapter")

        self.assertEqual(adapter.SUPPORTED_TARGETS, ("spinq", "originq", "braket"))
        concept = adapter.concept_answer("什么是贝尔态？")
        self.assertEqual(concept["name"], "贝尔态")
        self.assertIn("OPENQASM 2.0;", concept["qasm"])

    def test_adapter_rejects_invalid_shots_before_execution(self):
        adapter = importlib.import_module("starter_kit.adapter")
        qasm = (ROOT / "starter_kit" / "circuits" / "bell.qasm").read_text(encoding="utf-8")

        for invalid in (0, -1, True, 1.5, 1_000_001):
            with self.subTest(shots=invalid):
                with self.assertRaisesRegex(ValueError, "shots must be a positive integer"):
                    adapter.run(qasm, "braket", invalid)

    def test_invalid_vendor_counts_fall_back_to_the_internal_simulator(self):
        adapter = importlib.import_module("starter_kit.adapter")
        qasm = (ROOT / "starter_kit" / "circuits" / "bell.qasm").read_text(encoding="utf-8")
        with mock.patch.object(adapter, "run_backend", return_value=({"0": 1}, "bad-sdk-job")):
            result = adapter.run(qasm, "braket", 32)
        self.assertEqual(sum(result["counts"].values()), 32)
        self.assertEqual(result["meta"]["source"], "internal_simulator_fallback")
        self.assertTrue(result["job_id"].startswith("local-"))

    def test_local_sdk_task_ids_cannot_be_mistaken_for_hardware_evidence(self):
        adapter = importlib.import_module("starter_kit.adapter")
        qasm = (ROOT / "starter_kit" / "circuits" / "bell.qasm").read_text(encoding="utf-8")
        counts = {"00": 16, "11": 16}
        with mock.patch.object(adapter, "run_backend", return_value=(counts, "sdk-task-123")):
            result = adapter.run(qasm, "braket", 32)
        self.assertEqual(result["job_id"], "local-braket-sdk-task-123")
        self.assertEqual(result["meta"]["local_sdk_job_id"], "sdk-task-123")
        self.assertFalse(result["meta"]["is_hardware"])

    def test_policy_is_the_published_formal_deepseek_budget(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["formal_model"], "deepseek-v4-flash")
        self.assertEqual(policy["thinking"], {"type": "disabled"})
        self.assertEqual(
            policy["per_case"],
            {"timeout_seconds": 120},
        )
        self.assertFalse(policy["organizer_api_available_before_scoring"])

    def test_missing_environment_fails_without_echoing_secrets(self):
        client = load_client()
        with mock.patch.dict(os.environ, {"UNRELATED_SECRET": "do-not-echo"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LOOMQ_LLM_BASE_URL") as caught:
                client.chat_completion([{"role": "user", "content": "hello"}])
        self.assertNotIn("do-not-echo", str(caught.exception))

    def test_nonfinite_timeout_configuration_is_rejected(self):
        client = load_client()
        for bad_value in ("nan", "inf", "-inf"):
            environment = {
                "LOOMQ_LLM_BASE_URL": "http://127.0.0.1:1",
                "LOOMQ_LLM_API_KEY": "local-key",
                "LOOMQ_LLM_MODEL": "local-model",
                "LOOMQ_LLM_TIMEOUT_SECONDS": bad_value,
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(RuntimeError, "finite"):
                    client._configuration()

    def test_client_works_with_an_openai_compatible_endpoint(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CompatibleAPIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = {
                "LOOMQ_LLM_BASE_URL": "http://127.0.0.1:%d" % server.server_port,
                "LOOMQ_LLM_API_KEY": "local-key",
                "LOOMQ_LLM_MODEL": "local-model",
                "LOOMQ_LLM_TIMEOUT_SECONDS": "2",
                }
            with mock.patch.dict(os.environ, environment, clear=True):
                response = load_client().chat_completion(
                    [{"role": "user", "content": "hello"}],
                    model="must-not-override",
                    stream=True,
                    temperature=1,
                    max_tokens=1,
                    thinking={"type": "enabled"},
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(CompatibleAPIHandler.request_payload["model"], "local-model")
        self.assertEqual(CompatibleAPIHandler.request_payload["temperature"], 0)
        self.assertFalse(CompatibleAPIHandler.request_payload["stream"])
        self.assertEqual(CompatibleAPIHandler.request_payload["max_tokens"], 4096)
        self.assertNotIn("thinking", CompatibleAPIHandler.request_payload)


if __name__ == "__main__":
    unittest.main()
