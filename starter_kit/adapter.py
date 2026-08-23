"""LoomQ 参赛适配器门面：对外暴露固定的契约接口。

内部实现按层拆分到 qasm_parser / simulator / transpiler / backends / agent /
hybrid，本文件只做组装与再导出，保证 `from starter_kit import adapter` 的
既有用法（transpile / run / agent_chat / compile_hybrid）完全不变。
"""

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict

try:
    from .agent import agent_chat
    from .backends import run_backend, run_braket, run_real, run_spinq
    from .circuit_gen import ghz, grover_3, qft, random_circuit
    from .concepts import concept_answer
    from .hybrid import compile_hybrid
    from .qasm_parser import Circuit, Gate, parse
    from .simulator import MAX_SHOTS, Simulator, probabilities, simulate, simulate_with_noise
    from .transpiler import emit, parse_braket, parse_originq, parse_target
except ImportError:  # 脚本方式直接运行时无包上下文
    from agent import agent_chat
    from backends import run_backend, run_braket, run_real, run_spinq
    from circuit_gen import ghz, grover_3, qft, random_circuit
    from concepts import concept_answer
    from hybrid import compile_hybrid
    from qasm_parser import Circuit, Gate, parse
    from simulator import MAX_SHOTS, Simulator, probabilities, simulate, simulate_with_noise
    from transpiler import emit, parse_braket, parse_originq, parse_target

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


def _normalize_backend_counts(
    counts: object, num_clbits: int, shots: int
) -> Dict[str, int]:
    """Validate a vendor SDK result before it enters the public schema."""
    if not isinstance(counts, Mapping) or not counts:
        raise ValueError("backend counts must be a non-empty mapping")
    normalized: Dict[str, int] = {}
    for key, value in counts.items():
        if not isinstance(key, str) or not key or set(key) - {"0", "1"}:
            raise ValueError("backend count keys must be binary strings")
        if len(key) > num_clbits:
            raise ValueError("backend count key is wider than the classical register")
        if isinstance(value, bool):
            raise ValueError("backend count values must be non-negative integers")
        try:
            integer_value = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("backend count values must be non-negative integers") from exc
        if integer_value < 0 or integer_value != value:
            raise ValueError("backend count values must be non-negative integers")
        normalized_key = key.zfill(num_clbits)
        normalized[normalized_key] = normalized.get(normalized_key, 0) + integer_value
    if sum(normalized.values()) != shots:
        raise ValueError("backend counts total must equal shots")
    return normalized


def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
    """Execute a circuit and return the unified result schema."""
    if target not in SUPPORTED_TARGETS:
        raise ValueError("unsupported target: %s" % target)
    if (
        isinstance(shots, bool)
        or not isinstance(shots, int)
        or not 1 <= shots <= MAX_SHOTS
    ):
        raise ValueError(
            "shots must be a positive integer no greater than %d" % MAX_SHOTS
        )
    circuit = parse(qasm_str)
    meta = {
        "transpiled_gates": len(circuit.gates),
        "depth": _circuit_depth(circuit),
        "source": "local_sdk_simulator",
        "is_hardware": False,
    }
    native_job_id = None
    try:
        raw_counts, native_job_id = run_backend(qasm_str, target, shots)
        counts = _normalize_backend_counts(raw_counts, circuit.num_clbits, shots)
        if native_job_id:
            meta["local_sdk_job_id"] = str(native_job_id)
    except Exception as exc:  # noqa: BLE001 - SDK missing/unavailable -> 显式回退并记录原因
        native_job_id = None
        counts = simulate(circuit, shots)
        meta["source"] = "internal_simulator_fallback"
        meta["fallback_reason"] = "%s: %s" % (type(exc).__name__, exc)
    return {
        "backend": _BACKEND_IDS[target],
        "job_id": "local-%s-%s" % (target, native_job_id or uuid.uuid4().hex),
        "shots": shots,
        "counts": counts,
        "bit_order": "little",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
    }


__all__ = [
    "transpile", "run", "agent_chat", "compile_hybrid",
    "concept_answer",
    "parse", "simulate", "simulate_with_noise", "probabilities", "emit", "parse_target",
    "parse_braket", "parse_originq", "ghz", "qft", "grover_3",
    "random_circuit", "run_backend", "run_real", "run_braket", "run_spinq",
    "SUPPORTED_TARGETS", "Circuit", "Gate", "Simulator",
]
