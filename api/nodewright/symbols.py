"""Built-in schematic symbols (design §15): icons with pins.

Each is drawn in a 100x100 box with its leads running to the box edge, so a
pin `{side, at}` sits exactly where a lead ends; placed symbols stay square
so that holds at any size. Strokes are black: symbols are tinted (drawn as a
mask in the node's colour). Ids are `sym-<name>`; icons.builtins() serves
them next to the Lucide set, run through svgsafe.clean() like any icon.
"""

from __future__ import annotations

PREFIX = "sym-"
SW = 3  # stroke width in box units: 2.4 px on an 80 px symbol, close to a 2 px line


def _svg(body: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" '
            f'stroke="#000" stroke-width="{SW}" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>')


def _p(d: str) -> str:
    return f'<path d="{d}"/>'


def _fill(points: str) -> str:
    return f'<polygon points="{points}" fill="#000"/>'


def _circle(cx, cy, r, filled=False) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"' + (' fill="#000"' if filled else "") + "/>"


def _pin(pid: str, side: str, at: float = 0.5) -> dict:
    return {"id": pid, "side": side, "at": at}


TWO = [_pin("1", "left"), _pin("2", "right")]
VERT = [_pin("1", "top"), _pin("2", "bottom")]
GATE2 = [_pin("A", "left", 0.35), _pin("B", "left", 0.65), _pin("Y", "right")]
GATE1 = [_pin("A", "left"), _pin("Y", "right")]

_OR = "M18 20 Q60 20 82 50 Q60 80 18 80 Q32 50 18 20 Z"
_NOR = "M18 20 Q56 20 76 50 Q56 80 18 80 Q32 50 18 20 Z"

