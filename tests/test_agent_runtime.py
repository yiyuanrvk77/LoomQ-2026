import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

import agent  # noqa: E402


VALID_BELL = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q -> c;"""


def circuit_reply(qasm):
    return json.dumps({"task": "circuit", "qasm": qasm})


class AgentRuntimeTests(unittest.TestCase):
    def test_valid_circuit_envelope_is_returned_as_qasm(self):
        with mock.patch.object(agent, "_chat_reply", return_value=circuit_reply(VALID_BELL)) as call:
            self.assertEqual(agent.agent_chat("prepare a correlated pair"), VALID_BELL)
        self.assertEqual(call.call_count, 1)

    def test_invalid_gate_is_retried_and_never_escapes(self):
        invalid = VALID_BELL.replace("h q[0];", "u3(0,0,0) q[0];")
        with mock.patch.object(
            agent,
            "_chat_reply",
            side_effect=[circuit_reply(invalid), circuit_reply(VALID_BELL)],
        ) as call:
            self.assertEqual(agent.agent_chat("repair this circuit"), VALID_BELL)
        self.assertEqual(call.call_count, 2)

    def test_three_invalid_model_results_raise(self):
        invalid = circuit_reply(VALID_BELL.replace("h q[0];", "u q[0];"))
        with mock.patch.object(agent, "_chat_reply", return_value=invalid):
            with self.assertRaisesRegex(RuntimeError, "could not produce a validated result"):
                agent.agent_chat("make a circuit")

    def test_backend_constraints_are_filtered_by_capability_tool(self):
        reply = json.dumps(
            {
                "task": "backend",
                "requirements": {
                    "min_qubits": 15,
                    "platform": "any",
                    "device": "simulator",
                    "queue": "none",
                    "cost": "free",
                    "account": "not_required",
                },
            }
        )
        with mock.patch.object(agent, "_chat_reply", return_value=reply):
            result = agent.agent_chat("I need this available immediately without registration")
        self.assertEqual(result, "braket_local_simulator")

    def test_qpu_no_paid_constraint_does_not_select_paid_cloud(self):
        reply = json.dumps(
            {
                "task": "backend",
                "requirements": {
                    "min_qubits": 5,
                    "platform": "any",
                    "device": "qpu",
                    "queue": "any",
                    "cost": "no_paid",
                    "account": "any",
                },
            }
        )
        with mock.patch.object(agent, "_chat_reply", return_value=reply):
            self.assertEqual(agent.agent_chat("run it physically within free quota"), "spinq_cloud_qpu")

    def test_impossible_backend_constraints_report_no_solution(self):
        reply = json.dumps(
            {
                "task": "backend",
                "requirements": {
                    "min_qubits": 80,
                    "platform": "any",
                    "device": "qpu",
                    "queue": "none",
                    "cost": "no_paid",
                    "account": "any",
                },
            }
        )
        with mock.patch.object(agent, "_chat_reply", return_value=reply):
            self.assertIn("无解", agent.agent_chat("constraints expressed in any wording"))

    def test_fractional_minimum_qubits_are_not_silently_truncated(self):
        requirements = {
            "min_qubits": 15.5,
            "platform": "any",
            "device": "simulator",
            "queue": "any",
            "cost": "any",
            "account": "any",
        }
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            agent._normalize_requirements(requirements)

    def test_bare_backend_id_reply_is_accepted(self):
        with mock.patch.object(agent, "_chat_reply", return_value="braket_local_simulator") as call:
            self.assertEqual(agent.agent_chat("15 比特零排队免费选哪个平台？"), "braket_local_simulator")
        self.assertEqual(call.call_count, 1)

    def test_backend_id_inside_prose_is_accepted(self):
        reply = "推荐使用 AWS 本地模拟器，标识为 originq_wukong（可排队）。"
        with mock.patch.object(agent, "_chat_reply", return_value=reply) as call:
            self.assertEqual(agent.agent_chat("真机 5 比特免费选哪个？"), "originq_wukong")
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
