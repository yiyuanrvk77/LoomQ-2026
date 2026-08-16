"""无噪声态矢量模拟器 + 测量分布/采样，供 L1 自验与 run() 回退使用。"""

try:
    from .qasm_parser import Circuit, Gate
except ImportError:  # 脚本方式直接运行时无包上下文
    from qasm_parser import Circuit, Gate

import cmath
import math
import random



_SQ2 = math.sqrt(2.0)


def _H():
    return [[1 / _SQ2, 1 / _SQ2], [1 / _SQ2, -1 / _SQ2]]


def _RZ(theta):
    return [[cmath.exp(-1j * theta / 2), 0], [0, cmath.exp(1j * theta / 2)]]


def _RY(theta):
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return [[c, -s], [s, c]]


_SINGLE = {
    "h": _H(),
    "x": [[0, 1], [1, 0]],
    "s": [[1, 0], [0, 1j]],
    "sdg": [[1, 0], [0, -1j]],
    "t": [[1, 0], [0, cmath.exp(1j * math.pi / 4)]],
    "tdg": [[1, 0], [0, cmath.exp(-1j * math.pi / 4)]],
}


class Simulator:
    def __init__(self, num_qubits: int):
        self.n = num_qubits
        self.state = [0j] * (1 << num_qubits)
        self.state[0] = 1 + 0j

    def _apply1(self, u, q: int):
        n = self.n
        mask = 1 << q
        step = 1 << (q + 1)
        block = 1 << q
        state = self.state
        for start in range(0, 1 << n, step):
            for j in range(start, start + block):
                i0 = j
                i1 = j | mask
                a = state[i0]
                b = state[i1]
                state[i0] = u[0][0] * a + u[0][1] * b
                state[i1] = u[1][0] * a + u[1][1] * b

    def _apply2(self, u, a: int, b: int):
        n = self.n
        mask_a = 1 << a
        mask_b = 1 << b
        mask = mask_a | mask_b
        state = self.state
        for idx in range(1 << n):
            if idx & mask:
                continue
            i00 = idx
            i01 = idx | mask_b
            i10 = idx | mask_a
            i11 = idx | mask
            v00 = state[i00]
            v01 = state[i01]
            v10 = state[i10]
            v11 = state[i11]
            state[i00] = u[0][0] * v00 + u[0][1] * v01 + u[0][2] * v10 + u[0][3] * v11
            state[i01] = u[1][0] * v00 + u[1][1] * v01 + u[1][2] * v10 + u[1][3] * v11
            state[i10] = u[2][0] * v00 + u[2][1] * v01 + u[2][2] * v10 + u[2][3] * v11
            state[i11] = u[3][0] * v00 + u[3][1] * v01 + u[3][2] * v10 + u[3][3] * v11

    def _apply_ccx(self, a: int, b: int, c: int):
        # qelib1 standard Toffoli decomposition (control a,b; target c).
        self._apply1(_H(), c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], b, c)
        self._apply1(_SINGLE["tdg"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, c)
        self._apply1(_SINGLE["t"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], b, c)
        self._apply1(_SINGLE["tdg"], c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, c)
        self._apply1(_SINGLE["t"], b)
        self._apply1(_SINGLE["t"], c)
        self._apply1(_H(), c)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, b)
        self._apply1(_SINGLE["t"], a)
        self._apply1(_SINGLE["tdg"], b)
        self._apply2([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], a, b)

    def apply(self, gate: Gate):
        name = gate.name
        qubits = gate.qubits
        if name in _SINGLE:
            self._apply1(_SINGLE[name], qubits[0])
        elif name == "rz":
            self._apply1(_RZ(gate.params[0]), qubits[0])
        elif name == "ry":
            self._apply1(_RY(gate.params[0]), qubits[0])
        elif name == "cx":
            self._apply2(
                [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]],
                qubits[0],
                qubits[1],
            )
        elif name == "cu1":
            self._apply2(
                [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, cmath.exp(1j * gate.params[0])],
                ],
                qubits[0],
                qubits[1],
            )
        elif name == "swap":
            self._apply2(
                [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
                qubits[0],
                qubits[1],
            )
        elif name == "ccx":
            self._apply_ccx(*qubits)
        else:
            raise ValueError("unsupported gate: %s" % name)


def _final_state(circuit: Circuit) -> list[complex]:
    sim = Simulator(circuit.num_qubits)
    for gate in circuit.gates:
        sim.apply(gate)
    return sim.state


def _measure_map(circuit: Circuit) -> dict[int, int]:
    clbit_to_qubit: dict[int, int] = {}
    for qubit, clbit in circuit.measures:
        clbit_to_qubit[clbit] = qubit
    return clbit_to_qubit


def _key_for_index(index: int, circuit: Circuit, clbit_to_qubit: dict[int, int]) -> str:
    bits = [(index >> i) & 1 for i in range(circuit.num_qubits)]
    nc = circuit.num_clbits
    return "".join(
        str(bits[clbit_to_qubit[j]]) if j in clbit_to_qubit else "0"
        for j in range(nc - 1, -1, -1)
    )


def probabilities(circuit: Circuit) -> dict[str, float]:
    """Exact measurement probability distribution for the measured bits."""
    state = _final_state(circuit)
    clbit_to_qubit = _measure_map(circuit)
    dist: dict[str, float] = {}
    for index, amplitude in enumerate(state):
        prob = abs(amplitude) ** 2
        if prob == 0:
            continue
        key = _key_for_index(index, circuit, clbit_to_qubit)
        dist[key] = dist.get(key, 0.0) + prob
    return dist


def simulate(circuit: Circuit, shots: int) -> dict[str, int]:
    state = _final_state(circuit)

    probs = [abs(amplitude) ** 2 for amplitude in state]
    sampled = random.choices(range(1 << circuit.num_qubits), weights=probs, k=shots)

    clbit_to_qubit = _measure_map(circuit)

    counts: dict[str, int] = {}
    for index in sampled:
        key = _key_for_index(index, circuit, clbit_to_qubit)
        counts[key] = counts.get(key, 0) + 1
    return counts


def simulate_with_noise(circuit: Circuit, shots: int, error_rate: float = 0.02) -> dict[str, int]:
    """带噪声的态矢量模拟：测量采样后以 error_rate 概率随机翻转比特。

    用于教学演示「真机为何不完美」：模拟读取误差（bit-flip readout noise），
    让理想上确定的结果也出现少量错误比特，直观看到噪声把分布"抹平"。
    """
    sim = Simulator(circuit.num_qubits)
    for gate in circuit.gates:
        sim.apply(gate)

    probs = [abs(amplitude) ** 2 for amplitude in sim.state]
    sampled = random.choices(range(1 << circuit.num_qubits), weights=probs, k=shots)
    clbit_to_qubit = _measure_map(circuit)
    counts: dict[str, int] = {}
    for index in sampled:
        for q in range(circuit.num_qubits):
            if random.random() < error_rate:
                index ^= 1 << q
        key = _key_for_index(index, circuit, clbit_to_qubit)
        counts[key] = counts.get(key, 0) + 1
    return counts


"""Emit the unified IR as each backend's native target representation."""



