"""Parser for measurement expressions and first-order error propagation.

Grammar (recursive descent):

    expr        := term (('+' | '-') term)*
    term        := factor (('*' | '/' | implicit-multiply) factor)*
    factor      := unary ('^' signed_number)?
    unary       := ('-' | '+') unary | primary
    primary     := NUMBER unit_group? | '(' expr ')' | unit_group
    unit_group  := unit_atom+ (('/') unit_atom+)?       # e.g. kg·m/s^2

A NUMBER may carry an uncertainty:
    1.23(4)        -> parenthesis shorthand (uncertainty on last digits)
    1.23 ± 0.04    -> explicit absolute uncertainty
    1.23 ± 0.04 m  -> explicit uncertainty with shared unit

A '/' is considered a *unit separator* (part of a compound unit) only when
written without surrounding spaces, e.g. "m/s^2"; "m / s" is treated as
measurement-level division (the two are mathematically equivalent anyway).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .units import DIMENSIONLESS, Dimension, format_dimension, lookup_unit


class CalcError(Exception):
    """Field-level calculation error.

    kind: "parse" | "dimension" | "zero_division" | "exponent" | "unit"
    """

    def __init__(self, kind: str, message: str, position: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.position = position


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass
class Measurement:
    value: float          # in SI base units
    uncertainty: float    # absolute standard uncertainty, SI base units
    dim: Dimension

    def _check_additive(self, other: "Measurement", op: str) -> None:
        if self.dim != other.dim:
            word = "加法" if op == "+" else "减法"
            raise CalcError(
                "dimension",
                f"量纲不兼容：不能对 {format_dimension(self.dim)} 与 "
                f"{format_dimension(other.dim)} 执行{word}",
            )

    def __add__(self, other: "Measurement") -> "Measurement":
        self._check_additive(other, "+")
        return Measurement(
            self.value + other.value,
            math.hypot(self.uncertainty, other.uncertainty),
            self.dim,
        )

    def __sub__(self, other: "Measurement") -> "Measurement":
        self._check_additive(other, "-")
        return Measurement(
            self.value - other.value,
            math.hypot(self.uncertainty, other.uncertainty),
            self.dim,
        )

    def __mul__(self, other: "Measurement") -> "Measurement":
        v = self.value * other.value
        dim: Dimension = tuple(a + b for a, b in zip(self.dim, other.dim))  # type: ignore
        u = math.hypot(
            other.value * self.uncertainty, self.value * other.uncertainty
        )
        return Measurement(v, u, dim)

    def __truediv__(self, other: "Measurement") -> "Measurement":
        if other.value == 0:
            raise CalcError("zero_division", "零除错误：除数的数值为 0")
        v = self.value / other.value
        dim: Dimension = tuple(a - b for a, b in zip(self.dim, other.dim))  # type: ignore
        u = abs(v) * math.hypot(
            self.uncertainty / self.value if self.value else 0.0,
            other.uncertainty / other.value,
        )
        return Measurement(v, u, dim)

    def __neg__(self) -> "Measurement":
        return Measurement(-self.value, self.uncertainty, self.dim)

    def power(self, exponent: float) -> "Measurement":
        if not math.isfinite(exponent):
            raise CalcError("exponent", "非法指数：指数必须是有限实数")
        is_integer = abs(exponent - round(exponent)) < 1e-12
        if self.value == 0 and exponent <= 0:
            if exponent == 0:
                return Measurement(1.0, 0.0, DIMENSIONLESS)
            raise CalcError("zero_division", "零除错误：0 不能取负幂")
        if not is_integer and self.value < 0:
            raise CalcError(
                "exponent",
                f"非法指数：负数不能取非整数次幂（指数为 {exponent:g}）",
            )
        new_dim: List[int] = []
        for e in self.dim:
            r = e * exponent
            if abs(r - round(r)) > 1e-9:
                raise CalcError(
                    "dimension",
                    f"量纲不兼容：量纲 {format_dimension(self.dim)} 取 {exponent:g} "
                    f"次幂会产生非整数量纲指数",
                )
            new_dim.append(int(round(r)))
        try:
            v = self.value ** exponent
        except (OverflowError, ValueError) as exc:
            raise CalcError("exponent", f"非法指数：{exc}") from exc
        if not math.isfinite(v):
            raise CalcError("exponent", "幂运算结果不是有限数")
        rel = abs(exponent) * (
            self.uncertainty / abs(self.value) if self.value != 0 else 0.0
        )
        return Measurement(v, abs(v) * rel, tuple(new_dim))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass
class Token:
    kind: str   # 'num' | 'unit' | 'op' | 'lpar' | 'rpar' | 'pm'
    text: str
    pos: int
    end: int
    number: Optional[float] = None
    unc_short: Optional[str] = None  # raw digits of 1.23(4) shorthand


_NUM_RE = re.compile(
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    r"(?:\(\s*(?:\d+(?:\.\d*)?|\.\d+)\s*\))?"
)
_UNIT_RE = re.compile(r"[^\s0-9+\-*/^()·×÷∗±()]+")


def _normalize(text: str) -> str:
    table = {"−": "-", "–": "-", "—": "-", "∗": "*", "＊": "*"}
    for a, b in table.items():
        text = text.replace(a, b)
    return text.strip()


def tokenize(src: str) -> List[Token]:
    s = _normalize(src)
    toks: List[Token] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            m = _NUM_RE.match(s, i)
            text = m.group(0)
            main_m = re.match(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text)
            main = main_m.group(0)
            short = re.search(r"\(\s*([0-9.]+)\s*\)", text)
            toks.append(
                Token(
                    "num", text, i, m.end(), float(main),
                    short.group(1) if short else None,
                )
            )
            i = m.end()
            continue
        simple = {
            "(": "lpar", ")": "rpar", "±": "pm",
            "^": "op", "*": "op", "×": "op", "·": "op",
            "/": "op", "÷": "op", "+": "op", "-": "op",
        }
        if c == "*" and i + 1 < n and s[i + 1] == "*":
            toks.append(Token("op", "^", i, i + 2))
            i += 2
            continue
        if c in simple:
            kind = simple[c]
            text = "^" if c in "^" else ("*" if c in "×·" else ("/" if c == "÷" else c))
            toks.append(Token(kind, text, i, i + 1))
            i += 1
            continue
        m = _UNIT_RE.match(s, i)
        if m:
            toks.append(Token("unit", m.group(0), i, m.end()))
            i = m.end()
            continue
        raise CalcError("parse", f"无法识别的字符 {c!r}", i)
    return toks


def shorthand_uncertainty(main: str, digits: str) -> float:
    """GUM-style parenthesis shorthand.

    The parenthesized digits are the uncertainty on the last len(digits)
    displayed digits of the mantissa, aligned to the mantissa's last digit:
      1.234(5) -> 0.005
      1.23(12) -> 0.12
      120(3)   -> 3
      120(30)  -> 30
      1.2e2(3) -> 0.3e2 = 30
    """
    if "e" in main or "E" in main:
        mant, exp_part = re.split(r"[eE]", main, 1)
        exp10 = float(exp_part)
    else:
        mant, exp10 = main, 0.0
    ndec = len(mant.split(".", 1)[1]) if "." in mant else 0
    return float(digits) * 10 ** (-ndec + exp10)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class Parser:
    def __init__(self, tokens: List[Token], src: str):
        self.toks = tokens
        self.src = src
        self.i = 0

    # -- helpers ------------------------------------------------------------

    def peek(self, off: int = 0) -> Optional[Token]:
        j = self.i + off
        return self.toks[j] if j < len(self.toks) else None

    def advance(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self) -> Measurement:
        if not self.toks:
            raise CalcError("parse", "表达式为空")
        result = self.parse_expr()
        if self.peek() is not None:
            t = self.peek()
            raise CalcError("parse", f"表达式末尾存在多余内容：{t.text!r}", t.pos)
        return result

    # -- levels -------------------------------------------------------------

    def parse_expr(self) -> Measurement:
        left = self.parse_term()
        while (t := self.peek()) and t.kind == "op" and t.text in "+-":
            self.advance()
            right = self.parse_term()
            left = left + right if t.text == "+" else left - right
        return left

    def parse_term(self) -> Measurement:
        left = self.parse_factor()
        while True:
            t = self.peek()
            if t is None:
                return left
            if t.kind == "op" and t.text in "*/" and not self._is_unit_slash():
                self.advance()
                right = self.parse_factor()
                left = left * right if t.text == "*" else left / right
            elif t.kind in ("num", "lpar"):
                left = left * self.parse_factor()  # implicit multiplication
            else:
                # a unit here already attaches to a preceding number/'('
                # inside parse_primary; a stray leading unit is an error
                return left

    def _is_unit_slash(self) -> bool:
        """True if the upcoming '/' is an unspaced compound-unit separator."""
        t = self.peek()
        if not t or t.kind != "op" or t.text != "/":
            return False
        prev = self.peek(-1)
        nxt = self.peek(1)
        if prev is None or nxt is None:
            return False
        tight_left = prev.end == t.pos
        tight_right = t.end == nxt.pos
        return tight_left and tight_right and nxt.kind == "unit"

    def parse_factor(self) -> Measurement:
        base = self.parse_unary()
        t = self.peek()
        if t and t.kind == "op" and t.text == "^":
            self.advance()
            exponent = self._read_signed_exponent()
            base = base.power(exponent)
        return base

    def _read_signed_exponent(self) -> float:
        sign = 1.0
        t = self.peek()
        if t and t.kind == "op" and t.text in "+-":
            sign = -1.0 if t.text == "-" else 1.0
            self.advance()
            t = self.peek()
        if t is None or t.kind != "num" or t.unc_short is not None:
            pos = t.pos if t else len(self.src)
            raise CalcError("exponent", "非法指数：^ 后必须是一个纯数字", pos)
        self.advance()
        return sign * t.number

    def parse_unary(self) -> Measurement:
        t = self.peek()
        if t and t.kind == "op" and t.text in "+-":
            self.advance()
            v = self.parse_unary()
            return v if t.text == "+" else -v
        return self.parse_primary()

    def parse_primary(self) -> Measurement:
        t = self.peek()
        if t is None:
            raise CalcError("parse", "表达式不完整：缺少操作数")
        if t.kind == "lpar":
            self.advance()
            inner = self.parse_expr()
            close = self.peek()
            if close is None or close.kind != "rpar":
                raise CalcError("parse", "括号不匹配：缺少右括号 ')'", t.pos)
            self.advance()
            # a parenthesized value may carry a trailing unit group:
            # "(3 ± 0.1) m/s^2" means "(3 ± 0.1) * (1 m/s^2)"
            if self.peek() and self.peek().kind == "unit":
                factor, udim = self.read_unit_group()
                inner = inner * Measurement(factor, 0.0, udim)
            return inner
        if t.kind == "unit":
            return self.parse_bare_unit()
        if t.kind == "num":
            return self.parse_number_primary()
        raise CalcError("parse", f"此处应为数字或括号，却得到 {t.text!r}", t.pos)

    # -- number + units + uncertainty --------------------------------------

    def parse_bare_unit(self) -> Measurement:
        factor, dim = self.read_unit_group()
        return Measurement(factor, 0.0, dim)

    def parse_number_primary(self) -> Measurement:
        tok = self.advance()
        value = tok.number
        short_unc: Optional[float] = None
        if tok.unc_short is not None:
            short_unc = shorthand_uncertainty(tok.text.split("(", 1)[0], tok.unc_short)

        # explicit ± uncertainty
        explicit_u = None
        if self.peek() and self.peek().kind == "pm":
            self.advance()
            utok = self.peek()
            if utok is None or utok.kind != "num" or utok.unc_short is not None:
                pos = utok.pos if utok else len(self.src)
                raise CalcError("parse", "± 后必须是一个纯数字（绝对不确定度）", pos)
            self.advance()
            explicit_u = utok.number

        # one shared unit group follows
        factor, dim = self.read_unit_group()
        u = (explicit_u if explicit_u is not None else short_unc) or 0.0
        return Measurement(value * factor, u * factor, dim)

    # -- compound unit groups ----------------------------------------------

    def read_unit_group(self) -> Tuple[float, Dimension]:
        """Read e.g. 'kg·m/s^2' attached to the current position.

        Returns (factor to SI base, dimension). Empty group => (1, 1).
        '/' inside the group must be tight (no spaces) and have a unit on
        the right; otherwise the group stops and term parsing takes over.
        """
        if not self.peek() or self.peek().kind != "unit":
            return 1.0, DIMENSIONLESS
        factor, dim = self._read_unit_side(numerator=True)
        while self._is_unit_slash():
            self.advance()  # consume '/'
            rf, rd = self._read_unit_side(numerator=False)
            factor /= rf
            dim = tuple(a - b for a, b in zip(dim, rd))  # type: ignore
        return factor, dim  # type: ignore[return-value]

    def _read_unit_side(self, numerator: bool) -> Tuple[float, Dimension]:
        factor = 1.0
        dim: Dimension = DIMENSIONLESS
        while True:
            t = self.peek()
            if t is None or t.kind != "unit":
                break
            resolved = lookup_unit(t.text)
            if resolved is None:
                raise CalcError(
                    "unit",
                    f"未知单位 {t.text!r}（支持 SI 单位与标准前缀，如 km、mV、μs）",
                    t.pos,
                )
            self.advance()
            uf, ud = resolved
            exp = 1
            if self.peek() and self.peek().kind == "op" and self.peek().text == "^":
                self.advance()
                # explicit exponent, e.g. s^-2 (sign is inside the exponent)
                exp = self._read_unit_exponent()
            factor *= uf ** exp
            dim = tuple(a + exp * b for a, b in zip(dim, ud))  # type: ignore
            # explicit '·'/'*' separator, tight between units
            nxt = self.peek()
            if nxt and nxt.kind == "op" and nxt.text == "*":
                after = self.peek(1)
                prev_tok = self.toks[self.i - 1]
                if (
                    after and after.kind == "unit"
                    and prev_tok.end == nxt.pos and nxt.end == after.pos
                ):
                    self.advance()
                    continue
                break
            # whitespace-adjacent unit atom: part of the group
            if nxt and nxt.kind == "unit":
                continue
            break
        return factor, dim  # type: ignore[return-value]

    def _read_unit_exponent(self) -> int:
        sign = 1
        t = self.peek()
        if t and t.kind == "op" and t.text in "+-":
            sign = -1 if t.text == "-" else 1
            self.advance()
            t = self.peek()
        if t is None or t.kind != "num":
            pos = t.pos if t else len(self.src)
            raise CalcError("exponent", "单位指数必须是整数", pos)
        if abs(t.number - round(t.number)) > 1e-12:
            raise CalcError("exponent", f"单位指数必须是整数，得到 {t.number:g}", t.pos)
        self.advance()
        return sign * int(round(t.number))


def evaluate(expression: str) -> Measurement:
    return Parser(tokenize(expression), expression).parse()
