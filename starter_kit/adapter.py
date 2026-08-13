"""LoomQ L1 self-contained adapter.

Drop this file into your fork's `starter_kit/adapter.py` and implement
the real SDK runners where marked. See README.md for details.
"""


"""Unified intermediate representation for a quantum circuit."""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Gate:
    name: str
    params: List[float]
    qubits: List[int]


@dataclass
class Circuit:
    num_qubits: int
    num_clbits: int
    gates: List[Gate] = field(default_factory=list)
    # Each tuple is (qubit_index, clbit_index).
    measures: List[Tuple[int, int]] = field(default_factory=list)



"""A small, dependency-free OpenQASM 2.0 parser for the 12-gate whitelist.

It intentionally parses only the subset used by LoomQ L1:
    OPENQASM 2.0; / include; / qreg; / creg;
    single-qubit, two-qubit and three-qubit gate calls;
    measure; barrier (ignored).
"""


import ast
import math
import re



def _eval_param(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_param(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return math.pi
        raise ValueError("unknown symbol: %s" % node.id)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return -_eval_param(node.operand)
        if isinstance(node.op, ast.UAdd):
            return _eval_param(node.operand)
    if isinstance(node, ast.BinOp):
        left = _eval_param(node.left)
        right = _eval_param(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    raise ValueError("unsupported parameter expression")


def _eval_expression(text: str) -> float:
    text = text.strip()
    if not text:
        raise ValueError("empty parameter expression")
    return _eval_param(ast.parse(text, mode="eval"))


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def parse(qasm: str) -> Circuit:
    num_qubits: int | None = None
    num_clbits: int | None = None
    gates: list[Gate] = []
    measures: list[tuple[int, int]] = []

    for raw in qasm.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue
        if line.startswith("barrier"):
            continue

        m = re.match(r"qreg\s+\w+\s*\[\s*(\d+)\s*\]\s*;", line)
        if m:
            num_qubits = int(m.group(1))
            continue

        m = re.match(r"creg\s+\w+\s*\[\s*(\d+)\s*\]\s*;", line)
        if m:
            num_clbits = int(m.group(1))
            continue

        m = re.match(
            r"measure\s+\w+\s*\[\s*(\d+)\s*\]\s*->\s*\w+\s*\[\s*(\d+)\s*\]\s*;",
            line,
        )
        if m:
            measures.append((int(m.group(1)), int(m.group(2))))
            continue

        m = re.match(r"([a-zA-Z][a-zA-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*);", line)
        if m:
            name = m.group(1).lower()
            param_text = m.group(2)
            params = (
                [_eval_expression(p) for p in param_text.split(",")]
                if param_text
                else []
            )
            qubits = [int(q) for _, q in re.findall(r"(\w+)\[(\d+)\]", m.group(3))]
            gates.append(Gate(name=name, params=params, qubits=qubits))
            continue

        raise ValueError("unrecognized line: %s" % line)

    if num_qubits is None:
        raise ValueError("missing qreg declaration")
    if num_clbits is None:
        raise ValueError("missing creg declaration")

    return Circuit(
        num_qubits=num_qubits,
        num_clbits=num_clbits,
        gates=gates,
        measures=measures,
    )



"""A tiny noiseless state-vector simulator for the 12-gate whitelist.

This exists so the skeleton can self-verify `run()` without installing any
quantum SDK. Swap this out for the real SpinQit / pyqpanda / Braket runners
once you wire up true-machine evidence.
"""


import cmath
import math
import random



_SQ2 = math.sqrt(2.0)


def _H():
    return [[1 / _SQ2, 1 / _SQ2], [1 / _SQ2, -1 / _SQ2]]


def _RZ(theta):
    return [[cmath.exp(-1j * theta / 2), 0], [0, cmath.exp(1j * theta / 2)]]


def _RY(theta):
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return [[c, -s], [s, c]]


_SINGLE = {
    "h": _H(),
    "x": [[0, 1], [1, 0]],
    "s": [[1, 0], [0, 1j]],
    "sdg": [[1, 0], [0, -1j]],
    "t": [[1, 0], [0, cmath.exp(1j * math.pi / 4)]],
    "tdg": [[1, 0], [0, cmath.exp(-1j * math.pi / 4)]],
}


class Simulator:
    def __init__(self, num_qubits: int):
        self.n = num_qubits
        self.state = [0j] * (1 << num_qubits)
        self.state[0] = 1 + 0j

    def _apply1(self, u, q: int):
        n = self.n
        mask = 1 << q
        step = 1 << (q + 1)
        block = 1 << q
        state = self.state
        for start in range(0, 1 << n, step):
            for j in range(start, start + block):
                i0 = j
                i1 = j | mask
                a = state[i0]
                b = state[i1]
                state[i0] = u[0][0] * a + u[0][1] * b
                state[i1] = u[1][0] * a + u[1][1] * b

    def _apply2(self, u, a: int, b: int):
        n = self.n
        mask_a = 1 << a
        mask_b = 1 << b
        mask = mask_a | mask_b
        state = self.state
        for idx in range(1 << n):
            if idx & mask:
                continue
            i00 = idx
            i01 = idx | mask_b
            i10 = idx | mask_a
            i11 = idx | mask
            v00 = state[i00]
            v01 = state[i01]
            v10 = state[i10]
            v11 = state[i11]
            state[i00] = u[0][0] * v00 + u[0][1] * v01 + u[0][2] * v10 + u[0][3] * v11
            state[i01] = u[1][0] * v00 + u[1][1] * v01 + u[1][2] * v10 + u[1][3] * v11
            state[i10] = u[2][0] * v00 + u[2][1] * v01 + u[2][2] * v10 + u[2][3] * v11
            state[i11] = u[3][0] * v00 + u[3][1] * v01 + u[3][2] * v10 + u[3][3] * v11

    def _apply_ccx(self, a: int, b: int, c: int):
        # qelib1 standard Toffoli decomposition (control a,b; target c).
        self._apply1(_H(), c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], b, c)
        self._apply1(_SINGLE["tdg"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, c)
        self._apply1(_SINGLE["t"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], b, c)
        self._apply1(_SINGLE["tdg"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, c)
        self._apply1(_SINGLE["t"], b)
        self._apply1(_SINGLE["t"], c)
        self._apply1(_H(), c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, b)
        self._apply1(_SINGLE["t"], a)
        self._apply1(_SINGLE["tdg"], b)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, b)

    def apply(self, gate: Gate):
        name = gate.name
        qubits = gate.qubits
        if name in _SINGLE:
            self._apply1(_SINGLE[name], qubits[0])
        elif name == "rz":
            self._apply1(_RZ(gate.params[0]), qubits[0])
        elif name == "ry":
            self._apply1(_RY(gate.params[0]), qubits[0])
        elif name == "cx":
            self._apply2(
                [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]],
                qubits[0],
                qubits[1],
            )
        elif name == "cu1":
            self._apply2(
                [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, cmath.exp(1j * gate.params[0])],
                ],
                qubits[0],
                qubits[1],
            )
        elif name == "swap":
            self._apply2(
                [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
                qubits[0],
                qubits[1],
            )
        elif name == "ccx":
            self._apply_ccx(*qubits)
        else:
            raise ValueError("unsupported gate: %s" % name)


def _final_state(circuit: Circuit) -> list[complex]:
    sim = Simulator(circuit.num_qubits)
    for gate in circuit.gates:
        sim.apply(gate)
    return sim.state


def _measure_map(circuit: Circuit) -> dict[int, int]:
    clbit_to_qubit: dict[int, int] = {}
    for qubit, clbit in circuit.measures:
        clbit_to_qubit[clbit] = qubit
    return clbit_to_qubit


def _key_for_index(index: int, circuit: Circuit, clbit_to_qubit: dict[int, int]) -> str:
    bits = [(index >> i) & 1 for i in range(circuit.num_qubits)]
    nc = circuit.num_clbits
    return "".join(
        str(bits[clbit_to_qubit[j]]) if j in clbit_to_qubit else "0"
        for j in range(nc - 1, -1, -1)
    )


def probabilities(circuit: Circuit) -> dict[str, float]:
    """Exact measurement probability distribution for the measured bits."""
    state = _final_state(circuit)
    clbit_to_qubit = _measure_map(circuit)
    dist: dict[str, float] = {}
    for index, amplitude in enumerate(state):
        prob = abs(amplitude) ** 2
        if prob == 0:
            continue
        key = _key_for_index(index, circuit, clbit_to_qubit)
        dist[key] = dist.get(key, 0.0) + prob
    return dist


def simulate(circuit: Circuit, shots: int) -> dict[str, int]:
    state = _final_state(circuit)

    probs = [abs(amplitude) ** 2 for amplitude in state]
    sampled = random.choices(range(1 << circuit.num_qubits), weights=probs, k=shots)

    clbit_to_qubit = _measure_map(circuit)

    counts: dict[str, int] = {}
    for index in sampled:
        key = _key_for_index(index, circuit, clbit_to_qubit)
        counts[key] = counts.get(key, 0) + 1
    return counts


"""Emit the unified IR as each backend's native target representation."""




def _fmt(value: float) -> str:
    if abs(value) < 1e-15:
        value = 0.0
    return f"{value:.12g}"


def _args(qubits: list[int]) -> str:
    return ", ".join(f"q[{i}]" for i in qubits)


def _emit_spinq(circ: Circuit) -> str:
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{circ.num_qubits}];",
        f"creg c[{circ.num_clbits}];",
    ]
    for g in circ.gates:
        args = _args(g.qubits)
        if g.params:
            params = ", ".join(_fmt(p) for p in g.params)
            lines.append(f"{g.name}({params}) {args};")
        else:
            lines.append(f"{g.name} {args};")
    for qubit, clbit in circ.measures:
        lines.append(f"measure q[{qubit}] -> c[{clbit}];")
    return "\n".join(lines) + "\n"


