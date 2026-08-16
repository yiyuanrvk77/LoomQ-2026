"""真实 SDK 执行层（run 用），缺 SDK 时由适配器回退到内置模拟器。"""

try:
    from .qasm_parser import parse
    from .transpiler import emit
except ImportError:  # 脚本方式直接运行时无包上下文
    from qasm_parser import parse
    from transpiler import emit

from typing import Dict



def run_braket(qasm_str: str, shots: int) -> Dict[str, int]:
    """Run via AWS Braket LocalSimulator (OpenQASM 3)."""
    from braket.devices import LocalSimulator
    from braket.ir.openqasm import Program

    source = emit(parse(qasm_str), "braket")
    device = LocalSimulator()
    result = device.run(Program(source=source), shots=shots).result()
    raw = dict(result.measurement_counts)
    # Braket orders keys with q[0] leftmost by default; our schema wants c[0]
    # rightmost (little-endian), so reverse each key. Verify with an asymmetric
    # state (e.g. |01>) if you switch SDK versions.
    return {key[::-1]: value for key, value in raw.items()}


def run_spinq(qasm_str: str, shots: int) -> Dict[str, int]:
    """Run via SpinQit (Taurus local simulator), best-effort.

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
    return {key[::-1]: value for key, value in counts.items()}


def run_real(qasm_str: str, target: str, shots: int) -> Dict[str, int]:
    if target == "braket":
        return run_braket(qasm_str, shots)
    if target == "spinq":
        return run_spinq(qasm_str, shots)
    if target == "originq":
        raise NotImplementedError("originq requires pyqpanda + account token")
    raise ValueError("unsupported target: %s" % target)


"""L2: `agent_chat` — natural-language -> QASM / fix / backend selection.

Reads the `LOOMQ_LLM_*` environment variables and calls any OpenAI-compatible
chat-completions endpoint. A "generate -> self-verify -> retry" loop validates
generated QASM with the L1 engine before returning.
"""
