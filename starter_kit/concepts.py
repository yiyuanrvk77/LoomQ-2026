"""Offline educational concept cards used only by the local web demo."""

import re


_CONCEPTS = (
    {
        "name": "贝尔态",
        "keywords": ("bell", "贝尔", "epr", "爱因斯坦"),
        "explain": "贝尔态是两个量子比特的最大纠缠态：测量时两个比特总是相同（00 或 11，各一半）。它是量子纠缠、隐形传态、超密编码的基石。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];',
    },
    {
        "name": "GHZ 态",
        "keywords": ("ghz", "格林伯格", "greenberger"),
        "explain": "GHZ 态是三个（及以上）量子比特的最大纠缠态，是量子非局域性实验的经典载体。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\nmeasure q[2] -> c[2];',
    },
    {
        "name": "量子叠加",
        "keywords": ("叠加", "superposition"),
        "explain": "叠加让量子比特在测量前保持 |0⟩ 与 |1⟩ 的相干组合。H 门把 |0⟩ 变成 (|0⟩+|1⟩)/√2，测量才给出其中一个结果。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
    {
        "name": "量子纠缠",
        "keywords": ("纠缠", "entangle"),
        "explain": "纠缠是多个量子比特共享一个不可拆成独立部分的联合状态。贝尔态是最简单的例子：两个测量结果呈现经典独立比特无法复现的整体关联。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];',
    },
    {
        "name": "量子测量",
        "keywords": ("测量", "measure", "观测"),
        "explain": "测量把量子态转换成经典结果。一次只得到一个比特串；重复运行得到的频率分布，才是可以和理论概率比较的证据。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
    {
        "name": "量子退相干",
        "keywords": ("退相干", "decoherence", "噪声", "noise", "误差"),
        "explain": "退相干是量子系统与环境耦合后相位关系逐渐丢失的过程。它会削弱叠加和纠缠，是实际硬件偏离理想分布的重要来源。",
        "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];',
    },
)


def concept_answer(prompt: str) -> dict[str, str] | None:
    """Return a local concept card; this is not part of the scored L2 agent."""
    if not isinstance(prompt, str) or not re.search(
        r"什么是|是什么|啥是|啥叫|解释|讲讲|科普|介绍|meaning|what is|explain",
        prompt,
        re.I,
    ):
        return None
    lowered = prompt.lower()
    for concept in _CONCEPTS:
        if any(keyword.lower() in lowered for keyword in concept["keywords"]):
            return {
                "name": concept["name"],
                "explain": concept["explain"],
                "qasm": concept["qasm"],
            }
    return None