_BRAKET_GATES = {
    "h": "h",
    "x": "x",
    "s": "s",
    "sdg": "sdg",
    "t": "t",
    "tdg": "tdg",
    "rz": "rz",
    "ry": "ry",
    "cx": "cnot",
    "cu1": "cp",
    "swap": "swap",
    "ccx": "ccx",
}


def _emit_braket(circ: Circuit) -> str:
    lines = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qubit[{circ.num_qubits}] q;",
        f"bit[{circ.num_clbits}] c;",
    ]
    for g in circ.gates:
        name = _BRAKET_GATES[g.name]
        args = _args(g.qubits)
        if g.params:
            params = ", ".join(_fmt(p) for p in g.params)
            lines.append(f"{name}({params}) {args};")
        else:
            lines.append(f"{name} {args};")
    for qubit, clbit in circ.measures:
        lines.append(f"c[{clbit}] = measure q[{qubit}];")
    return "\n".join(lines) + "\n"


_ORIGINQ_GATES = {
    "h": "H",
    "x": "X",
    "s": "S",
    "sdg": "SDAG",
    "t": "T",
    "tdg": "TDAG",
    "rz": "RZ",
    "ry": "RY",
    "cx": "CNOT",
    "cu1": "CU1",
    "swap": "SWAP",
    "ccx": "TOFFOLI",
}


