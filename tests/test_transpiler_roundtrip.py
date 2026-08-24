import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

from circuit_gen import random_circuit  # noqa: E402
from qasm_parser import parse  # noqa: E402
from simulator import probabilities, simulate  # noqa: E402
from transpiler import emit, parse_target, standardize_braket_qasm  # noqa: E402


ALL_GATES = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
creg c[3];
h q[0];
x q[1];
s q[0];
sdg q[0];
t q[1];
tdg q[1];
rz(pi/7) q[2];
ry(-pi/5) q[0];
cx q[0],q[1];
cu1(pi/3) q[1],q[2];
swap q[0],q[2];
ccx q[0],q[1],q[2];
measure q -> c;"""


class TranspilerRoundTripTests(unittest.TestCase):
    def assert_distribution_close(self, left, right):
        self.assertEqual(set(left), set(right))
        for key in left:
            self.assertAlmostEqual(left[key], right[key], places=10)

    def test_all_whitelist_gates_round_trip_through_every_target(self):
        source = parse(ALL_GATES)
        expected = probabilities(source)
        for target in ("spinq", "originq", "braket"):
            with self.subTest(target=target):
                recovered = parse_target(emit(source, target), target)
                self.assert_distribution_close(probabilities(recovered), expected)

    def test_random_hidden_style_circuits_round_trip(self):
        for seed in range(12):
            source = parse(random_circuit(3 + seed % 3, 18, seed))
            expected = probabilities(source)
            for target in ("spinq", "originq", "braket"):
                with self.subTest(seed=seed, target=target):
                    recovered = parse_target(emit(source, target), target)
                    self.assert_distribution_close(probabilities(recovered), expected)

    def test_little_endian_schema_places_c0_at_the_right(self):
        circuit = parse(
            'OPENQASM 2.0; include "qelib1.inc"; qreg q[3]; creg c[3]; '
            'x q[0]; measure q -> c;'
        )
        self.assertEqual(simulate(circuit, 32), {"001": 32})

    def test_braket_dialect_can_be_standardized_to_stdgates_names(self):
        source = parse(ALL_GATES)
        braket = emit(source, "braket")
        self.assertIn("si", braket)
        standardized = standardize_braket_qasm(braket)
        for native, standard in (("si", "sdg"), ("ti", "tdg"), ("cphaseshift", "cp"), ("ccnot", "ccx")):
            self.assertNotIn(native, standardized)
            self.assertIn(standard, standardized)
        self.assert_distribution_close(
            probabilities(parse_target(standardized, "braket")),
            probabilities(source),
        )


if __name__ == "__main__":
    unittest.main()
