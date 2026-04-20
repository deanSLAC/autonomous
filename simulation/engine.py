"""Mock scan generator for simulation mode.

Writes physics-plausible SPEC scan blocks (#S/#D/#T/#P/#L + data rows)
to files that silx can read back through the normal `local_data.py`
path. The agent never knows the difference: it issues a SPEC command,
the mock screen calls into here, a real file appears on disk, and the
next `get_latest_scan` call surfaces it.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# K-edge energies for the elements the agent is most likely to scan (eV).
EDGE_ENERGIES_EV: dict[str, float] = {
    "Ti": 4966, "V": 5465, "Cr": 5989, "Mn": 6539, "Fe": 7112,
    "Co": 7709, "Ni": 8333, "Cu": 8979, "Zn": 9659,
}

# The 12 motors emitted on every #P0 line (must match the order on #O0).
_MOTOR_ORDER = [
    "m1vert", "m1pitch", "m2vert", "m2horz", "pitcha", "pitchb",
    "energy", "Sx", "Sy", "Sz", "mono", "gap",
]
_DEFAULT_POSITIONS: dict[str, float] = {
    "m1vert": 1.93, "m1pitch": 0.0, "m2vert": 0.0, "m2horz": 0.0,
    "pitcha": 0.0, "pitchb": 0.0, "energy": 7100.0, "Sx": 0.0,
    "Sy": 0.0, "Sz": 10.0, "mono": 7100.0, "gap": 38.0,
}


@dataclass
class _State:
    scan_dir: Optional[Path] = None
    current_file: str = "mock.01"
    scan_n_per_file: dict[str, int] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(42))


_state = _State()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def configure(scan_dir: Path, default_file: str = "mock.01") -> None:
    _state.scan_dir = Path(scan_dir)
    _state.scan_dir.mkdir(parents=True, exist_ok=True)
    _state.current_file = default_file


def is_active() -> bool:
    return _state.scan_dir is not None


def set_current_file(name: str) -> None:
    _state.current_file = name


def current_file() -> str:
    return _state.current_file


def status() -> dict:
    scans: dict[str, int] = {}
    if _state.scan_dir is not None:
        for child in sorted(_state.scan_dir.iterdir()):
            if child.is_file() and not child.name.startswith("."):
                n = _highest_existing_n(child.name)
                if n:
                    scans[child.name] = n
    return {
        "active": is_active(),
        "scan_dir": str(_state.scan_dir) if _state.scan_dir else None,
        "current_file": _state.current_file,
        "scans_per_file": scans,
    }


# ---------------------------------------------------------------------------
# Public scan-generating API
# ---------------------------------------------------------------------------

def append_xas_scan(
    element: str,
    count_time: float,
    n_points: int = 101,
    *,
    file_name: Optional[str] = None,
    positions: Optional[dict] = None,
) -> dict:
    edge = EDGE_ENERGIES_EV.get(element, _DEFAULT_POSITIONS["energy"])
    return _append_scan(
        fname=file_name or _state.current_file,
        motor="energy",
        lo=edge - 50,
        hi=edge + 200,
        n=n_points,
        ct=count_time,
        edge=edge,
        positions=positions,
        scan_command=f"{element}_xas {count_time} 1",
        kind="edge",
    )


def append_emiss_scan(
    element: str,
    count_time: float,
    n_points: int = 81,
    *,
    file_name: Optional[str] = None,
    positions: Optional[dict] = None,
) -> dict:
    edge = EDGE_ENERGIES_EV.get(element, 7000.0)
    emiss_center = edge - 700  # rough Kalpha line offset for first-row TM
    return _append_scan(
        fname=file_name or _state.current_file,
        motor="emiss",
        lo=emiss_center - 30,
        hi=emiss_center + 30,
        n=n_points,
        ct=count_time,
        edge=emiss_center,
        positions=positions,
        scan_command=f"{element}_cee {count_time} 1 {emiss_center} 0",
        kind="peak",
    )


def append_ascan(
    motor: str,
    lo: float,
    hi: float,
    n: int,
    ct: float,
    *,
    file_name: Optional[str] = None,
    positions: Optional[dict] = None,
) -> dict:
    is_energy = motor.lower() in ("energy", "mono", "emiss")
    return _append_scan(
        fname=file_name or _state.current_file,
        motor=motor,
        lo=lo,
        hi=hi,
        n=n,
        ct=ct,
        edge=(lo + hi) / 2,
        positions=positions,
        scan_command=f"ascan {motor} {lo} {hi} {n} {ct}",
        kind="edge" if is_energy else "peak",
    )


def append_alias_scan(
    alias: str,
    *,
    file_name: Optional[str] = None,
    positions: Optional[dict] = None,
) -> dict:
    """Handle SPEC shortcut commands like `vvv`, `hhh`, `m1m1` etc.

    Each shortcut maps to a scan over a specific motor with sensible
    defaults so the file lands on disk with realistic shape.
    """
    motor_for: dict[str, tuple[str, float, float, int, float]] = {
        # alias: (motor, lo_delta, hi_delta, n, ct)
        "vvv":   ("m1vert", -0.2, 0.2, 41, 0.5),
        "hhh":   ("m2horz", -0.3, 0.3, 31, 0.5),
        "m1m1":  ("m1pitch", -0.05, 0.05, 21, 0.5),
        "m2m2":  ("pitcha", -0.05, 0.05, 21, 0.5),
        "ggg":   ("gap", -0.1, 0.1, 21, 0.5),
        "bxbx":  ("Sx", -0.5, 0.5, 31, 0.3),
        "bzbz":  ("Sz", -0.5, 0.5, 31, 0.3),
        "dmm":   ("energy", -10, 10, 21, 0.5),
        "beamx": ("Sx", -1.0, 1.0, 41, 0.3),
        "beamz": ("Sz", -1.0, 1.0, 41, 0.3),
        "cm1m1": ("m1pitch", -0.02, 0.02, 21, 0.5),
        "cm2m2": ("pitcha", -0.02, 0.02, 21, 0.5),
    }
    spec = motor_for.get(alias)
    if spec is None:
        spec = ("m1vert", -0.1, 0.1, 21, 0.5)
    motor, dlo, dhi, n, ct = spec
    base = (positions or {}).get(motor, _DEFAULT_POSITIONS.get(motor, 0.0))
    return _append_scan(
        fname=file_name or _state.current_file,
        motor=motor,
        lo=base + dlo,
        hi=base + dhi,
        n=n,
        ct=ct,
        edge=base,
        positions=positions,
        scan_command=f"{alias}",
        kind="peak",
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _next_n(fname: str) -> int:
    if fname not in _state.scan_n_per_file:
        # First touch this process — pick up where the file left off.
        _state.scan_n_per_file[fname] = _highest_existing_n(fname)
    n = _state.scan_n_per_file[fname] + 1
    _state.scan_n_per_file[fname] = n
    return n


def _highest_existing_n(fname: str) -> int:
    if _state.scan_dir is None:
        return 0
    path = _state.scan_dir / fname
    if not path.exists():
        return 0
    highest = 0
    try:
        for line in path.read_text().splitlines():
            if line.startswith("#S "):
                tok = line[3:].split(None, 1)[0]
                try:
                    highest = max(highest, int(tok))
                except ValueError:
                    continue
    except OSError:
        return 0
    return highest


def _ensure_header(path: Path) -> None:
    if path.exists():
        return
    epoch = int(time.time())
    date = datetime.fromtimestamp(epoch).strftime("%a %b %d %H:%M:%S %Y")
    header = (
        f"#F {path.name}\n"
        f"#E {epoch}\n"
        f"#D {date}\n"
        f"#C beamtimehero  User = mock\n"
        f"\n"
        f"#O0 {' '.join(_MOTOR_ORDER)}\n"
        f"\n"
    )
    path.write_text(header)


def _positions_line(positions: Optional[dict]) -> str:
    pos = dict(_DEFAULT_POSITIONS)
    if positions:
        pos.update({k: v for k, v in positions.items() if k in _MOTOR_ORDER})
    return " ".join(f"{pos.get(k, 0.0):.4f}" for k in _MOTOR_ORDER)


def _append_scan(
    *,
    fname: str,
    motor: str,
    lo: float,
    hi: float,
    n: int,
    ct: float,
    edge: float,
    positions: Optional[dict],
    scan_command: str,
    kind: str,
) -> dict:
    if _state.scan_dir is None:
        raise RuntimeError("simulation.engine.configure() not called")
    n = max(2, int(n))
    path = _state.scan_dir / fname
    _ensure_header(path)

    sn = _next_n(fname)
    epoch = time.time()
    date = datetime.fromtimestamp(epoch).strftime("%a %b %d %H:%M:%S %Y")
    motor_vals = _positions_line(positions)

    xs, i0, idet, icr, epochs = _gen_data(lo, hi, n, ct, edge, kind)

    block = [
        "",
        f"#S {sn} {scan_command}",
        f"#D {date}",
        f"#T {ct}  (Seconds)",
        "#G0 0",
        "#Q",
        f"#P0 {motor_vals}",
        "#N 5",
        f"#L {motor}  I0  ID  ICR  Epoch",
    ]
    for x_, a_, b_, c_, t_ in zip(xs, i0, idet, icr, epochs):
        block.append(f"{x_:.4f}  {a_:.2f}  {b_:.4f}  {c_:.2f}  {t_:.2f}")
    block.append("")
    with path.open("a") as f:
        f.write("\n".join(block))

    summary = {
        "file_name": fname,
        "scan_number": sn,
        "scan_command": scan_command,
        "motor": motor,
        "n_points": n,
        "kind": kind,
    }
    if kind == "edge":
        summary["edge_step"] = round(max(idet) - min(idet), 3)
        summary["edge_energy_ev"] = edge
    elif kind == "peak":
        summary["peak_value"] = round(max(idet), 2)
        summary["peak_position"] = round(xs[idet.index(max(idet))], 4)
    return summary


def _gen_data(lo: float, hi: float, n: int, ct: float,
              edge: float, kind: str):
    rng = _state.rng
    xs = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    base_i0 = 1.2e5
    i0 = [base_i0 * (1.0 + 0.005 * (rng.random() - 0.5)) for _ in xs]
    if kind == "edge":
        idet = []
        for x in xs:
            step = 0.5 + math.atan((x - edge) / 3.0) / math.pi
            if x > edge:
                osc = 0.04 * math.sin((x - edge) / 12.0) * math.exp(-((x - edge) ** 2) / 60000)
            else:
                osc = 0.0
            mu = 0.10 + 0.85 * step + osc + 0.005 * (rng.random() - 0.5)
            idet.append(mu * base_i0 / 100.0)
    else:
        center = edge
        width = max((hi - lo) / 8.0, 1e-6)
        idet = []
        for x in xs:
            y = math.exp(-((x - center) / width) ** 2)
            idet.append(950.0 * y + 30.0 + 8.0 * rng.random())
    icr = [80.0 + 6.0 * rng.random() for _ in xs]
    t0 = time.time()
    epochs = [t0 + ct * i for i in range(n)]
    return xs, i0, idet, icr, epochs
