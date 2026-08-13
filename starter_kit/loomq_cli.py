#!/usr/bin/env python3
"""LoomQ Agent CLI —— L2 可运行入口。

用法：和 adapter.py 放在同一目录（starter_kit/），先设置 LOOMQ_LLM_* 环境变量，然后：
    python3 loomq_cli.py
"""

from __future__ import annotations

import sys

try:
    import adapter
except Exception:  # noqa: BLE001
    print("未找到 adapter.py，请把本文件与 adapter.py 放在同一目录。")
    sys.exit(1)


WELCOME = """
============================================================
  LoomQ Agent · 量子接入平权计划
  用一句话，指挥量子计算机。

  试试输入：
    “生成一个 3 比特的 GHZ 纠缠态并全测量”
    “我想运行一个 15 比特、零排队的电路，选哪个平台？”

  输入 help 看更多，输入 quit 退出。
============================================================
"""

HELP = """
你可以这样用：
  1) 生成电路   —— 描述你想制备的态，例如“生成 Bell 态并测量”
  2) 修复电路   —— 贴一段报错的 QASM，说“帮我修好，我要的是贝尔态”
  3) 选择后端   —— 描述比特数/排队/费用约束，例如“15 比特零排队免费”

生成电路后，我会尝试在本地模拟器上自验并展示测量结果分布。
"""


def _looks_like_qasm(text: str) -> bool:
    return "OPENQASM" in text


def _show_counts(counts: dict, shots: int) -> None:
    print("  测量结果分布（shots=%d）：" % shots)
    width = 32
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        value = counts[key]
        bar = "#" * max(1, round(width * value / shots))
        print("    %-8s %s %d (%.1f%%)" % (key, bar, value, 100.0 * value / shots))


def _handle(prompt: str) -> None:
    try:
        reply = adapter.agent_chat(prompt)
    except Exception as exc:  # noqa: BLE001
        print("模型调用失败：%s" % exc)
        print("请检查环境变量 LOOMQ_LLM_BASE_URL / LOOMQ_LLM_API_KEY / LOOMQ_LLM_MODEL。")
        return

    if _looks_like_qasm(reply):
        print("\n已生成 OpenQASM 2.0 电路：\n")
        print(reply)
        try:
            result = adapter.run(reply, "braket", 1024)
            _show_counts(result["counts"], result["shots"])
        except Exception:  # noqa: BLE001
            print("（本地自验未执行：目标后端不可用。）")
    else:
        print("\n" + reply + "\n")


def main() -> None:
    print(WELCOME)
    while True:
        try:
            prompt = input("LoomQ > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            break
        if prompt.lower() in ("help", "?"):
            print(HELP)
            continue
        _handle(prompt)


if __name__ == "__main__":
    main()

