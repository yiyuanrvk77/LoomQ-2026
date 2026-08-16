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

# 量子概念知识库：概念 -> 一句话解释 + 可运行电路（三本书发散三的轻量版）
_CONCEPTS = [
    {
        "name": "贝尔态",
        "keywords": ["bell", "贝尔", "epr", "爱因斯坦"],
        "explain": "贝尔态是两个量子比特的最大纠缠态：测量时两个比特总是相同（00 或 11，各一半）。它是量子纠缠、隐形传态、超密编码的基石。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];',
    },
    {
        "name": "GHZ 态",
        "keywords": ["ghz", "格林伯格", "greenberger"],
        "explain": "GHZ 态是三个（及以上）量子比特的最大纠缠态，是量子非局域性实验的经典载体。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\nmeasure q[2] -> c[2];',
    },
    {
        "name": "量子叠加",
        "keywords": ["叠加", "superposition"],
        "explain": "叠加是量子比特同时处于 |0⟩ 和 |1⟩ 的能力。H 门把 |0⟩ 变成 (|0⟩+|1⟩)/√2，测量时才坍缩到其中一个。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
    {
        "name": "量子纠缠",
        "keywords": ["纠缠", "entangle"],
        "explain": "纠缠是两个量子比特的关联强到无法用经典比特解释的现象。贝尔态是最简单的纠缠态：测一个比特，另一个立刻确定。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];',
    },
    {
        "name": "量子测量",
        "keywords": ["测量", "measure", "观测"],
        "explain": "测量把量子叠加态坍缩到确定态。测量前叠加态在 |0⟩ 和 |1⟩ 各有概率，测量后只剩一个确定结果。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
    {
        "name": "量子退相干",
        "keywords": ["退相干", "decoherence", "噪声", "noise", "误差"],
        "explain": "退相干是量子态与环境相互作用而丧失量子特性的过程，是真机结果不如理想模拟器的根本原因——叠加态最容易被噪声抹掉。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
]


def _match_concept(prompt: str) -> dict | None:
    """判断 prompt 是否在问量子概念（教育问答，非 L2 三大评测任务）。"""
    if not re.search(
        r"什么是|是什么|啥是|啥叫|解释|讲讲|科普|介绍|meaning|what is|explain",
        prompt,
        re.I,
    ):
        return None
    low = prompt.lower()
    for concept in _CONCEPTS:
        for keyword in concept["keywords"]:
            if keyword.lower() in low:
                return concept
    return None


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
        "the stated target state.\n"
        "IMPORTANT: If the question asks WHICH platform/backend to choose (contains "
        "words like '选哪个平台', '排队', 'which platform', 'backend'), it is a "
        "backend-selection task. NEVER output a circuit for such a question even if "
        "a bit count is mentioned; output ONLY the backend id."
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


def _is_backend_query(prompt: str) -> bool:
    """判断 prompt 是否属于「选后端」意图（任务路由，非答案硬编码）。"""
    return bool(
        re.search(
            r"选.{0,6}(平台|后端|backend|platform)|哪个平台|哪家|排队|no queue|backend|platform",
            prompt,
            re.I,
        )
    )


def _candidate_backends(prompt: str) -> list[dict]:
    """按 prompt 中的约束，从能力表筛出所有满足条件的后端（可能为空）。"""
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
    return candidates


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


def _fallback_backend(prompt: str) -> str | None:
    """Deterministic fallback if the model returns no canonical id."""
    return _pick_best_backend(_candidate_backends(prompt))


def _valid_backend_from_reply(prompt: str, reply: str) -> str | None:
    """从模型回复里提取后端 ID，但仅当它满足 prompt 约束时才返回。"""
    llm_id = _extract_backend_id(reply)
    if not llm_id:
        return None
    valid_ids = {b["id"] for b in _candidate_backends(prompt)}
    return llm_id if llm_id in valid_ids else None


def agent_chat(prompt: str) -> str:
    # 概念问答（教育功能）：问「什么是 X」直接返回解释 + 可运行电路，不调模型
    concept = _match_concept(prompt)
    if concept:
        return concept["explain"] + "\n\n可运行电路（复制到 LoomQ 即可跑）：\n" + concept["qasm"]

    system = _system_prompt()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    reply = _chat_reply(messages)
    # 任务路由：选后端意图优先，即使模型误生成了电路也按选平台处理
    if _is_backend_query(prompt):
        candidates = _candidate_backends(prompt)
        if not candidates:
            return "无解：能力表中没有平台能同时满足这些约束，请放宽比特数、排队或费用要求。"
        return _valid_backend_from_reply(prompt, reply) or _pick_best_backend(candidates)

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

    backend_id = _valid_backend_from_reply(prompt, reply) or _fallback_backend(prompt)
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
    return (_extract_qasm(reply) or _valid_backend_from_reply(prompt, reply) or _fallback_backend(prompt) or reply).strip()
