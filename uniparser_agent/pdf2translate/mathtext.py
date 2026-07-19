"""Convert UniParser inline LaTeX math ($...$) into display text for PDF overlay."""

from __future__ import annotations

import re
from typing import Any

# Unicode sub/superscript maps (common scientific glyphs).
_SUB = str.maketrans(
    "0123456789+-=()aeioruvx",
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵣᵤᵥₓ",
)
_SUP = str.maketrans(
    "0123456789+-=()n*",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ*",
)

_GREEK = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\iota": "ι",
    r"\kappa": "κ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
}

_SYMBOLS = {
    r"\ldots": "…",
    r"\cdots": "⋯",
    r"\cdot": "·",
    r"\times": "×",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\sim": "∼",
    r"\infty": "∞",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\int": "∫",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\rightarrow": "→",
    r"\leftarrow": "←",
    r"\Rightarrow": "⇒",
    r"\Leftrightarrow": "⇔",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\forall": "∀",
    r"\exists": "∃",
}


_INLINE_MATH_RE = re.compile(
    r"\$\$(.+?)\$\$|\$([^$]+)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]",
    re.DOTALL,
)


def _font_has(font: Any | None, ch: str) -> bool:
    if font is None or not ch:
        return True
    try:
        return bool(font.has_glyph(ord(ch)))
    except Exception:  # noqa: BLE001
        return True


def _to_sub(s: str, font: Any | None = None) -> str:
    extra = {
        "a": "ₐ",
        "e": "ₑ",
        "h": "ₕ",
        "i": "ᵢ",
        "j": "ⱼ",
        "k": "ₖ",
        "K": "ₖ",
        "l": "ₗ",
        "m": "ₘ",
        "n": "ₙ",
        "o": "ₒ",
        "p": "ₚ",
        "r": "ᵣ",
        "s": "ₛ",
        "t": "ₜ",
        "u": "ᵤ",
        "v": "ᵥ",
        "x": "ₓ",
    }
    out = []
    for ch in s:
        if ch in extra:
            out.append(extra[ch])
        else:
            out.append(ch.translate(_SUB))
    uni = "".join(out)
    if font is not None and any(not _font_has(font, ch) for ch in uni):
        # CJK body fonts often lack Unicode subscripts — keep ASCII.
        return s
    return uni


def _to_sup(s: str, font: Any | None = None) -> str:
    out = []
    for ch in s:
        if ch == "*":
            out.append("∗")
        else:
            out.append(ch.translate(_SUP))
    uni = "".join(out)
    if font is not None and any(not _font_has(font, ch) for ch in uni):
        return "^" + s
    return uni


def latex_inner_to_display(latex: str, *, font: Any | None = None) -> str:
    """Convert the inside of `$...$` to a readable Unicode string."""
    s = latex.strip()
    # Spacing / escapes commonly emitted by UniParser.
    s = s.replace(r"\%", "%")
    s = s.replace(r"\&", "&")
    s = s.replace(r"\_", "_")
    s = s.replace(r"\#", "#")
    s = s.replace(r"\,", " ")
    s = s.replace(r"\;", " ")
    s = s.replace(r"\:", " ")
    s = s.replace(r"\!", "")
    s = s.replace(r"\\", "↵")

    s = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\operatorname\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^{}]*)\}", r"\1", s)

    def _hat(m: re.Match[str]) -> str:
        inner = m.group(1)
        hats = {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û", "A": "Â"}
        return hats.get(inner, inner + "\u0302")

    s = re.sub(r"\\hat\{([^{}]*)\}", _hat, s)
    s = re.sub(r"\\bar\{([^{}]*)\}", r"\1̄", s)
    s = re.sub(r"\\tilde\{([^{}]*)\}", r"\1̃", s)

    for cmd, glyph in sorted(_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        s = s.replace(cmd, glyph)
    for cmd, glyph in sorted(_GREEK.items(), key=lambda kv: -len(kv[0])):
        glyph_out = glyph if _font_has(font, glyph) else cmd.lstrip("\\")
        s = s.replace(cmd, glyph_out)

    s = re.sub(r"_\{([^{}]+)\}", lambda m: _to_sub(m.group(1), font), s)
    s = re.sub(r"\^\{([^{}]+)\}", lambda m: _to_sup(m.group(1), font), s)
    s = re.sub(r"_([A-Za-z0-9])", lambda m: _to_sub(m.group(1), font), s)
    s = re.sub(r"\^([A-Za-z0-9*+\-]+)", lambda m: _to_sup(m.group(1), font), s)

    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def render_inline_math(text: str, *, font: Any | None = None) -> str:
    """Replace inline LaTeX math segments with display forms for overlay drawing."""

    def _repl(match: re.Match[str]) -> str:
        inner = next(g for g in match.groups() if g is not None)
        return latex_inner_to_display(inner, font=font)

    return _INLINE_MATH_RE.sub(_repl, text)
