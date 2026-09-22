"""Unit registry: SI base units, derived units and SI prefixes."""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, Tuple

# Dimension vector: (length, mass, time, electric_current,
#                    thermodynamic_temperature, amount_of_substance,
#                    luminous_intensity)
DIM_NAMES = ("L", "M", "T", "I", "Θ", "N", "J")

Dimension = Tuple[int, int, int, int, int, int, int]

DIMENSIONLESS: Dimension = (0, 0, 0, 0, 0, 0, 0)


def _dim(**kw: int) -> Dimension:
    d = [0] * 7
    for k, v in kw.items():
        d[list(DIM_NAMES).index(k)] = v
    return tuple(d)  # type: ignore[return-value]


# Unit name -> (factor to SI base units, dimension)
UNITS: Dict[str, Tuple[float, Dimension]] = {
    # SI base units
    "m":   (1.0, _dim(L=1)),
    "g":   (1e-3, _dim(M=1)),
    "s":   (1.0, _dim(T=1)),
    "A":   (1.0, _dim(I=1)),
    "K":   (1.0, _dim(Θ=1)),
    "mol": (1.0, _dim(N=1)),
    "cd":  (1.0, _dim(J=1)),
    # Common mass
    "kg":  (1.0, _dim(M=1)),
    # Length
    "inch": (0.0254, _dim(L=1)),
    "ft":   (0.3048, _dim(L=1)),
    # Time
    "min": (60.0, _dim(T=1)),
    "h":   (3600.0, _dim(T=1)),
    "hr":  (3600.0, _dim(T=1)),
    # Temperature (offset units converted below in parser; here linear factor)
    "degC": (1.0, _dim(Θ=1)),
    "degF": (5.0 / 9.0, _dim(Θ=1)),
    # Volume
    "L":   (1e-3, _dim(L=3)),
    "l":   (1e-3, _dim(L=3)),
    "liter": (1e-3, _dim(L=3)),
    "mL":  (1e-6, _dim(L=3)),
    "ml":  (1e-6, _dim(L=3)),
    "gal": (0.003785411784, _dim(L=3)),
    # Area
    "ha": (1e4, _dim(L=2)),
    # Frequency
    "Hz": (1.0, _dim(T=-1)),
    # Force / energy / power / pressure
    "N":  (1.0, _dim(L=1, M=1, T=-2)),
    "J":  (1.0, _dim(L=2, M=1, T=-2)),
    "W":  (1.0, _dim(L=2, M=1, T=-3)),
    "Pa": (1.0, _dim(L=-1, M=1, T=-2)),
    "bar": (1e5, _dim(L=-1, M=1, T=-2)),
    "atm": (101325.0, _dim(L=-1, M=1, T=-2)),
    "eV":  (1.602176634e-19, _dim(L=2, M=1, T=-2)),
    # Electric
    "C": (1.0, _dim(T=1, I=1)),
    "V": (1.0, _dim(L=2, M=1, T=-3, I=-1)),
    "Ohm": (1.0, _dim(L=2, M=1, T=-3, I=-2)),
    "ohm": (1.0, _dim(L=2, M=1, T=-3, I=-2)),
    "Ω":   (1.0, _dim(L=2, M=1, T=-3, I=-2)),
    "F":   (1.0, _dim(L=-2, M=-1, T=4, I=2)),
    "T_field": (1.0, _dim(M=1, T=-2, I=-1)),
    # Angle (treated as dimensionless radian, but kept as named convenience)
    "rad": (1.0, DIMENSIONLESS),
    "sr":  (1.0, DIMENSIONLESS),
    "deg": (0.017453292519943295, DIMENSIONLESS),
}

# SI prefixes (factor, exponent-of-10)
SI_PREFIXES: Dict[str, float] = {
    "q": 1e-30, "r": 1e-27, "y": 1e-24, "z": 1e-21,
    "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9,
    "μ": 1e-6, "u": 1e-6,
    "m": 1e-3, "c": 1e-2, "d": 1e-1,
    "da": 1e1,
    "h": 1e2, "k": 1e3, "M": 1e6, "G": 1e9,
    "T": 1e12, "P": 1e15, "E": 1e18, "Z": 1e21,
    "Y": 1e24, "R": 1e27, "Q": 1e30,
}

# Units that accept SI prefixes
PREFIXABLE = {
    "m", "g", "s", "A", "K", "mol", "cd", "Hz", "N", "J", "W", "Pa",
    "C", "V", "Ohm", "ohm", "Ω", "F", "L", "l", "liter", "rad", "eV",
}


def lookup_unit(token: str) -> Tuple[float, Dimension] | None:
    """Resolve a unit token with optional SI prefix."""
    if token in UNITS:
        return UNITS[token]
    # try prefix: longest prefix first ("da" before single letters)
    for i in (2, 1):
        if len(token) > i:
            pre, base = token[:i], token[i:]
            if pre in SI_PREFIXES and base in PREFIXABLE:
                u = UNITS[base]
                return (SI_PREFIXES[pre] * u[0], u[1])
    return None


def format_dimension(dim: Dimension) -> str:
    """Render a dimension vector, e.g. L·M·T^-2."""
    if dim == DIMENSIONLESS:
        return "1 (dimensionless)"
    parts = []
    for name, exp in zip(DIM_NAMES, dim):
        if exp == 0:
            continue
        parts.append(name if exp == 1 else f"{name}^{exp}")
    return "·".join(parts)