def _emit_originq(circ: Circuit) -> str:
    lines = [
        f"QINIT {circ.num_qubits}",
        f"CREG {circ.num_clbits}",
    ]
    for g in circ.gates:
        name = _ORIGINQ_GATES[g.name]
        args = _args(g.qubits)
        if g.params:
            params = ", ".join(_fmt(p) for p in g.params)
            lines.append(f"{name}({params}) {args}")
        else:
            lines.append(f"{name} {args}")
    for qubit, clbit in circ.measures:
        lines.append(f"MEASURE q[{qubit}], c[{clbit}]")
    return "\n".join(lines) + "\n"


def emit(circ: Circuit, target: str) -> str:
    if target == "spinq":
        return _emit_spinq(circ)
    if target == "braket":
        return _emit_braket(circ)
    if target == "originq":
        return _emit_originq(circ)
    raise ValueError("unsupported target: %s" % target)



"""Parse each backend's target IR back into the unified Circuit.

This enables round-trip self-checking: `transpile -> parse -> simulate` must
reproduce the same distribution as simulating the original OpenQASM 2.0.
"""


import re



def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def parse_braket(text: str) -> Circuit:
    num_qubits: int | None = None
    num_clbits: int | None = None
    gates: list[Gate] = []
    measures: list[tuple[int, int]] = []

    gate_map = {
        "h": "h", "x": "x", "s": "s", "sdg": "sdg", "t": "t", "tdg": "tdg",
        "rz": "rz", "ry": "ry", "cnot": "cx", "cx": "cx", "cp": "cu1",
        "cu1": "cu1", "swap": "swap", "ccx": "ccx",
    }

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue
        m = re.match(r"qubit\s*\[\s*(\d+)\s*\]\s+q\s*;", line)
        if m:
            num_qubits = int(m.group(1))
            continue
        m = re.match(r"bit\s*\[\s*(\d+)\s*\]\s+c\s*;", line)
        if m:
            num_clbits = int(m.group(1))
            continue
        m = re.match(r"c\s*=\s*measure\s+q\s*;", line)
        if m:
            for i in range(num_qubits or 0):
                measures.append((i, i))
            continue
        m = re.match(r"c\s*\[\s*(\d+)\s*\]\s*=\s*measure\s+q\s*\[\s*(\d+)\s*\]\s*;", line)
        if m:
            measures.append((int(m.group(2)), int(m.group(1))))
            continue
        m = re.match(r"([a-zA-Z][a-zA-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*);", line)
        if m:
            name = m.group(1).lower()
            params = (
                [_eval_expression(p) for p in m.group(2).split(",")]
                if m.group(2)
                else []
            )
            qubits = [int(q) for q in re.findall(r"q\[(\d+)\]", m.group(3))]
            gates.append(Gate(gate_map.get(name, name), params, qubits))
            continue

    if num_qubits is None or num_clbits is None:
        raise ValueError("braket target missing qubit/bit declaration")
    return Circuit(num_qubits, num_clbits, gates, measures)


def parse_originq(text: str) -> Circuit:
    num_qubits: int | None = None
    num_clbits: int | None = None
    gates: list[Gate] = []
    measures: list[tuple[int, int]] = []

    gate_map = {
        "H": "h", "X": "x", "S": "s", "SDAG": "sdg", "T": "t", "TDAG": "tdg",
        "RZ": "rz", "RY": "ry", "CNOT": "cx", "CU1": "cu1", "CR": "cu1",
        "SWAP": "swap", "TOFFOLI": "ccx", "CCX": "ccx",
    }

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        m = re.match(r"QINIT\s+(\d+)", line)
        if m:
            num_qubits = int(m.group(1))
            continue
        m = re.match(r"CREG\s+(\d+)", line)
        if m:
            num_clbits = int(m.group(1))
            continue
        m = re.match(r"MEASURE\s+q\s*\[\s*(\d+)\s*\]\s*,\s*c\s*\[\s*(\d+)\s*\]", line)
        if m:
            measures.append((int(m.group(1)), int(m.group(2))))
            continue
        # Gate with optional (params) right after name, or the `,(params)` form.
        m = re.match(r"([A-Za-z][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*)", line)
        if m:
            name = m.group(1)
            params = []
            rest = m.group(3)
            if m.group(2):
                params = [_eval_expression(p) for p in m.group(2).split(",")]
            elif re.search(r"\(\s*[^)]*\s*\)\s*$", rest):
                pm = re.search(r"\(([^)]*)\)\s*$", rest)
                params = [_eval_expression(p) for p in pm.group(1).split(",")]
                rest = rest[: pm.start()]
            qubits = [int(q) for q in re.findall(r"q\[(\d+)\]", rest)]
            gates.append(Gate(gate_map.get(name, name.lower()), params, qubits))
            continue

    if num_qubits is None or num_clbits is None:
        raise ValueError("originq target missing QINIT/CREG")
    return Circuit(num_qubits, num_clbits, gates, measures)


