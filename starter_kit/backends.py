"""真实 SDK 执行层（run 用），缺 SDK 时由适配器回退到内置模拟器。"""

try:
    from .qasm_parser import parse
    from .transpiler import emit
except ImportError:  # 脚本方式直接运行时无包上下文
    from qasm_parser import parse
    from transpiler import emit

from typing import Dict



def run_braket(qasm_str: str, shots: int) -> tuple[Dict[str, int], str | None]:
    """Run via AWS Braket LocalSimulator (OpenQASM 3). 返回 (counts, job_id)。"""
    from braket.devices import LocalSimulator
    from braket.ir.openqasm import Program

    source = emit(parse(qasm_str), "braket")
    device = LocalSimulator()
    task = device.run(Program(source=source), shots=shots)
    result = task.result()
    raw = dict(result.measurement_counts)
    # Braket orders keys with q[0] leftmost by default; our schema wants c[0]
    # rightmost (little-endian), so reverse each key. Verify with an asymmetric
    # state (e.g. |01>) if you switch SDK versions.
    counts = {key[::-1]: value for key, value in raw.items()}
    # LocalSimulator 的任务 ID 是 SDK 内可回溯的本地任务号，优于随机 UUID。
    job_id = getattr(task, "id", None)
    return counts, job_id


def run_spinq(qasm_str: str, shots: int) -> tuple[Dict[str, int], str | None]:
    """Run via SpinQit (Taurus local simulator), best-effort. 返回 (counts, job_id)。

    NOTE: this maps the 12-gate whitelist to SpinQit gate objects and has not
    been exercised against the SDK in this environment. Verify on Python 3.10
    (`uv pip install spinqit`) before relying on it for real-machine evidence.
    """
    import spinqit as sp

    circ = parse(qasm_str)
    circuit = sp.Circuit()
    q = circuit.allocateQubits(circ.num_qubits)
    c = circuit.allocateClbits(circ.num_clbits)

    no_param = {
        "h": sp.H,
        "x": sp.X,
        "s": sp.S,
        "sdg": sp.Sd,
        "t": sp.T,
        "tdg": sp.Td,
        "cx": sp.CX,
        "swap": sp.SWAP,
        "ccx": sp.CCX,
    }

    for gate in circ.gates:
        name = gate.name
        if name in ("rz", "ry"):
            g = sp.Rz if name == "rz" else sp.Ry
            circuit << (g, q[gate.qubits[0]], gate.params[0])
        elif name == "cu1":
            circuit << (sp.CP, (q[gate.qubits[0]], q[gate.qubits[1]]), gate.params[0])
        elif len(gate.qubits) == 1:
            circuit << (no_param[name], q[gate.qubits[0]])
        else:
            circuit << (no_param[name], tuple(q[i] for i in gate.qubits))

    for qubit, clbit in circ.measures:
        circuit.measure(q[qubit], c[clbit])

    compiler = sp.get_compiler("native")
    engine = sp.get_basic_simulator()
    exe = compiler.compile(circuit, 0)
    config = sp.BasicSimulatorConfig()
    config.configure_shots(shots)
    result = engine.execute(exe, config)
    counts = dict(result.counts)
    # SpinQit orders keys with q[0] leftmost by default; normalize to little.
    counts = {key[::-1]: value for key, value in counts.items()}
    job_id = getattr(result, "job_id", None) or getattr(result, "task_id", None)
    return counts, job_id


def run_originq(qasm_str: str, shots: int) -> tuple[Dict[str, int], str | None]:
    """Run via pyqpanda local CPUQVM (best-effort). 返回 (counts, job_id)。

    依赖 pyqpanda SDK；缺 SDK 或 API 不匹配时抛异常，由 adapter 回退到内置模拟器。
    键序按 little-endian 归一化（c[0] 最右），需在真实 pyqpanda 上复核。
    """
    import pyqpanda as pq

    machine = pq.CPUQVM()
    machine.init_qvm()
    try:
        if hasattr(pq, "convert_qasm_string_to_qprog"):
            prog, _qreg, creg = pq.convert_qasm_string_to_qprog(qasm_str, machine)
        else:
            prog = pq.convert_qasm_to_qprog(qasm_str, machine)
            creg = machine.get_allocate_cbits()
        result = machine.run_with_configuration(prog, creg, shots)
    finally:
        machine.finalize()

    num_bits = len(creg)
    counts: Dict[str, int] = {}
    for key, val in result.items():
        if isinstance(key, int):
            bin_str = bin(key)[2:].zfill(num_bits)
        else:
            bin_str = str(key).zfill(num_bits)
        counts[bin_str] = val
    # 本地 CPUQVM 无云端可溯源 job_id，返回 None 交由 adapter 生成本地任务号。
    return counts, None


def run_real(qasm_str: str, target: str, shots: int) -> tuple[Dict[str, int], str | None]:
    """执行电路，返回 (counts, job_id)。SDK 缺失或失败时抛异常，由 adapter 回退。"""
    if target == "braket":
        return run_braket(qasm_str, shots)
    if target == "spinq":
        return run_spinq(qasm_str, shots)
    if target == "originq":
        return run_originq(qasm_str, shots)
    raise ValueError("unsupported target: %s" % target)


"""L2: `agent_chat` — natural-language -> QASM / fix / backend selection.

Reads the `LOOMQ_LLM_*` environment variables and calls any OpenAI-compatible
chat-completions endpoint. A "generate -> self-verify -> retry" loop validates
generated QASM with the L1 engine before returning.
"""
