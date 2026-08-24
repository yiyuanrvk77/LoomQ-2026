"""OpenQASM 2.0 解析器：把题面 12 门白名单子集解析成统一中间表示（IR）。"""

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
    value = _eval_param(ast.parse(text, mode="eval"))
    if not math.isfinite(value):
        raise ValueError("gate parameter must be finite")
    return value


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


_GATE_WHITELIST = {"h", "x", "s", "sdg", "t", "tdg", "rz", "ry", "cx", "cu1", "swap", "ccx"}
_GATE_ARITY = {
    "h": 1, "x": 1, "s": 1, "sdg": 1, "t": 1, "tdg": 1,
    "rz": 1, "ry": 1, "cx": 2, "cu1": 2, "swap": 2, "ccx": 3,
}


def parse(qasm: str) -> Circuit:
    if not isinstance(qasm, str) or not qasm.strip():
        raise ValueError("QASM source must be a non-empty string")

    num_qubits: int | None = None
    num_clbits: int | None = None
    qreg_name: str | None = None
    creg_name: str | None = None
    gates: list[Gate] = []
    measures: list[tuple[int, int]] = []
    operation_started = False
    measurement_started = False

    without_comments = "\n".join(_strip_comment(raw) for raw in qasm.splitlines())
    statements = [part.strip() + ";" for part in without_comments.split(";") if part.strip()]
    if not statements or re.fullmatch(r"OPENQASM\s+2\.0\s*;", statements[0], re.I) is None:
        raise ValueError("program must start with OPENQASM 2.0;")

    include_seen = False
    for statement_index, line in enumerate(statements):
        if re.fullmatch(r"OPENQASM\s+2\.0\s*;", line, re.I):
            if statement_index != 0:
                raise ValueError("duplicate OPENQASM declaration")
            continue
        if re.fullmatch(r'include\s+"qelib1\.inc"\s*;', line, re.I):
            if include_seen:
                raise ValueError('duplicate include "qelib1.inc"')
            if num_qubits is not None or num_clbits is not None or operation_started:
                raise ValueError('include "qelib1.inc" must precede register declarations')
            include_seen = True
            continue
        if re.match(r"OPENQASM\b", line, re.I) or re.match(r"include\b", line, re.I):
            raise ValueError("only OpenQASM 2.0 with qelib1.inc is supported")
        barrier = re.fullmatch(r"barrier\s+([^;]+);", line, re.I)
        if barrier:
            operation_started = True
            if num_qubits is None or qreg_name is None:
                raise ValueError("barrier before qreg declaration")
            operands = [item.strip() for item in barrier.group(1).split(",")]
            if any(not item for item in operands):
                raise ValueError("barrier operand list contains an empty operand")
            for operand in operands:
                if operand == qreg_name:
                    continue
                ref = re.fullmatch(r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]", operand)
                if ref is None or ref.group(1) != qreg_name:
                    raise ValueError("barrier operands must reference the declared qreg")
                qubit = int(ref.group(2))
                if not 0 <= qubit < num_qubits:
                    raise ValueError(
                        "barrier qubit index out of range: q[%d] (qreg has %d qubits)"
                        % (qubit, num_qubits)
                    )
            continue

        m = re.fullmatch(r"qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;", line, re.I)
        if m:
            if operation_started:
                raise ValueError("qreg declaration must precede circuit operations")
            if num_qubits is not None:
                raise ValueError("only one qreg declaration is supported")
            qreg_name = m.group(1)
            num_qubits = int(m.group(2))
            if num_qubits <= 0:
                raise ValueError("qreg size must be positive")
            continue

        m = re.fullmatch(r"creg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;", line, re.I)
        if m:
            if operation_started:
                raise ValueError("creg declaration must precede circuit operations")
            if num_clbits is not None:
                raise ValueError("only one creg declaration is supported")
            creg_name = m.group(1)
            num_clbits = int(m.group(2))
            if num_clbits <= 0:
                raise ValueError("creg size must be positive")
            continue

        m = re.fullmatch(r"measure\s+([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)\s*;", line, re.I)
        if m:
            operation_started = True
            measurement_started = True
            if num_qubits is None or num_clbits is None:
                raise ValueError("measure before register declaration")
            if m.group(1) != qreg_name or m.group(2) != creg_name:
                raise ValueError("measure must use the declared qreg and creg")
            if num_qubits != num_clbits:
                raise ValueError("whole-register measurement requires equal register sizes")
            measures.extend((i, i) for i in range(num_qubits))
            continue
        m = re.fullmatch(
            r"measure\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*->\s*([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;",
            line,
            re.I,
        )
        if m:
            operation_started = True
            measurement_started = True
            if num_qubits is None or num_clbits is None:
                raise ValueError("measure before register declaration")
            if m.group(1) != qreg_name or m.group(3) != creg_name:
                raise ValueError("measure must use the declared qreg and creg")
            measures.append((int(m.group(2)), int(m.group(4))))
            continue

        m = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*?)\s*;", line)
        if m:
            if measurement_started:
                raise ValueError("mid-circuit measurement is not supported")
            operation_started = True
            if num_qubits is None or qreg_name is None:
                raise ValueError("gate before qreg declaration")
            raw_name = m.group(1)
            if raw_name != raw_name.lower():
                raise ValueError("OpenQASM gate names are case-sensitive and must be lowercase")
            name = raw_name
            param_text = m.group(2)
            if param_text is not None and not param_text.strip():
                raise ValueError("empty gate parameter list")
            params = [_eval_expression(p) for p in param_text.split(",")] if param_text else []
            raw_operands = m.group(3).split(",")
            if any(not operand.strip() for operand in raw_operands):
                raise ValueError("gate operand list contains an empty operand")
            operands = [operand.strip() for operand in raw_operands]
            qubits = []
            for operand in operands:
                ref = re.fullmatch(r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]", operand)
                if ref is None or ref.group(1) != qreg_name:
                    raise ValueError("gate operands must reference the declared qreg")
                qubits.append(int(ref.group(2)))
            if len(set(qubits)) != len(qubits):
                raise ValueError("a gate cannot reference the same qubit more than once")
            gates.append(Gate(name=name, params=params, qubits=qubits))
            continue

        raise ValueError("unrecognized line: %s" % line)

    if num_qubits is None:
        raise ValueError("missing qreg declaration")
    if num_clbits is None:
        raise ValueError("missing creg declaration")
    if qreg_name == creg_name:
        raise ValueError("qreg and creg must use different names")
    if not include_seen:
        raise ValueError('missing include "qelib1.inc";')

    for gate in gates:
        if gate.name not in _GATE_WHITELIST:
            raise ValueError("gate outside the 12-gate whitelist: %s" % gate.name)
        if len(gate.qubits) != _GATE_ARITY[gate.name]:
            raise ValueError(
                "gate %s expects %d qubit(s), got %d"
                % (gate.name, _GATE_ARITY[gate.name], len(gate.qubits))
            )
        if gate.name in ("rz", "ry", "cu1") and len(gate.params) != 1:
            raise ValueError("gate %s requires exactly one angle parameter" % gate.name)
        if gate.name not in ("rz", "ry", "cu1") and gate.params:
            raise ValueError("gate %s does not accept parameters" % gate.name)
        for q in gate.qubits:
            if not 0 <= q < num_qubits:
                raise ValueError(
                    "qubit index out of range: q[%d] (qreg has %d qubits)"
                    % (q, num_qubits)
                )
    for qubit, clbit in measures:
        if not 0 <= qubit < num_qubits:
            raise ValueError("measure qubit index out of range: q[%d]" % qubit)
        if not 0 <= clbit < num_clbits:
            raise ValueError(
                "measure clbit index out of range: c[%d] (creg has %d bits)"
                % (clbit, num_clbits)
            )

    return Circuit(
        num_qubits=num_qubits,
        num_clbits=num_clbits,
        gates=gates,
        measures=measures,
    )
