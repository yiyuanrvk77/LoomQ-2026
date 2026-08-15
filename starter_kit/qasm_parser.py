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

        m = re.match(r"measure\s+\w+\s*->\s*\w+\s*;", line)
        if m:
            if num_qubits is None:
                raise ValueError("measure before qreg declaration")
            measures.extend((i, i) for i in range(num_qubits))
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

