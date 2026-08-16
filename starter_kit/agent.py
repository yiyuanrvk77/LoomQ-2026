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
    detail = "；".join(hints) if hints else name
    return detail + "。原始错误：" + msg


def _validate(qasm: str) -> str | None:
    try:
        simulate(parse(qasm), 16)
        return None
    except Exception as exc:  # noqa: BLE001
        return _describe_error(exc)


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
    wants_qpu = bool(re.search(r"真机|量子芯片|量子硬件|硬件|实体机|qpu|超导|核磁|芯片|machine|hardware|chip|real device|on real", prompt, re.I))
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
        for _ in range(2):
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