def parse_target(text: str, target: str) -> Circuit:
    if target == "spinq":

        return parse(text)
    if target == "braket":
        return parse_braket(text)
    if target == "originq":
        return parse_originq(text)
    raise ValueError("unsupported target: %s" % target)


"""Hidden-circuit-like generators (all using only the 12-gate whitelist)."""


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


import re
from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #
@dataclass
class Reg:
    index: int  # 1..9


@dataclass
class CBit:
    index: int  # 0..


@dataclass
class IntLit:
    value: int


@dataclass
class Neg:
    operand: object


@dataclass
class BinOp:
    op: str  # "+" or "-"
    left: object
    right: object


@dataclass
class Cond:
    op: str  # "==" or "!="
    left: object
    right: object


@dataclass
class Assign:
    var: Reg
    expr: object


@dataclass
class If:
    cond: Cond
    then: list
    else_: list


# --------------------------------------------------------------------------- #
# Lexer / parser for the classical block
# --------------------------------------------------------------------------- #
@dataclass
class _Token:
    kind: str
    value: str


_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<COMMENT>//[^\n]*)
  | (?P<CBIT>c\[[0-9]+\])
  | (?P<REG>r[1-9])
  | (?P<IF>if)
  | (?P<ELSE>else)
  | (?P<NUM>[0-9]+)
  | (?P<EQEQ>==)
  | (?P<NEQ>!=)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<LBRACE>\{)
  | (?P<RBRACE>\})
  | (?P<ASSIGN>=)
  | (?P<PLUS>\+)
  | (?P<MINUS>-)
  | (?P<SEMI>;)
    """,
    re.VERBOSE,
)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError("unexpected character at %d: %r" % (pos, text[pos]))
        pos = m.end()
        if m.lastgroup in ("WS", "COMMENT"):
            continue
        tokens.append(_Token(m.lastgroup, m.group()))
    tokens.append(_Token("EOF", ""))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token:
        return self.tokens[self.pos]

    def next(self) -> _Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> _Token:
        tok = self.next()
        if tok.kind != kind:
            raise ValueError("expected %s but got %s" % (kind, tok.kind))
        return tok

    def parse_program(self) -> list:
        stmts = []
        while self.peek().kind != "EOF":
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        if self.peek().kind == "IF":
            return self.parse_if()
        return self.parse_assign()

    def parse_assign(self) -> Assign:
        var = self.parse_reg()
        self.expect("ASSIGN")
        expr = self.parse_expr()
        self.expect("SEMI")
        return Assign(var, expr)

    def parse_reg(self) -> Reg:
        tok = self.expect("REG")
        return Reg(int(tok.value[1:]))

    def parse_if(self) -> If:
        self.expect("IF")
        self.expect("LPAREN")
        cond = self.parse_cond()
        self.expect("RPAREN")
        then = self.parse_block()
        else_ = []
        if self.peek().kind == "ELSE":
            self.next()
            else_ = self.parse_block()
        return If(cond, then, else_)

    def parse_block(self) -> list:
        self.expect("LBRACE")
        stmts = []
        while self.peek().kind != "RBRACE":
            stmts.append(self.parse_statement())
        self.expect("RBRACE")
        return stmts

    def parse_cond(self) -> Cond:
        left = self.parse_expr()
        op_tok = self.next()
        if op_tok.kind == "EQEQ":
            op = "=="
        elif op_tok.kind == "NEQ":
            op = "!="
        else:
            raise ValueError("expected comparison operator, got %s" % op_tok.kind)
        right = self.parse_expr()
        return Cond(op, left, right)

    def parse_expr(self):
        left = self.parse_term()
        while self.peek().kind in ("PLUS", "MINUS"):
            op_tok = self.next()
            op = "+" if op_tok.kind == "PLUS" else "-"
            right = self.parse_term()
            left = BinOp(op, left, right)
        return left

    def parse_term(self):
        if self.peek().kind == "MINUS":
            self.next()
            return Neg(self.parse_term())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUM":
            self.next()
            return IntLit(int(tok.value))
        if tok.kind == "REG":
            return self.parse_reg()
        if tok.kind == "CBIT":
            self.next()
            return CBit(int(re.search(r"\d+", tok.value).group()))
        if tok.kind == "LPAREN":
            self.next()
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr
        raise ValueError("unexpected token in expression: %s" % tok.kind)


def _parse_classical(body: str) -> list:
    return _Parser(_tokenize(body)).parse_program()


# --------------------------------------------------------------------------- #
# Code generation
# --------------------------------------------------------------------------- #
class _Alloc:
    def __init__(self, first_free: int):
        self.pool = ["x%d" % i for i in range(first_free, 32)]
        self.used: set[str] = set()

    def alloc(self) -> str:
        for reg in self.pool:
            if reg not in self.used:
                self.used.add(reg)
                return reg
        raise RuntimeError("out of scratch registers")

    def free(self, reg: str) -> None:
        self.used.discard(reg)


def _reg_name(expr) -> str:
    if isinstance(expr, Reg):
        return "x%d" % expr.index
    if isinstance(expr, CBit):
        return "x%d" % (10 + expr.index)
    raise ValueError("not a register-like expression")


def _gen_expr(expr, dest: str, alloc: _Alloc, out: list[str]) -> None:
    if isinstance(expr, IntLit):
        out.append("li %s, %d" % (dest, expr.value))
    elif isinstance(expr, (Reg, CBit)):
        out.append("add %s, %s, x0" % (dest, _reg_name(expr)))
    elif isinstance(expr, Neg):
        if isinstance(expr.operand, IntLit):
            out.append("li %s, %d" % (dest, -expr.operand.value))
        else:
            _gen_expr(expr.operand, dest, alloc, out)
            out.append("sub %s, x0, %s" % (dest, dest))
    elif isinstance(expr, BinOp):
        _gen_binop(expr, dest, alloc, out)
    else:
        raise ValueError("unsupported expression node")


def _gen_binop(expr: BinOp, dest: str, alloc: _Alloc, out: list[str]) -> None:
    left, right, op = expr.left, expr.right, expr.op
    if isinstance(left, IntLit) and isinstance(right, IntLit):
        value = left.value + right.value if op == "+" else left.value - right.value
        out.append("li %s, %d" % (dest, value))
        return
    if isinstance(right, IntLit):
        _gen_expr(left, dest, alloc, out)
        imm = right.value if op == "+" else -right.value
        out.append("addi %s, %s, %d" % (dest, dest, imm))
        return
    if isinstance(left, IntLit):
        _gen_expr(right, dest, alloc, out)
        if op == "+":
            out.append("addi %s, %s, %d" % (dest, dest, left.value))
        else:
            out.append("sub %s, x0, %s" % (dest, dest))
            out.append("addi %s, %s, %d" % (dest, dest, left.value))
        return
    # Both operands are register-like.
    temp = alloc.alloc()
    _gen_expr(right, temp, alloc, out)
    _gen_expr(left, dest, alloc, out)
    if op == "+":
        out.append("add %s, %s, %s" % (dest, dest, temp))
    else:
        out.append("sub %s, %s, %s" % (dest, dest, temp))
    alloc.free(temp)


def _gen_branch_if_false(cond: Cond, label: str, alloc: _Alloc, out: list[str]) -> None:
    temps: list[str] = []

    def operand_reg(operand) -> str:
        if isinstance(operand, (Reg, CBit)):
            return _reg_name(operand)
        if isinstance(operand, IntLit):
            reg = alloc.alloc()
            out.append("li %s, %d" % (reg, operand.value))
            temps.append(reg)
            return reg
        reg = alloc.alloc()
        _gen_expr(operand, reg, alloc, out)
        temps.append(reg)
        return reg

    left_reg = operand_reg(cond.left)
    right_reg = operand_reg(cond.right)
    if cond.op == "==":
        out.append("bne %s, %s, %s" % (left_reg, right_reg, label))
    else:
        out.append("beq %s, %s, %s" % (left_reg, right_reg, label))
    for reg in temps:
        alloc.free(reg)


def _gen_statements(
    statements: list,
    alloc: _Alloc,
    out: list[str],
    fresh: callable,
) -> None:
    for stmt in statements:
        if isinstance(stmt, Assign):
            _gen_expr(stmt.expr, _reg_name(stmt.var), alloc, out)
        elif isinstance(stmt, If):
            else_label = fresh("else")
            end_label = fresh("end")
            _gen_branch_if_false(stmt.cond, else_label, alloc, out)
            _gen_statements(stmt.then, alloc, out, fresh)
            out.append("j %s" % end_label)
            out.append("%s:" % else_label)
            _gen_statements(stmt.else_, alloc, out, fresh)
            out.append("%s:" % end_label)
        else:
            raise ValueError("unsupported statement node")


def _compile_classical(statements: list, num_clbits: int) -> str:
    alloc = _Alloc(10 + num_clbits)
    out: list[str] = []
    counter = [0]

    def fresh(prefix: str) -> str:
        counter[0] += 1
        return ".L_%s_%d" % (prefix, counter[0])

    _gen_statements(statements, alloc, out, fresh)
    for reg in alloc.pool:
        out.append("addi %s, x0, 0" % reg)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Hybrid-QASM splitting
# --------------------------------------------------------------------------- #
def _extract_classical(text: str) -> tuple[str, list[str]]:
    quantum_parts: list[str] = []
    classical_bodies: list[str] = []
    i = 0
    n = len(text)
    keyword = "classical"
    while True:
        idx = text.find(keyword, i)
        if idx == -1:
            quantum_parts.append(text[i:])
            break
        before_ok = idx == 0 or not (text[idx - 1].isalnum() or text[idx - 1] == "_")
        after = idx + len(keyword)
        after_ok = after < n and (text[after].isspace() or text[after] == "{")
        if not (before_ok and after_ok):
            quantum_parts.append(text[i:after])
            i = after
            continue
        quantum_parts.append(text[i:idx])
        brace = text.find("{", after)
        if brace == -1:
            raise ValueError("classical block missing '{'")
        depth = 0
        j = brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n:
            raise ValueError("unbalanced braces in classical block")
        classical_bodies.append(text[brace + 1 : j])
        i = j + 1
    return "".join(quantum_parts), classical_bodies


def _parse_creg_size(text: str) -> int:
    m = re.search(r"creg\s+\w+\s*\[\s*(\d+)\s*\]", text)
    return int(m.group(1)) if m else 0


def _parse_quantum_ops(text: str) -> list[str]:
    ops: list[str] = []
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if re.match(r"(OPENQASM|include|qreg|creg|barrier)\b", line):
            continue
        m = re.match(
            r"measure\s+\w+\s*\[\s*(\d+)\s*\]\s*->\s*\w+\s*\[\s*(\d+)\s*\]\s*;",
            line,
        )
        if m:
            ops.append("measure q[%s] -> c[%s]" % (m.group(1), m.group(2)))
            continue
        m = re.match(r"([a-zA-Z][a-zA-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*);", line)
        if m:
            name = m.group(1)
            params = m.group(2)
            qubits = [int(x) for x in re.findall(r"q\[(\d+)\]", m.group(3))]
            args = ", ".join("q[%d]" % q for q in qubits)
            if params is not None:
                ops.append("%s(%s) %s" % (name, params.strip(), args))
            else:
                ops.append("%s %s" % (name, args))
            continue
    return ops


def compile_hybrid(hybrid_qasm_str: str) -> tuple[list[str], str]:
    """Return (quantum operation sequence, RISC-V assembly text)."""
    quantum_text, classical_bodies = _extract_classical(hybrid_qasm_str)
    num_clbits = _parse_creg_size(hybrid_qasm_str)
    quantum_ops = _parse_quantum_ops(quantum_text)

    statements = []
    for body in classical_bodies:
        statements.extend(_parse_classical(body))

    assembly = _compile_classical(statements, num_clbits)
    return quantum_ops, assembly



"""Real SDK runners for `run()`, with a zero-dependency simulator fallback.

