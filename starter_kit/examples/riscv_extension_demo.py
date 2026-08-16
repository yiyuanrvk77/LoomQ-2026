"""量子 RISC-V 扩展（QUANT 指令）端到端测试。

运行：python3 starter_kit/examples/riscv_extension_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from riscv_emulator import TinyRISCVEmulator  # noqa: E402

ASM = """
# QUANT rd, imm：自定义量子扩展指令，imm ∈ {0=H, 1=X, 2=Z}
# 状态约定：0=|0⟩, 1=|1⟩, 2=|+⟩, 3=|−⟩
li x1, 0
quant x1, 0     # H: |0⟩ -> |+⟩(2)
quant x1, 1     # X: |+⟩ -> |−⟩(3)
quant x1, 2     # Z: |−⟩ -> |+⟩(2)
quant x1, 1     # X: |+⟩ -> |−⟩(3)
quant x1, 0     # H: |−⟩ -> |1⟩(1)
li x2, 1
beq x1, x2, PASS
li x3, 99
j END
PASS:
li x3, 0
END:
"""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # 展示「汇编 -> 编码 -> 机器码 -> 解码」闭环
    from riscv_emulator import decode_quant, encode_quant

    print("== 编码/解码闭环（机器码真正进入执行链路）==")
    for rd, imm in ((1, 0), (1, 1), (1, 2)):
        word = encode_quant(rd, imm)
        decoded = decode_quant(word)
        print(f"  quant x{rd}, {imm}  ->  0x{word:08X}  ->  (x{decoded[0]}, {decoded[1]})")
        assert decoded == (rd, imm)

    emu = TinyRISCVEmulator()
    emu.load_program(ASM)
    state = emu.execute()
    assert state.get("x1") == 1, "量子门序列错误：x1=%s" % state.get("x1")
    # 模拟器只返回非零寄存器，x3=0 表示"未出现"即 PASS；失败时 x3=99
    assert state.get("x3", 0) == 0, "自检标记应为 0（PASS）"
    print("量子 RISC-V 扩展（QUANT）端到端测试通过：x1=1（|1⟩），x3=0（PASS）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
