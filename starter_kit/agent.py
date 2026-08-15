"""L2 智能体：自然语言 -> QASM / 纠错 / 后端选型，读 LOOMQ_LLM_* 配置。"""

import re

try:
    from . import llm_client
    from .qasm_parser import parse
    from .simulator import simulate
except ImportError:  # 脚本方式直接运行时无包上下文
    import llm_client
    from qasm_parser import parse
    from simulator import simulate


_BACKENDS = [
    {"id": "spinq_taurus_simulator", "platform": "spinq", "kind": "simulator", "max_qubits": 24, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "spinq_cloud_qpu", "platform": "spinq", "kind": "qpu", "max_qubits": 8, "queue": "minutes_to_hours", "cost": "free_quota", "requires_account": True},
    {"id": "originq_local_simulator", "platform": "originq", "kind": "simulator", "max_qubits": 30, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "originq_wukong", "platform": "originq", "kind": "qpu", "max_qubits": 72, "queue": "hours", "cost": "free_quota", "requires_account": True},
    {"id": "braket_local_simulator", "platform": "braket", "kind": "simulator", "max_qubits": 25, "queue": "none", "cost": "free", "requires_account": False},
    {"id": "braket_cloud", "platform": "braket", "kind": "cloud", "max_qubits": 34, "queue": "minutes_to_hours", "cost": "paid", "requires_account": True},
]


def _chat_reply(messages: list[dict]) -> str:
    """调用官方 llm_client 做一次补全，返回 assistant 文本。"""
    return llm_client.chat_completion(messages)["choices"][0]["message"]["content"]


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
    system = _system_prompt()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    reply = _chat_reply(messages)
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
            reply = _chat_reply(messages)
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
    reply = _chat_reply(messages)
    return (_extract_qasm(reply) or _extract_backend_id(reply) or _fallback_backend(prompt) or reply).strip()