The organizer grades L1 semantic equivalence by simulating your `transpile()`
output itself, so these runners are mainly for (a) the public self-check and
(b) real-machine evidence. Each runner raises if its SDK is missing, and the
adapter falls back to the built-in simulator in that case.
"""


from typing import Dict



def run_braket(qasm_str: str, shots: int) -> Dict[str, int]:
    """Run via AWS Braket LocalSimulator (OpenQASM 3)."""
    from braket.devices import LocalSimulator
    from braket.ir.openqasm import Program

    source = emit(parse(qasm_str), "braket")
    device = LocalSimulator()
    result = device.run(Program(source=source), shots=shots).result()
    raw = dict(result.measurement_counts)
    # Braket orders keys with q[0] leftmost by default; our schema wants c[0]
    # rightmost (little-endian), so reverse each key. Verify with an asymmetric
    # state (e.g. |01>) if you switch SDK versions.
    return {key[::-1]: value for key, value in raw.items()}


def run_spinq(qasm_str: str, shots: int) -> Dict[str, int]:
    """Run via SpinQit (Taurus local simulator), best-effort.

    NOTE: this maps the 12-gate whitelist to SpinQit gate objects and has not
    been exercised against the SDK in this environment. Verify on Python 3.10
    (`uv pip install spinqit`) before relying on it for real-machine evidence.
    """
    import spinqit as sp

    circ = parse(qasm_str)
    circuit = sp.Circuit()
    q = circuit.allocateQubits(circ.num_qubits)
    c = circuit.allocateClbits(circ.num_clbits)

    no_param = {
        "h": sp.H,
        "x": sp.X,
        "s": sp.S,
        "sdg": sp.SDG,
        "t": sp.T,
        "tdg": sp.TDG,
        "cx": sp.CX,
        "swap": sp.SWAP,
        "ccx": sp.CCX,
    }

    for gate in circ.gates:
        name = gate.name
        if name in ("rz", "ry"):
            g = sp.RZ if name == "rz" else sp.RY
            circuit << (g, q[gate.qubits[0]], gate.params[0])
        elif name == "cu1":
            circuit << (sp.CP, (q[gate.qubits[0]], q[gate.qubits[1]]), gate.params[0])
        elif len(gate.qubits) == 1:
            circuit << (no_param[name], q[gate.qubits[0]])
        else:
            circuit << (no_param[name], tuple(q[i] for i in gate.qubits))

    for qubit, clbit in circ.measures:
        circuit << (sp.MEASURE, (q[qubit], c[clbit]))

    result = sp.BasicSimulator().run(circuit, shots=shots)
    counts = dict(result.counts)
    # SpinQit orders keys with q[0] leftmost by default; normalize to little.
    return {key[::-1]: value for key, value in counts.items()}


def run_real(qasm_str: str, target: str, shots: int) -> Dict[str, int]:
    if target == "braket":
        return run_braket(qasm_str, shots)
    if target == "spinq":
        return run_spinq(qasm_str, shots)
    if target == "originq":
        raise NotImplementedError("originq requires pyqpanda + account token")
    raise ValueError("unsupported target: %s" % target)


"""L2: `agent_chat` — natural-language -> QASM / fix / backend selection.

