import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

from qasm_parser import Circuit, parse  # noqa: E402
from simulator import Simulator, simulate, simulate_with_noise  # noqa: E402


BASE = 'OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; creg c[2]; h q[0]; measure q -> c;'


class QasmParserHardeningTests(unittest.TestCase):
    def test_compact_one_line_program_is_supported(self):
        circuit = parse(BASE)
        self.assertEqual((circuit.num_qubits, len(circuit.measures)), (2, 2))

    def test_duplicate_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate OPENQASM"):
            parse(BASE.replace('include "qelib1.inc";', 'OPENQASM 2.0; include "qelib1.inc";'))

    def test_gate_after_measurement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "mid-circuit measurement"):
            parse(BASE + " x q[1];")

    def test_wrong_register_and_duplicate_operands_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "declared qreg"):
            parse(BASE.replace("h q[0];", "h other[0];"))
        with self.assertRaisesRegex(ValueError, "same qubit"):
            parse(BASE.replace("h q[0];", "cx q[0],q[0];"))

    def test_non_whitelist_gate_and_nonfinite_angle_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "12-gate whitelist"):
            parse(BASE.replace("h q[0];", "u3(0,0,0) q[0];"))
        with self.assertRaisesRegex(ValueError, "finite"):
            parse(BASE.replace("h q[0];", "rz(1e309) q[0];"))

    def test_uppercase_gate_does_not_hide_a_repair_error(self):
        with self.assertRaisesRegex(ValueError, "case-sensitive"):
            parse(BASE.replace("h q[0];", "H q[0];"))

    def test_include_order_duplicates_and_empty_operands_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate include"):
            parse(BASE.replace('qreg q[2];', 'include "qelib1.inc"; qreg q[2];'))
        with self.assertRaisesRegex(ValueError, "must precede register"):
            parse(BASE.replace('include "qelib1.inc"; qreg q[2];', 'qreg q[2]; include "qelib1.inc";'))
        with self.assertRaisesRegex(ValueError, "empty operand"):
            parse(BASE.replace("h q[0];", "h q[0],;"))

    def test_barrier_must_reference_valid_quantum_operands(self):
        parsed = parse(BASE.replace("h q[0];", "barrier q[0],q[1]; h q[0];"))
        self.assertEqual([gate.name for gate in parsed.gates], ["h"])
        with self.assertRaisesRegex(ValueError, "declared qreg"):
            parse(BASE.replace("h q[0];", "barrier c; h q[0];"))
        with self.assertRaisesRegex(ValueError, "out of range"):
            parse(BASE.replace("h q[0];", "barrier q[2]; h q[0];"))

    def test_local_simulator_rejects_resource_exhausting_or_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "supports 1 to 20 qubits"):
            Simulator(21)
        circuit = Circuit(num_qubits=1, num_clbits=1, measures=[(0, 0)])
        with self.assertRaisesRegex(ValueError, "shots must be"):
            simulate(circuit, 0)
        with self.assertRaisesRegex(ValueError, "error_rate"):
            simulate_with_noise(circuit, 1, 1.1)


if __name__ == "__main__":
    unittest.main()
