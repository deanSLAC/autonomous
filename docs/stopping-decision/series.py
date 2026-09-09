"""The four example series used in the figures, and the real analysis of each."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simdata as S
from beamtimehero_cli.science.statistics.efficiency import analyze_scan_efficiency
from beamtimehero_cli.science.statistics.features import (
    extract_window_scalar, analyze_scalar_convergence)

EMIN, EMAX = S.EMIN_W, S.EMAX_W


def _pack(name, energy, reps, counts, target_frac):
    m = S.window_mask(energy)
    eff = analyze_scan_efficiency(reps[:, m].tolist(),
                                  raw_counts_per_point=counts[:, m].tolist(),
                                  sem_threshold_frac=target_frac)
    ex = extract_window_scalar(reps.tolist(), energy.tolist(), EMIN, EMAX, 'integral')
    conv = analyze_scalar_convergence(ex['per_rep_values'])
    return dict(name=name, energy=energy, reps=reps, counts=counts, mask=m,
                eff=eff, scalar=np.array(ex['per_rep_values']), conv=conv,
                target=target_frac * 100)


def series_A():
    """Photon-limited: genuine repeats, dilute sample, target 1%."""
    e, r, c = S.make_stack(12, seed=970)
    return _pack('A', e, r, c, 0.01)


def series_B():
    """Systematics-limited: spot wanders from rep 6; demanding 0.3% target."""
    e, r, c = S.make_stack(14, seed=4, counts_at_edge=12000,
                           wl_jitter=0.10, jitter_from=6)
    return _pack('B', e, r, c, 0.003)


def series_C():
    """Drifting: progressive photoreduction from rep 4, target 1%."""
    e, r, c = S.make_stack(12, seed=3, drift_per_rep=0.014, drift_from=4)
    return _pack('C', e, r, c, 0.01)


def series_D():
    """Late disturbance at rep 10: no monotone trend, but the running SEM turns
    back up — the self-contradiction veto."""
    e, r, c = S.make_stack(12, seed=110, wl_jitter=0.04, jitter_from=10)
    return _pack('D', e, r, c, 0.01)