Reads the `LOOMQ_LLM_*` environment variables and calls any OpenAI-compatible
chat-completions endpoint. A "generate -> self-verify -> retry" loop validates
generated QASM with the L1 engine before returning.
"""


import json
import os
import re
import urllib.error
import urllib.request



_REQUIRED_ENV = ("LOOMQ_LLM_BASE_URL", "LOOMQ_LLM_API_KEY", "LOOMQ_LLM_MODEL")

_BACKENDS = [
    {"id": "spinq_taurus_simulator", "platform": "spinq", "kind": "simulator", "max_qubits": 24, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "spinq_cloud_qpu", "platform": "spinq", "kind": "qpu", "max_qubits": 8, "queue": "minutes_to_hours", "cost": "free_quota", "requires_account": True},
    {"id": "originq_local_simulator", "platform": "originq", "kind": "simulator", "max_qubits": 30, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "originq_wukong", "platform": "originq", "kind": "qpu", "max_qubits": 72, "queue": "hours", "cost": "free_quota", "requires_account": True},
    {"id": "braket_local_simulator", "platform": "braket", "kind": "simulator", "max_qubits": 25, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "braket_cloud", "platform": "braket", "kind": "cloud", "max_qubits": 34, "queue": "minutes_to_hours", "cost": "paid", "requires_account": True},
]


def _config() -> dict:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "missing required LoomQ L2 environment variable(s): " + ", ".join(missing)
        )
    try:
        timeout = float(os.environ.get("LOOMQ_LLM_TIMEOUT_SECONDS", "120"))
        max_output = int(os.environ.get("LOOMQ_LLM_MAX_OUTPUT_TOKENS", "4096"))
    except ValueError as exc:
        raise RuntimeError("invalid LoomQ L2 numeric environment variable") from exc
    if timeout <= 0 or max_output <= 0:
        raise RuntimeError("LoomQ L2 timeout and output-token limit must be positive")
    return {
        "base_url": os.environ["LOOMQ_LLM_BASE_URL"].rstrip("/"),
        "api_key": os.environ["LOOMQ_LLM_API_KEY"],
        "model": os.environ["LOOMQ_LLM_MODEL"],
        "timeout": timeout,
        "max_output": max_output,
    }


def _chat(messages: list[dict], config: dict) -> str:
    payload = {
        "model": config["model"],
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": config["max_output"],
    }
    if config["model"] == "deepseek-v4-flash":
        payload["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        config["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError("LoomQ L2 API returned HTTP %d" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("LoomQ L2 API is unreachable") from exc
    return data["choices"][0]["message"]["content"]


def _backend_table() -> list[dict]:
    return _BACKENDS


def _system_prompt() -> str:
    backends = _backend_table()
    table = "\n".join(
        "- %s | kind=%s | max_qubits=%d | queue=%s | cost=%s | account=%s"
        % (b["id"], b["kind"], b["max_qubits"], b["queue"], b["cost"], b["requires_account"])
        for b in backends
    )
    return (
        "You are LoomQ Agent, a quantum-circuit assistant.\n"
        "You output ONLY one of two things, no markdown fences and no extra prose:\n"
        "1. If the user wants to create, run, generate, or fix a quantum circuit, "
        "output ONLY a valid OpenQASM 2.0 program that starts with `OPENQASM 2.0;` "
        "and includes `include \"qelib1.inc\";`, qreg/creg declarations and measure "
        "statements. Use only these gates: h x s sdg t tdg rz(angle) ry(angle) cx "
        "cu1(angle) swap ccx. Counts are little-endian (c[0] is the rightmost bit).\n"
        "2. If the user wants to choose/recommend a backend/platform, output ONLY the "
        "exact backend id, chosen from this table by max qubits, queue, cost and "
        "account requirement:\n"
        + table
        + "\n"
        "For a circuit request, prefer the simplest correct circuit that realizes "
        "the stated target state."
    )


def _extract_qasm(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r"```[a-zA-Z0-9_]*\n?|```", "", text)
    m = re.search(r"OPENQASM\s+2\.0;.*?(?=\Z)", cleaned, re.DOTALL)
    return m.group(0).strip() if m else None


def _validate(qasm: str) -> str | None:
    try:
        simulate(parse(qasm), 16)
        return None
    except Exception as exc:  # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)


def _extract_backend_id(text: str) -> str | None:
    for backend in _backend_table():
        if backend["id"] in text:
            return backend["id"]
    return None


def _fallback_backend(prompt: str) -> str | None:
    """Deterministic fallback if the model returns no canonical id."""
    numbers = [int(x) for x in re.findall(r"\d+", prompt)]
    n_qubits = max(numbers) if numbers else 0
    wants_sim = bool(re.search(r"模拟器|simulator|本地|local", prompt, re.I))
    wants_free = bool(re.search(r"免费|free|不花钱|free quota|free_quota", prompt, re.I))
    wants_paid = bool(re.search(r"付费|paid", prompt, re.I))
    wants_no_queue = bool(re.search(r"零排队|不排队|无排队|no queue|立即|马上|立刻", prompt, re.I))
    wants_qpu = bool(re.search(r"真机|量子芯片|qpu|超导|核磁|芯片|machine|hardware|chip|real device", prompt, re.I))
    wants_no_account = bool(re.search(r"无账号|无需账号|no account|不注册", prompt, re.I))

    candidates = _backend_table()
    if wants_sim:
        candidates = [b for b in candidates if b["kind"] == "simulator"]
    elif wants_qpu:
        candidates = [b for b in candidates if b["kind"] in ("qpu", "cloud")]
    if wants_free:
        candidates = [b for b in candidates if b["cost"] in ("free", "free_quota")]
    if wants_paid:
        candidates = [b for b in candidates if b["cost"] == "paid"]
    if wants_no_queue:
        candidates = [b for b in candidates if b["queue"] == "none"]
    if wants_no_account:
        candidates = [b for b in candidates if not b["requires_account"]]
    candidates = [b for b in candidates if b["max_qubits"] >= n_qubits]
    if candidates:
        # Prefer the recommended default local simulator, then no-account,
        # then no-queue, then free.
        def preference(b):
            return (
                b["id"] != "braket_local_simulator",
                b["requires_account"],
                b["queue"] != "none",
                b["cost"] not in ("free", "free_quota"),
            )

        candidates.sort(key=preference)
        return candidates[0]["id"]
    return None


def agent_chat(prompt: str) -> str:
    config = _config()
    system = _system_prompt()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    reply = _chat(messages, config)
    qasm = _extract_qasm(reply)
    if qasm:
        for _ in range(3):
            error = _validate(qasm)
            if error is None:
                return qasm
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": "That QASM is invalid: %s. Output ONLY the corrected "
                    "OpenQASM 2.0 program." % error,
                }
            )
            reply = _chat(messages, config)
            qasm = _extract_qasm(reply)
            if not qasm:
                break
        return qasm if qasm else reply.strip()

    backend_id = _extract_backend_id(reply) or _fallback_backend(prompt)
    if backend_id:
        return backend_id

    messages.append({"role": "assistant", "content": reply})
    messages.append(
        {
            "role": "user",
            "content": "Output ONLY either an OpenQASM 2.0 program or one exact "
            "backend id from the table.",
        }
    )
    reply = _chat(messages, config)
    return (_extract_qasm(reply) or _extract_backend_id(reply) or _fallback_backend(prompt) or reply).strip()


"""LoomQ L1 submission adapter (skeleton).

