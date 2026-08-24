"""L3 混合编译：Hybrid-QASM 经典块解析 -> RISC-V 汇编。"""

import re
from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #
@dataclass
class Reg:
    index: int  # 1..9


@dataclass
class CBit:
    index: int  # 0..


@dataclass
class IntLit:
    value: int


@dataclass
class Neg:
    operand: object


@dataclass
class BinOp:
    op: str  # "+" or "-"
    left: object
    right: object


@dataclass
class Cond:
    op: str  # "==" or "!="
    left: object
    right: object


@dataclass
class Assign:
    var: Reg
    expr: object


@dataclass
class If:
    cond: Cond
    then: list
    else_: list


# --------------------------------------------------------------------------- #
# Lexer / parser for the classical block
# --------------------------------------------------------------------------- #
@dataclass
class _Token:
    kind: str
    value: str


_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<COMMENT>//[^\n]*)
  | (?P<CBIT>c\[[0-9]+\])
  | (?P<REG>r[1-9])
  | (?P<IF>if)
  | (?P<ELSE>else)
  | (?P<NUM>[0-9]+)
  | (?P<EQEQ>==)
  | (?P<NEQ>!=)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<LBRACE>\{)
  | (?P<RBRACE>\})
  | (?P<ASSIGN>=)
  | (?P<PLUS>\+)
  | (?P<MINUS>-)
  | (?P<SEMI>;)
    """,
    re.VERBOSE,
)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError("unexpected character at %d: %r" % (pos, text[pos]))
        pos = m.end()
        if m.lastgroup in ("WS", "COMMENT"):
            continue
        tokens.append(_Token(m.lastgroup, m.group()))
    tokens.append(_Token("EOF", ""))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token:
        return self.tokens[self.pos]

    def next(self) -> _Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> _Token:
        tok = self.next()
        if tok.kind != kind:
            raise ValueError("expected %s but got %s" % (kind, tok.kind))
        return tok

    def parse_program(self) -> list:
        stmts = []
        while self.peek().kind != "EOF":
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        if self.peek().kind == "IF":
            return self.parse_if()
        return self.parse_assign()

    def parse_assign(self) -> Assign:
        var = self.parse_reg()
        self.expect("ASSIGN")
        expr = self.parse_expr()
        self.expect("SEMI")
        return Assign(var, expr)

    def parse_reg(self) -> Reg:
        tok = self.expect("REG")
        return Reg(int(tok.value[1:]))

    def parse_if(self) -> If:
        self.expect("IF")
        self.expect("LPAREN")
        cond = self.parse_cond()
        self.expect("RPAREN")
        then = self.parse_block()
        else_ = []
        if self.peek().kind == "ELSE":
            self.next()
            else_ = self.parse_block()
        return If(cond, then, else_)

    def parse_block(self) -> list:
        self.expect("LBRACE")
        stmts = []
        while self.peek().kind != "RBRACE":
            stmts.append(self.parse_statement())
        self.expect("RBRACE")
        return stmts

    def parse_cond(self) -> Cond:
        left = self.parse_expr()
        op_tok = self.next()
        if op_tok.kind == "EQEQ":
            op = "=="
        elif op_tok.kind == "NEQ":
            op = "!="
        else:
            raise ValueError("expected comparison operator, got %s" % op_tok.kind)
        right = self.parse_expr()
        return Cond(op, left, right)

    def parse_expr(self):
        left = self.parse_term()
        while self.peek().kind in ("PLUS", "MINUS"):
            op_tok = self.next()
            op = "+" if op_tok.kind == "PLUS" else "-"
            right = self.parse_term()
            left = BinOp(op, left, right)
        return left

    def parse_term(self):
        if self.peek().kind == "MINUS":
            self.next()
            return Neg(self.parse_term())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUM":
            self.next()
            return IntLit(int(tok.value))
        if tok.kind == "REG":
            return self.parse_reg()
        if tok.kind == "CBIT":
            self.next()
            return CBit(int(re.search(r"\d+", tok.value).group()))
        if tok.kind == "LPAREN":
            self.next()
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr
        raise ValueError("unexpected token in expression: %s" % tok.kind)


def _parse_classical(body: str) -> list:
    return _Parser(_tokenize(body)).parse_program()


# --------------------------------------------------------------------------- #
# Code generation
# --------------------------------------------------------------------------- #
class _Alloc:
    def __init__(self, first_free: int):
        self.pool = ["x%d" % i for i in range(first_free, 32)]
        self.used: set[str] = set()

    def alloc(self) -> str:
        for reg in self.pool:
            if reg not in self.used:
                self.used.add(reg)
                return reg
        raise RuntimeError("out of scratch registers")

    def free(self, reg: str) -> None:
        self.used.discard(reg)


def _reg_name(expr) -> str:
    if isinstance(expr, Reg):
        return "x%d" % expr.index
    if isinstance(expr, CBit):
        return "x%d" % (10 + expr.index)
    raise ValueError("not a register-like expression")


def _gen_expr(expr, dest: str, alloc: _Alloc, out: list[str]) -> None:
    if isinstance(expr, IntLit):
        out.append("li %s, %d" % (dest, expr.value))
    elif isinstance(expr, (Reg, CBit)):
        out.append("add %s, %s, x0" % (dest, _reg_name(expr)))
    elif isinstance(expr, Neg):
        if isinstance(expr.operand, IntLit):
            out.append("li %s, %d" % (dest, -expr.operand.value))
        else:
            _gen_expr(expr.operand, dest, alloc, out)
            out.append("sub %s, x0, %s" % (dest, dest))
    elif isinstance(expr, BinOp):
        _gen_binop(expr, dest, alloc, out)
    else:
        raise ValueError("unsupported expression node")


def _gen_binop(expr: BinOp, dest: str, alloc: _Alloc, out: list[str]) -> None:
    left, right, op = expr.left, expr.right, expr.op
    if isinstance(left, IntLit) and isinstance(right, IntLit):
        value = left.value + right.value if op == "+" else left.value - right.value
        out.append("li %s, %d" % (dest, value))
        return
    if isinstance(right, IntLit):
        _gen_expr(left, dest, alloc, out)
        imm = right.value if op == "+" else -right.value
        out.append("addi %s, %s, %d" % (dest, dest, imm))
        return
    if isinstance(left, IntLit):
        _gen_expr(right, dest, alloc, out)
        if op == "+":
            out.append("addi %s, %s, %d" % (dest, dest, left.value))
        else:
            out.append("sub %s, x0, %s" % (dest, dest))
            out.append("addi %s, %s, %d" % (dest, dest, left.value))
        return
    if isinstance(left, (Reg, CBit)) and isinstance(right, (Reg, CBit)):
        # Both operands are single registers: reads happen before the write,
        # so no scratch register is required (safe even when one of them is
        # the destination itself, e.g. ``r1 = r1 + c[0]``).
        if op == "+":
            out.append("add %s, %s, %s" % (dest, _reg_name(left), _reg_name(right)))
        else:
            out.append("sub %s, %s, %s" % (dest, _reg_name(left), _reg_name(right)))
        return
    if isinstance(right, (Reg, CBit)) and _reg_name(right) != dest:
        # Right is a stable single register that is not the destination:
        # materialize the left subtree into dest, then combine directly.
        # (The ``!= dest`` guard keeps the right operand's value intact.)
        _gen_expr(left, dest, alloc, out)
        if op == "+":
            out.append("add %s, %s, %s" % (dest, dest, _reg_name(right)))
        else:
            out.append("sub %s, %s, %s" % (dest, dest, _reg_name(right)))
        return
    # Both operands are complex (or the simple right operand is `dest`):
    # keep the original two-register strategy.
    temp = alloc.alloc()
    _gen_expr(right, temp, alloc, out)
    _gen_expr(left, dest, alloc, out)
    if op == "+":
        out.append("add %s, %s, %s" % (dest, dest, temp))
    else:
        out.append("sub %s, %s, %s" % (dest, dest, temp))
    alloc.free(temp)


def _gen_branch_if_false(cond: Cond, label: str, alloc: _Alloc, out: list[str]) -> None:
    temps: list[str] = []

    def operand_reg(operand) -> str:
        if isinstance(operand, (Reg, CBit)):
            return _reg_name(operand)
        if isinstance(operand, IntLit):
            reg = alloc.alloc()
            out.append("li %s, %d" % (reg, operand.value))
            temps.append(reg)
            return reg
        reg = alloc.alloc()
        _gen_expr(operand, reg, alloc, out)
        temps.append(reg)
        return reg

    left_reg = operand_reg(cond.left)
    right_reg = operand_reg(cond.right)
    if cond.op == "==":
        out.append("bne %s, %s, %s" % (left_reg, right_reg, label))
    else:
        out.append("beq %s, %s, %s" % (left_reg, right_reg, label))
    for reg in temps:
        alloc.free(reg)


def _gen_statements(
    statements: list,
    alloc: _Alloc,
    out: list[str],
    fresh: callable,
) -> None:
    for stmt in statements:
        if isinstance(stmt, Assign):
            _gen_expr(stmt.expr, _reg_name(stmt.var), alloc, out)
        elif isinstance(stmt, If):
            else_label = fresh("else")
            end_label = fresh("end")
            _gen_branch_if_false(stmt.cond, else_label, alloc, out)
            _gen_statements(stmt.then, alloc, out, fresh)
            out.append("j %s" % end_label)
            out.append("%s:" % else_label)
            _gen_statements(stmt.else_, alloc, out, fresh)
            out.append("%s:" % end_label)
        else:
            raise ValueError("unsupported statement node")


def _compile_classical(statements: list, num_clbits: int) -> str:
    alloc = _Alloc(10 + num_clbits)
    out: list[str] = []
    counter = [0]

    def fresh(prefix: str) -> str:
        counter[0] += 1
        return ".L_%s_%d" % (prefix, counter[0])

    _gen_statements(statements, alloc, out, fresh)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Hybrid-QASM splitting
# --------------------------------------------------------------------------- #
def _strip_comments(text: str) -> str:
    """Remove `//` line comments before keyword scanning.

    The classical-block keyword must never be matched inside a comment:
    a comment such as ``// classical logic`` used to either drop the quantum
    operation sequence or raise ``classical block missing '{'``.
    """
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _extract_classical(text: str) -> tuple[str, list[str]]:
    quantum_parts: list[str] = []
    classical_bodies: list[str] = []
    text = _strip_comments(text)
    i = 0
    n = len(text)
    keyword = "classical"
    while True:
        idx = text.find(keyword, i)
        if idx == -1:
            quantum_parts.append(text[i:])
            break
        before_ok = idx == 0 or not (text[idx - 1].isalnum() or text[idx - 1] == "_")
        after = idx + len(keyword)
        after_ok = after < n and (text[after].isspace() or text[after] == "{")
        if not (before_ok and after_ok):
            quantum_parts.append(text[i:after])
            i = after
            continue
        quantum_parts.append(text[i:idx])
        # The block brace must directly follow the keyword (whitespace only).
        brace = after
        while brace < n and text[brace].isspace():
            brace += 1
        if brace >= n or text[brace] != "{":
            raise ValueError("classical block missing '{'")
        depth = 0
        j = brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n:
            raise ValueError("unbalanced braces in classical block")
        classical_bodies.append(text[brace + 1 : j])
        i = j + 1
    return "".join(quantum_parts), classical_bodies


def _parse_creg_size(text: str) -> int:
    m = re.search(r"creg\s+\w+\s*\[\s*(\d+)\s*\]", text)
    return int(m.group(1)) if m else 0


def _parse_quantum_ops(text: str) -> list[str]:
    ops: list[str] = []
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if re.match(r"(OPENQASM|include|qreg|creg|barrier)\b", line):
            continue
        m = re.match(
            r"measure\s+\w+\s*\[\s*(\d+)\s*\]\s*->\s*\w+\s*\[\s*(\d+)\s*\]\s*;",
            line,
        )
        if m:
            ops.append("measure q[%s] -> c[%s]" % (m.group(1), m.group(2)))
            continue
        m = re.match(r"([a-zA-Z][a-zA-Z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*);", line)
        if m:
            name = m.group(1)
            params = m.group(2)
            qubits = [int(x) for x in re.findall(r"q\[(\d+)\]", m.group(3))]
            args = ", ".join("q[%d]" % q for q in qubits)
            if params is not None:
                ops.append("%s(%s) %s" % (name, params.strip(), args))
            else:
                ops.append("%s %s" % (name, args))
            continue
    return ops


def compile_hybrid(hybrid_qasm_str: str) -> tuple[list[str], str]:
    """Return (quantum operation sequence, RISC-V assembly text)."""
    cleaned = _strip_comments(hybrid_qasm_str)
    quantum_text, classical_bodies = _extract_classical(cleaned)
    num_clbits = _parse_creg_size(cleaned)
    quantum_ops = _parse_quantum_ops(quantum_text)

    statements = []
    for body in classical_bodies:
        statements.extend(_parse_classical(body))

    assembly = _compile_classical(statements, num_clbits)
    return quantum_ops, assembly