# name, category, body, pins[, size]
_DEFS: list[tuple] = [
    # passive
    ("resistor", "Passive", _p("M0 50 H20 L25 38 L35 62 L45 38 L55 62 L65 38 L75 62 L80 50 H100"), TWO),
    ("capacitor", "Passive", _p("M0 50 H44 M44 28 V72 M56 28 V72 M56 50 H100"), TWO),
    ("capacitor-polarized", "Passive",
     _p("M0 50 H44 M44 28 V72 M62 28 Q52 50 62 72 M56 50 H100 M28 30 H36 M32 26 V34"),
     [_pin("+", "left"), _pin("-", "right")]),
    ("inductor", "Passive",
     _p("M0 50 H18 A8 8 0 0 1 34 50 A8 8 0 0 1 50 50 A8 8 0 0 1 66 50 A8 8 0 0 1 82 50 H100"), TWO),
    ("potentiometer", "Passive",
     _p("M0 50 H20 L25 38 L35 62 L45 38 L55 62 L65 38 L75 62 L80 50 H100 M50 0 V26")
     + _fill("43,24 57,24 50,36"),
     TWO + [_pin("W", "top")]),
    ("fuse", "Passive", _p("M0 50 H100") + '<rect x="22" y="40" width="56" height="20" rx="2"/>', TWO),
    ("crystal", "Passive",
     _p("M0 50 H34 M34 30 V70 M66 30 V70 M66 50 H100") + '<rect x="42" y="24" width="16" height="52"/>', TWO),
    ("transformer", "Passive",
     _p("M0 20 H30 A7.5 7.5 0 0 1 30 35 A7.5 7.5 0 0 1 30 50 A7.5 7.5 0 0 1 30 65 A7.5 7.5 0 0 1 30 80 H0 "
        "M100 20 H70 A7.5 7.5 0 0 0 70 35 A7.5 7.5 0 0 0 70 50 A7.5 7.5 0 0 0 70 65 A7.5 7.5 0 0 0 70 80 H100 "
        "M46 16 V84 M54 16 V84"),
     [_pin("P1", "left", 0.2), _pin("P2", "left", 0.8), _pin("S1", "right", 0.2), _pin("S2", "right", 0.8)]),
    # semiconductors
    ("diode", "Semiconductors", _p("M0 50 H35 M65 30 V70 M65 50 H100") + _fill("35,30 35,70 65,50"),
     [_pin("A", "left"), _pin("K", "right")]),
    ("led", "Semiconductors",
     _p("M0 50 H35 M65 30 V70 M65 50 H100 M56 24 L66 14 M66 32 L76 22") + _fill("35,30 35,70 65,50")
     + _fill("70,10 61,13 67,19") + _fill("80,18 71,21 77,27"),
     [_pin("A", "left"), _pin("K", "right")]),
    ("zener", "Semiconductors", _p("M0 50 H35 M58 26 L65 30 V70 L72 74 M65 50 H100") + _fill("35,30 35,70 65,50"),
     [_pin("A", "left"), _pin("K", "right")]),
    ("npn", "Semiconductors",
     _circle(55, 50, 31) + _p("M0 50 H40 M40 32 V68 M40 42 L70 26 V0 M40 58 L70 74 V100")
     + _fill("67,73 55,72 60,63"),
     [_pin("B", "left"), _pin("C", "top", 0.7), _pin("E", "bottom", 0.7)]),
    ("pnp", "Semiconductors",
     _circle(55, 50, 31) + _p("M0 50 H40 M40 32 V68 M40 42 L70 26 V0 M40 58 L70 74 V100")
     + _fill("45,40 57,40 52,31"),
     [_pin("B", "left"), _pin("E", "top", 0.7), _pin("C", "bottom", 0.7)]),
    ("nmos", "Semiconductors",
     _p("M0 50 H32 M32 30 V70 M42 24 V36 M42 44 V56 M42 64 V76 M42 30 H70 V0 M42 70 H70 V100 M52 50 H70 V70")
     + _fill("43,50 54,44 54,56"),
     [_pin("G", "left"), _pin("D", "top", 0.7), _pin("S", "bottom", 0.7)]),
    ("pmos", "Semiconductors",
     _p("M0 50 H32 M32 30 V70 M42 24 V36 M42 44 V56 M42 64 V76 M42 30 H70 V0 M42 70 H70 V100 M42 50 H58 M70 50 V30")
     + _fill("69,50 58,44 58,56"),
     [_pin("G", "left"), _pin("S", "top", 0.7), _pin("D", "bottom", 0.7)]),
    # sources and power
    ("battery", "Sources and power",
     _p("M0 50 H40 M40 28 V72 M50 38 V62 M60 28 V72 M70 38 V62 M70 50 H100 M22 30 H30 M26 26 V34"),
     [_pin("+", "left"), _pin("-", "right")]),
    ("voltage-source", "Sources and power",
     _circle(50, 50, 28) + _p("M50 0 V22 M50 78 V100 M44 38 H56 M50 32 V44 M44 64 H56"),
     [_pin("+", "top"), _pin("-", "bottom")]),
    ("ac-source", "Sources and power",
     _circle(50, 50, 28) + _p("M50 0 V22 M50 78 V100 M34 50 Q42 34 50 50 T66 50"), VERT),
    ("current-source", "Sources and power",
     _circle(50, 50, 28) + _p("M50 0 V22 M50 78 V100 M50 68 V40") + _fill("50,30 43,42 57,42"),
     [_pin("out", "top"), _pin("in", "bottom")]),
    ("ground", "Sources and power", _p("M50 0 V50 M24 50 H76 M33 62 H67 M42 74 H58"),
     [_pin("1", "top")], 60),
    ("supply", "Sources and power", _p("M50 100 V40 M28 40 H72"), [_pin("1", "bottom")], 60),
    # logic and ICs
    ("op-amp", "Logic and ICs",
     '<polygon points="20,10 20,90 86,50"/>' + _p("M0 30 H20 M0 70 H20 M86 50 H100 M26 30 H36 M26 70 H36 M31 65 V75"),
     [_pin("-", "left", 0.3), _pin("+", "left", 0.7), _pin("out", "right")]),
    ("buffer", "Logic and ICs", '<polygon points="22,20 22,80 76,50"/>' + _p("M0 50 H22 M76 50 H100"), GATE1),
    ("not", "Logic and ICs",
     '<polygon points="22,20 22,80 68,50"/>' + _circle(75, 50, 6) + _p("M0 50 H22 M81 50 H100"), GATE1),
    ("and", "Logic and ICs", _p("M20 20 H50 A30 30 0 0 1 50 80 H20 Z M0 35 H20 M0 65 H20 M80 50 H100"), GATE2),
    ("nand", "Logic and ICs",
     _p("M20 20 H44 A30 30 0 0 1 44 80 H20 Z M0 35 H20 M0 65 H20 M86 50 H100") + _circle(80, 50, 6), GATE2),
    ("or", "Logic and ICs", _p(_OR + " M0 35 H25 M0 65 H25 M82 50 H100"), GATE2),
    ("nor", "Logic and ICs", _p(_NOR + " M0 35 H25 M0 65 H25 M88 50 H100") + _circle(82, 50, 6), GATE2),
    ("xor", "Logic and ICs", _p(_OR + " M8 80 Q22 50 8 20 M0 35 H15 M0 65 H15 M82 50 H100"), GATE2),
    # switches and other
    ("switch", "Switches and other",
     _p("M0 50 H28 M36 48 L68 30 M72 50 H100") + _circle(32, 50, 4) + _circle(68, 50, 4), TWO),
    ("push-button", "Switches and other",
     _p("M0 60 H28 M72 60 H100 M24 46 H76 M50 46 V30 M42 30 H58") + _circle(32, 60, 4) + _circle(68, 60, 4),
     [_pin("1", "left", 0.6), _pin("2", "right", 0.6)]),
    ("lamp", "Switches and other", _circle(50, 50, 24) + _p("M0 50 H26 M74 50 H100 M33 33 L67 67 M67 33 L33 67"), TWO),
    ("motor", "Switches and other", _circle(50, 50, 24) + _p("M0 50 H26 M74 50 H100 M40 60 V40 L50 52 L60 40 V60"), TWO),
    ("antenna", "Switches and other", _p("M50 100 V30 M28 8 L50 30 L72 8 Z"), [_pin("1", "bottom")], 60),
    ("terminal", "Switches and other", _circle(70, 50, 10) + _p("M0 50 H60"), [_pin("1", "left")], 40),
    # A junction dot: wires meeting at one of its four sides meet at the dot.
    ("junction", "Switches and other", _circle(50, 50, 50, filled=True),
     [_pin("t", "top"), _pin("r", "right"), _pin("b", "bottom"), _pin("l", "left")], 16),
]


def definitions() -> list[dict]:
    """[{id, name, category, size, ports, svg}] in palette order."""
    out = []
    for d in _DEFS:
        name, category, body, pins = d[:4]
        size = d[4] if len(d) > 4 else 80
        out.append({"id": PREFIX + name, "name": name.replace("-", " ").capitalize(),
                    "category": category, "size": size, "ports": [dict(p) for p in pins],
                    "svg": _svg(body)})
    return out
