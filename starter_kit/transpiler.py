"""转译层：统一 IR 分别输出 SpinQ / Braket / OriginQ，并支持回读自验。"""

try:
    from .qasm_parser import Circuit, Gate, parse, _eval_expression
except ImportError:  # 脚本方式直接运行时无包上下文
    from qasm_parser import Circuit, Gate, parse, _eval_expression

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
    "sdg": "si",
    "t": "t",
    "tdg": "ti",
    "rz": "rz",
    "ry": "ry",
    "cx": "cnot",
    "cu1": "cphaseshift",
    "swap": "swap",
    "ccx": "ccnot",
}


def _emit_braket(circ: Circuit) -> str:
    lines = [
        "OPENQASM 3.0;",
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
        "h": "h", "x": "x", "s": "s", "sdg": "sdg", "si": "sdg",
        "t": "t", "tdg": "tdg", "ti": "tdg",
        "rz": "rz", "ry": "ry", "cnot": "cx", "cx": "cx", "cp": "cu1",
        "cu1": "cu1", "cphaseshift": "cu1", "swap": "swap", "ccx": "ccx", "ccnot": "ccx",
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