Implements the fixed contract functions `transpile` and `run` so the public
`evaluator.py` can run immediately. `agent_chat` and `compile_hybrid` remain
unimplemented until you choose to enter L2/L3.
"""


import uuid
from datetime import datetime, timezone
from typing import Any, Dict



SUPPORTED_TARGETS = ("spinq", "originq", "braket")

_BACKEND_IDS = {
    "spinq": "spinq_taurus_simulator",
    "originq": "originq_local_simulator",
    "braket": "braket_local_simulator",
}


def transpile(qasm_str: str, target: str) -> str:
    """Translate OpenQASM 2.0 into the target backend's native representation."""
    if target not in SUPPORTED_TARGETS:
        raise ValueError("unsupported target: %s" % target)
    return emit(parse(qasm_str), target)


def _circuit_depth(circ) -> int:
    # Greedy layer scheduler: a valid (not necessarily minimal) depth.
    last_layer = [-1] * circ.num_qubits
    depth = 0
    for gate in circ.gates:
        layer = max((last_layer[q] + 1) for q in gate.qubits)
        for q in gate.qubits:
            last_layer[q] = layer
        depth = max(depth, layer + 1)
    return depth


def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
    """Execute a circuit and return the unified result schema."""
    if target not in SUPPORTED_TARGETS:
        raise ValueError("unsupported target: %s" % target)
    circuit = parse(qasm_str)
    try:
        counts = run_real(qasm_str, target, shots)
    except Exception:  # noqa: BLE001 - SDK missing or unverified -> fallback
        counts = simulate(circuit, shots)
    return {
        "backend": _BACKEND_IDS[target],
        "job_id": uuid.uuid4().hex,
        "shots": shots,
        "counts": counts,
        "bit_order": "little",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": {
            "transpiled_gates": len(circuit.gates),
            "depth": _circuit_depth(circuit),
        },
    }

