"""Simulated but physically-plausible Fe K-edge XAS rep stack.

Two series:
  A "stationary"  — genuine repeats, counting-noise only
  B "drifting"    — progressive photoreduction pulling the white line down
Both carry raw counts so the counting-statistics floor is computable.
"""
import numpy as np

E0 = 7112.0
EMIN_W, EMAX_W = 7124.0, 7140.0          # feature (white-line) window
COUNTS_AT_EDGE = 1350.0                   # per-rep counts at the top of the edge
EDGE_TOP = 1.5                            # normalised mu at which counts = COUNTS_AT_EDGE
BACKGROUND_FRAC = 0.05                    # pre-edge counts as a fraction of the edge-top counts


def _mu(energy, wl_scale=1.0):
    """Edge-step-normalised absorption: pre-edge 0, post-edge 1."""
    e = np.asarray(energy, float)
    # arctan edge
    step = 0.5 + np.arctan((e - E0 - 4.0) / 2.6) / np.pi
    # white line (Lorentzian-ish) on top of the step
    wl = 0.52 * wl_scale / (1.0 + ((e - 7131.0) / 3.4) ** 2)
    # small pre-edge 1s->3d feature
    pre = 0.045 / (1.0 + ((e - 7113.5) / 1.6) ** 2)
    # damped EXAFS oscillations above the edge
    k = np.sqrt(np.maximum(e - E0, 0.0)) * 0.512
    exafs = 0.075 * np.exp(-0.055 * k ** 2) * np.sin(2 * 2.9 * k + 1.1)
    exafs = np.where(e > E0 + 18, exafs, 0.0)
    return step + wl + pre + exafs


def make_stack(n_reps, drift_per_rep=0.0, drift_from=1, seed=0,
               counts_at_edge=COUNTS_AT_EDGE, wl_jitter=0.0, jitter_from=1,
               background_frac=BACKGROUND_FRAC):
    """Return (energy, normalised reps (n,p), raw counts (n,p))."""
    rng = np.random.default_rng(seed)
    energy = np.arange(7060.0, 7260.01, 0.5)
    b = background_frac
    reps, counts = [], []
    for i in range(n_reps):
        scale = 1.0 - drift_per_rep * max(i - (drift_from - 1), 0)
        if wl_jitter and i >= jitter_from - 1:
            scale += rng.normal(0.0, wl_jitter)
        clean = _mu(energy, wl_scale=scale)
        # counts track the absorption: flat background pre-edge, rising over edge
        lam = counts_at_edge * (b + (1.0 - b) * np.clip(clean, 0, None) / EDGE_TOP)
        n = rng.poisson(np.maximum(lam, 1.0)).astype(float)
        # The measured spectrum is whatever the recorded counts imply, so the
        # counting noise reaches it through the background subtraction and the
        # edge-step division rather than being pasted onto the clean shape.
        # That propagation is why a real measurement sits a few percent *above*
        # 1/sqrt(N) rather than exactly on it: the bracket
        # [1 + b/(edge step * mu)] is always >= 1.
        noisy = (n / counts_at_edge - b) * EDGE_TOP / (1.0 - b)
        reps.append(noisy)
        counts.append(n)
    return energy, np.array(reps), np.array(counts)


def window_mask(energy, e_min=EMIN_W, e_max=EMAX_W):
    e = np.asarray(energy, float)
    return (e >= e_min) & (e <= e_max)
