import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter_kit"))

from riscv_emulator import TinyRISCVEmulator, decode_quant, encode_quant  # noqa: E402


class RiscvExtensionEncodingTests(unittest.TestCase):
    def test_all_documented_encodings_round_trip(self):
        for rd in (0, 1, 17, 31):
            for gate in (0, 1, 2):
                with self.subTest(rd=rd, gate=gate):
                    self.assertEqual(decode_quant(encode_quant(rd, gate)), (rd, gate))

    def test_reserved_fields_and_gate_codes_are_rejected(self):
        word = encode_quant(3, 1)
        for corrupted in (word | (1 << 12), word | (1 << 15), word | (3 << 20)):
            with self.subTest(word=corrupted):
                with self.assertRaisesRegex(ValueError, "合法的 QUANT"):
                    decode_quant(corrupted)

    def test_encoder_rejects_undocumented_gate_code(self):
        with self.assertRaisesRegex(ValueError, "编码越界"):
            encode_quant(1, 3)

    def test_h_x_z_truth_tables_match_the_documented_four_state_model(self):
        expected = {
            0: (2, 3, 0, 1),
            1: (1, 0, 2, 3),
            2: (0, 1, 3, 2),
        }
        for gate, outputs in expected.items():
            for state, output in enumerate(outputs):
                with self.subTest(gate=gate, state=state):
                    emulator = TinyRISCVEmulator()
                    emulator.load_program("li x1, %d\nquant x1, %d" % (state, gate))
                    emulator.execute()
                    self.assertEqual(emulator.get_register("x1"), output)


if __name__ == "__main__":
    unittest.main()
