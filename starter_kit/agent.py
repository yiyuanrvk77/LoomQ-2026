"""L2 智能体：自然语言 -> QASM / 纠错 / 后端选型，读 LOOMQ_LLM_* 配置。"""

import json
import re
from pathlib import Path

try:
    from . import llm_client
    from .qasm_parser import parse
    from .simulator import simulate
except ImportError:  # 脚本方式直接运行时无包上下文
    import llm_client
    from qasm_parser import parse
    from simulator import simulate


def _chat_reply(messages: list[dict]) -> str:
    """调用官方 llm_client 做一次补全，返回 assistant 文本。"""
    return llm_client.chat_completion(messages)["choices"][0]["message"]["content"]


def _backend_table() -> list[dict]:
    """Load the official backend capability table (single source of truth)."""
    path = Path(__file__).with_name("backend_capabilities.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["backends"]


def _valid_backend_ids() -> set[str]:
    """Canonical backend identifiers from the official capability table."""
    return {backend["id"] for backend in _backend_table()}


def _bare_backend_id(reply: str) -> str | None:
    """Accept a reply that directly names a canonical backend identifier.

    Some models occasionally answer a backend-selection prompt with the bare
    ``id`` from the capability table instead of the required JSON envelope.
    Treat any reply that contains exactly one of those identifiers as the
    final answer instead of burning all three retries.
    """
    if not isinstance(reply, str):
        return None
    valid = _valid_backend_ids()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", reply):
        if token in valid:
            return token
    return None


def _system_prompt() -> str:
    return (
        "You are LoomQ Agent. Understand the user's semantic intent rather than "
        "matching keywords. Return exactly one JSON object, without markdown or prose.\n"
        "For a circuit generation or circuit repair request, return:\n"
        '{"task":"circuit","qasm":"<complete OpenQASM 2.0 program>"}\n'
        "The program must start with OPENQASM 2.0;, include qelib1.inc, declare one "
        "qreg and one creg, end with measurement, and use only: h, x, s, sdg, t, "
        "tdg, rz(angle), ry(angle), cx, cu1(angle), swap, ccx. Preserve the user's "
        "declared target state when repairing code. Use c[0] as the rightmost bit.\n"
        "For a backend recommendation request, do not choose from memory. Extract "
        "constraints for LoomQ's deterministic capability-table tool and return:\n"
        '{"task":"backend","requirements":{"min_qubits":0,'
        '"platform":"any","device":"any","queue":"any",'
        '"cost":"any","account":"any"}}\n'
        "Allowed platform values: any, spinq, originq, braket. Allowed device values: "
        "any, simulator, qpu, cloud. Allowed queue values: any, none. Allowed cost "
        "values: any, free, free_quota, no_paid, paid. Use no_paid when the user "
        "accepts free quota but does not want a paid backend. Allowed account values: "
        "any, not_required, required. Never invent another enum value."
    )


def _extract_qasm(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r"```[a-zA-Z0-9_]*\n?|```", "", text)
    m = re.search(r"OPENQASM\s+2\.0;.*?(?=\Z)", cleaned, re.DOTALL)
    return m.group(0).strip() if m else None


def _describe_error(exc: Exception) -> str:
    """把底层异常翻译成对模型更有指导意义的中文提示。"""
    msg = str(exc)
    name = type(exc).__name__
    hints = []
    if "unexpected character" in msg or "unexpected token" in msg:
        hints.append("QASM 里有非法字符或无法解析的符号（检查标点、拼写和门名）")
    if "expected" in msg and "got" in msg:
        hints.append("语句结构不完整或顺序不对（检查声明、分号、括号配对）")
    if "out of range" in msg or "index" in msg.lower():
        hints.append("引用了不存在的量子比特或经典比特（q[n]/c[n] 越界）")
    if "unknown" in msg.lower() or "unsupported" in msg.lower():
        hints.append("使用了不在 12 门白名单里的门或语法")
    if "measure" in msg.lower():
        hints.append("measure 语法有误（应为 measure q[i] -> c[j];）")
    if "supports 1 to 20" in msg:
        hints.append("电路超过本地自验的 20 比特上限，请缩小电路或改用后端选型")
    detail = "；".join(hints) if hints else name
    return detail + "。原始错误：" + msg


def _validate(qasm: str) -> str | None:
    try:
        circuit = parse(qasm)
        if not circuit.measures:
            raise ValueError("the generated circuit must include measurement")
        simulate(circuit, 16)
        return None
    except Exception as exc:  # noqa: BLE001
        return _describe_error(exc)


def _extract_json_object(text: str) -> dict | None:
    """Extract the first complete JSON object without trusting surrounding prose."""
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _model_envelope(reply: str) -> dict | None:
    data = _extract_json_object(reply)
    if data and data.get("task") in {"circuit", "backend"}:
        return data
    qasm = _extract_qasm(reply)
    if qasm:
        return {"task": "circuit", "qasm": qasm}
    return None


_REQUIREMENT_ENUMS = {
    "platform": {"any", "spinq", "originq", "braket"},
    "device": {"any", "simulator", "qpu", "cloud"},
    "queue": {"any", "none"},
    "cost": {"any", "free", "free_quota", "no_paid", "paid"},
    "account": {"any", "not_required", "required"},
}


def _normalize_requirements(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("backend requirements must be a JSON object")
    raw_qubits = value.get("min_qubits", 0)
    if type(raw_qubits) is int:
        min_qubits = raw_qubits
    elif type(raw_qubits) is float and raw_qubits.is_integer():
        min_qubits = int(raw_qubits)
    elif isinstance(raw_qubits, str) and re.fullmatch(r"\s*\d+\s*", raw_qubits):
        min_qubits = int(raw_qubits)
    else:
        raise ValueError("min_qubits must be a non-negative integer")
    if min_qubits < 0 or min_qubits > 100_000:
        raise ValueError("min_qubits must be between 0 and 100000")
    normalized = {"min_qubits": min_qubits}
    for field, allowed in _REQUIREMENT_ENUMS.items():
        item = value.get(field, "any")
        if not isinstance(item, str) or item not in allowed:
            raise ValueError("invalid %s requirement: %r" % (field, item))
        normalized[field] = item
    return normalized


def _candidate_backends(requirements: dict) -> list[dict]:
    """Filter the official capability table using model-extracted constraints."""
    candidates = list(_backend_table())
    if requirements["platform"] != "any":
        candidates = [b for b in candidates if b["platform"] == requirements["platform"]]
    if requirements["device"] != "any":
        candidates = [b for b in candidates if b["kind"] == requirements["device"]]
    if requirements["queue"] == "none":
        candidates = [b for b in candidates if b["queue"] == "none"]
    if requirements["cost"] == "no_paid":
        candidates = [b for b in candidates if b["cost"] != "paid"]
    elif requirements["cost"] != "any":
        candidates = [b for b in candidates if b["cost"] == requirements["cost"]]
    if requirements["account"] == "not_required":
        candidates = [b for b in candidates if not b["requires_account"]]
    elif requirements["account"] == "required":
        candidates = [b for b in candidates if b["requires_account"]]
    return [b for b in candidates if b["max_qubits"] >= requirements["min_qubits"]]


def _pick_best_backend(candidates: list[dict]) -> str | None:
    """从候选集中选默认最优（默认本地模拟器 > 免账号 > 零排队 > 免费）。"""
    if not candidates:
        return None

    def preference(b):
        return (
            b["id"] != "braket_local_simulator",
            b["requires_account"],
            b["queue"] != "none",
            b["cost"] not in ("free", "free_quota"),
        )

    candidates.sort(key=preference)
    return candidates[0]["id"]


def agent_chat(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    system = _system_prompt()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt.strip()}]
    last_error = "model response did not contain a valid task envelope"

    for _ in range(3):
        try:
            reply = _chat_reply(messages)
        except Exception as exc:  # noqa: BLE001 - transport/parse failures are retryable
            last_error = "%s: %s" % (type(exc).__name__, exc)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous model call failed with a transient error "
                        "(%s). Retry and return exactly one JSON object matching "
                        "the required schema."
                    ) % last_error,
                }
            )
            continue
        envelope = _model_envelope(reply)
        if envelope is None:
            bare_backend = _bare_backend_id(reply)
            if bare_backend:
                return bare_backend
        if envelope and envelope["task"] == "backend":
            try:
                requirements = _normalize_requirements(envelope.get("requirements"))
            except ValueError as exc:
                last_error = str(exc)
            else:
                candidates = _candidate_backends(requirements)
                if not candidates:
                    return "无解：backend_capabilities.json 中没有后端能同时满足这些约束。"
                return _pick_best_backend(candidates)
        elif envelope and envelope["task"] == "circuit":
            qasm = _extract_qasm(envelope.get("qasm", ""))
            if qasm:
                error = _validate(qasm)
                if error is None:
                    return qasm
                last_error = error
            else:
                last_error = "circuit envelope contains no complete OpenQASM 2.0 program"

        messages.append({"role": "assistant", "content": reply})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous response failed deterministic validation: %s. "
                    "Return exactly one corrected JSON object matching the required schema."
                )
                % last_error,
            }
        )

    raise RuntimeError("LoomQ Agent could not produce a validated result: %s" % last_error)
