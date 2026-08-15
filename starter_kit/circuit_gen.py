"""隐藏电路风格生成器（仅使用 12 门白名单），用于本地扩展自测。"""

import random


def ghz(n: int) -> str:
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{n}];",
        f"creg c[{n}];",
        "h q[0];",
    ]
    for i in range(n - 1):
        lines.append(f"cx q[{i}], q[{i + 1}];")
    for i in range(n):
        lines.append(f"measure q[{i}] -> c[{i}];")
    return "\n".join(lines) + "\n"


def qft(n: int) -> str:
    """Standard QFT on |0...0> -> uniform superposition (little-endian)."""
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{n}];",
        f"creg c[{n}];",
    ]
    import math

    for i in range(n):
        lines.append(f"h q[{i}];")
        for j in range(i + 1, n):
            angle = math.pi / (2 ** (j - i))
            lines.append(f"cu1({angle:.12g}) q[{j}], q[{i}];")
    for i in range(n // 2):
        lines.append(f"swap q[{i}], q[{n - 1 - i}];")
    for i in range(n):
        lines.append(f"measure q[{i}] -> c[{i}];")
    return "\n".join(lines) + "\n"


def grover_3(marked: int = 7) -> str:
    """3-qubit Grover search for the marked state `marked` (0..7)."""
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        "qreg q[3];",
        "creg c[3];",
        "h q[0];",
        "h q[1];",
        "h q[2];",
    ]

    def ccz():
        # Controlled-controlled-Z on q[0],q[1] -> q[2] (H sandwich around Toffoli).
        lines.append("h q[2];")
        lines.append("ccx q[0], q[1], q[2];")
        lines.append("h q[2];")

    # Oracle: phase-flip the marked basis state via X on zero bits + CCZ + X.
    bits = [(marked >> i) & 1 for i in range(3)]
    for i in range(3):
        if bits[i] == 0:
            lines.append(f"x q[{i}];")
    ccz()
    for i in range(3):
        if bits[i] == 0:
            lines.append(f"x q[{i}];")
    # Diffusion operator.
    for i in range(3):
        lines.append(f"h q[{i}];")
    for i in range(3):
        lines.append(f"x q[{i}];")
    ccz()
    for i in range(3):
        lines.append(f"x q[{i}];")
    for i in range(3):
        lines.append(f"h q[{i}];")
    for i in range(3):
        lines.append(f"measure q[{i}] -> c[{i}];")
    return "\n".join(lines) + "\n"


def random_circuit(n: int, gates_count: int, seed: int) -> str:
    rng = random.Random(seed)
    single_no_param = ["h", "x", "s", "sdg", "t", "tdg"]
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{n}];",
        f"creg c[{n}];",
    ]
    for _ in range(gates_count):
        kind = rng.random()
        if kind < 0.45:
            g = rng.choice(single_no_param)
            q = rng.randrange(n)
            lines.append(f"{g} q[{q}];")
        elif kind < 0.7:
            g = rng.choice(["rz", "ry"])
            theta = rng.choice([0.25, 0.5, 0.75, 1.0])
            q = rng.randrange(n)
            lines.append(f"{g}({theta}) q[{q}];")
        elif kind < 0.9:
            g = rng.choice(["cx", "cu1", "swap"])
            a = rng.randrange(n)
            b = rng.randrange(n)
            while b == a:
                b = rng.randrange(n)
            if g == "cu1":
                theta = rng.choice([0.25, 0.5, 1.0])
                lines.append(f"cu1({theta}) q[{a}], q[{b}];")
            else:
                lines.append(f"{g} q[{a}], q[{b}];")
        else:
            if n >= 3:
                qs = rng.sample(range(n), 3)
                lines.append(f"ccx q[{qs[0]}], q[{qs[1]}], q[{qs[2]}];")
            else:
                lines.append(f"h q[{rng.randrange(n)}];")
    for i in range(n):
        lines.append(f"measure q[{i}] -> c[{i}];")
    return "\n".join(lines) + "\n"


"""L3: Hybrid-QASM (classical block) -> quantum ops + RISC-V assembly.

The classical mini-language is intentionally small:
    integer literals, registers r1..r9, measurement bits c[k],
    operators + - == !=, if/else and sequential assignment.

Registers r1..r9 map to RISC-V x1..x9, and c[k] maps to x(10+k) (injected
by the evaluation system). We emit only `li / add / sub / addi / beq / bne / j`,
the exact instruction subset supported by the official `riscv_emulator.py`.
"""

