import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

from hybrid import compile_hybrid  # noqa: E402
from riscv_emulator import TinyRISCVEmulator  # noqa: E402


SOURCE = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
measure q[0] -> c[0];
classical {
  r1 = c[0] + 4;
  r2 = c[1] - r1;
  if (r1 + r2 == 1) {
    r3 = r1 - (r2 - 2);
    if (c[0] != c[1]) { r4 = r3 + r1; }
    else { r4 = r3 - r1; }
  } else {
    r3 = -(r1 + r2);
    r4 = 9 - r3;
  }
  r5 = r4 + r2 - c[0];
}
cx q[0],q[1];
measure q[1] -> c[1];
"""


def reference(c0, c1):
    r1 = c0 + 4
    r2 = c1 - r1
    if r1 + r2 == 1:
        r3 = r1 - (r2 - 2)
        r4 = r3 + r1 if c0 != c1 else r3 - r1
    else:
        r3 = -(r1 + r2)
        r4 = 9 - r3
    r5 = r4 + r2 - c0
    return (r1, r2, r3, r4, r5)


class HybridHiddenStyleTests(unittest.TestCase):
    def test_nested_branches_match_a_reference_for_every_measurement(self):
        quantum_ops, assembly = compile_hybrid(SOURCE)
        self.assertEqual(
            quantum_ops,
            ["h q[0]", "measure q[0] -> c[0]", "cx q[0], q[1]", "measure q[1] -> c[1]"],
        )
        for c0 in (0, 1):
            for c1 in (0, 1):
                with self.subTest(c0=c0, c1=c1):
                    emulator = TinyRISCVEmulator()
                    emulator.load_program(assembly)
                    emulator.set_register("x10", c0)
                    emulator.set_register("x11", c1)
                    emulator.execute()
                    actual = tuple(emulator.get_register("x%d" % i) for i in range(1, 6))
                    self.assertEqual(actual, reference(c0, c1))


if __name__ == "__main__":
    unittest.main()
