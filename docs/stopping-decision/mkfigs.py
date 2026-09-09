"""Render every figure for stopping-decision.html as a standalone inline SVG.

All plotted numbers come from the shipped implementation in
beamtimehero_cli.science.statistics — nothing here re-implements the maths.
Figure numbers and captions live in the HTML, not in the artwork.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FixedFormatter
from matplotlib.colors import LinearSegmentedColormap
import series as X
from beamtimehero_cli.science.statistics.efficiency import _c4

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figs')
os.makedirs(OUT, exist_ok=True)

INK, MUTE, GRID = '#1a1a1a', '#5f5c55', '#e3dfd6'
BLUE, ORANGE, AQUA, VIOLET = '#2a78d6', '#eb6834', '#1baf7a', '#4a3aa7'
RED, GREEN, BAND, TRIM = '#d03b3b', '#1a7f37', '#eaf1fb', '#efe9dc'
REPRAMP = LinearSegmentedColormap.from_list('rep', ['#bcd7f8', '#0d366b'])

plt.rcParams.update({
    'svg.fonttype': 'none', 'font.size': 9.5, 'font.family': 'sans-serif',
    'axes.edgecolor': '#b9b3a6', 'axes.linewidth': 0.8, 'axes.labelcolor': INK,
    'axes.titlesize': 9.5, 'axes.titleweight': 'bold', 'axes.titlecolor': INK,
    'axes.titlelocation': 'left', 'axes.titlepad': 6,
    'xtick.color': MUTE, 'ytick.color': MUTE, 'xtick.labelsize': 8.5,
    'ytick.labelsize': 8.5, 'grid.color': GRID, 'grid.linewidth': 0.7,
    'legend.frameon': False, 'legend.fontsize': 8.5, 'legend.labelcolor': INK,
    'figure.facecolor': 'none', 'axes.facecolor': 'none',
    'savefig.facecolor': 'none', 'lines.solid_capstyle': 'round',
})
BOX = dict(boxstyle='round,pad=0.34', fc='#ffffff', ec='none', alpha=0.86)


def style(ax, grid='y'):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    if grid:
        ax.grid(True, axis=grid, zorder=0)
        ax.set_axisbelow(True)
    return ax


def save(fig, name):
    path = os.path.join(OUT, name + '.svg')
    fig.savefig(path, format='svg', bbox_inches='tight', pad_inches=0.06,
                transparent=True)
    plt.close(fig)
    svg = open(path).read()
    svg = re.sub(r'<\?xml[^>]*\?>\s*', '', svg)
    svg = re.sub(r'<!DOCTYPE[^>]*>\s*', '', svg)
    svg = re.sub(r'<!--.*?-->', '', svg, flags=re.S)
    svg = svg.replace('font-family: sans-serif', 'font-family: inherit')
    svg = re.sub(r'\sd="([^"]*)"',
                 lambda mo: ' d="%s"' % re.sub(r'(\d+\.\d{2})\d+', r'\1', mo.group(1)),
                 svg)
    svg = re.sub(r'\n\s+', '\n', svg)
    open(path, 'w').write(svg)
    print('wrote', name, len(svg) // 1024, 'kB')


A, B, C, D = X.series_A(), X.series_B(), X.series_C(), X.series_D()
EMIN, EMAX = X.EMIN, X.EMAX
import simdata as S


# ---------------------------------------------------------------- fig 1
def fig_reps():
    fig, ax = plt.subplots(figsize=(7.1, 3.15))
    style(ax, grid=False)
    e, reps = A['energy'], A['reps']
    for i in range(6):
        ax.plot(e, reps[i], lw=0.85, color=REPRAMP(i / 5.0), zorder=3)
    ax.set_xlim(7080, 7222); ax.set_ylim(-0.16, 1.80)
    ax.set_xlabel('photon energy  E  (eV)')
    ax.set_ylabel('normalised absorption  μ(E)')
    ax.axhline(0, color='#cfc9bb', lw=0.8, zorder=1)
    ax.axhline(1, color='#cfc9bb', lw=0.8, zorder=1)
    ax.annotate('pre-edge region — normalised to 0', (7082, -0.10), fontsize=8,
                color=MUTE, ha='left', va='center')
    ax.annotate('post-edge region — normalised to 1', (7220, 1.30), fontsize=8,
                color=MUTE, ha='right', va='center')
    ax.annotate('white line', (7131, 1.72), fontsize=8.5, color=INK, ha='center',
                va='center', fontweight='bold')
    ax.annotate('', xy=(7131, 1.60), xytext=(7131, 1.68),
                arrowprops=dict(arrowstyle='-', color=MUTE, lw=0.8))
    ax.annotate('pre-edge peak', (7104, 0.44), fontsize=8, color=MUTE, ha='center')
    ax.annotate('', xy=(7113.0, 0.24), xytext=(7107, 0.41),
                arrowprops=dict(arrowstyle='-', color=MUTE, lw=0.7))
    ax.annotate('EXAFS oscillations', (7178, 0.72), fontsize=8, color=MUTE, ha='center')
    ax.annotate('', xy=(7172, 0.93), xytext=(7176, 0.78),
                arrowprops=dict(arrowstyle='-', color=MUTE, lw=0.7))
    sm = plt.cm.ScalarMappable(cmap=REPRAMP, norm=plt.Normalize(1, 6))
    cb = fig.colorbar(sm, ax=ax, pad=0.014, aspect=24, ticks=[1, 6])
    cb.set_label('rep number', fontsize=8.5, color=MUTE)
    cb.ax.tick_params(labelsize=8, color=MUTE, length=0)
    cb.outline.set_visible(False)
    save(fig, 'fig1-reps')


# ---------------------------------------------------------------- fig 2
def fig_window():
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.85),
                             gridspec_kw={'width_ratios': [1.3, 1], 'wspace': 0.24})
    e, reps = A['energy'], A['reps']
    win = S.window_mask(e); ew = e[win]
    npts = ew.size; trim = max(1, npts // 20)

    ax = style(axes[0], grid=False)
    ax.axvspan(EMIN, EMAX, color=BAND, zorder=1)
    for i in range(6):
        ax.plot(e, reps[i], lw=0.75, color=REPRAMP(i / 5.0), zorder=3)
    ax.set_xlim(7080, 7222); ax.set_ylim(-0.12, 1.86)
    ax.set_xlabel('E  (eV)'); ax.set_ylabel('μ(E)')
    ax.set_title('whole spectrum')
    ax.annotate(f'feature window\n[{EMIN:.0f}, {EMAX:.0f}] eV',
                (0.5 * (EMIN + EMAX), 1.78), fontsize=8.5, color=INK, ha='center',
                va='top', fontweight='bold', linespacing=1.35)

    ax = style(axes[1], grid='both')
    m = (e >= EMIN - 3.5) & (e <= EMAX + 3.5)
    ax.axvspan(EMIN, EMAX, color=BAND, zorder=1)
    ax.axvspan(ew[0], ew[trim], color=TRIM, zorder=2)
    ax.axvspan(ew[-trim - 1], ew[-1], color=TRIM, zorder=2)
    for i in range(6):
        ax.plot(e[m], reps[i][m], lw=1.0, color=REPRAMP(i / 5.0), zorder=4)
    ax.set_xlim(EMIN - 3.5, EMAX + 3.5)
    ax.set_ylim(0.86, 1.78)
    ax.set_xlabel('E  (eV)')
    ax.set_title('window detail')
    ax.annotate('outer 5 % trimmed', (0.5 * (EMIN + EMAX), 1.72), fontsize=7.8,
                color=MUTE, ha='center', va='center')
    ax.annotate('', xy=(ew[trim], 1.66), xytext=(EMIN + 4.0, 1.70),
                arrowprops=dict(arrowstyle='-', color=MUTE, lw=0.7))
    ax.annotate('', xy=(ew[-trim - 1], 1.66), xytext=(EMAX - 4.0, 1.70),
                arrowprops=dict(arrowstyle='-', color=MUTE, lw=0.7))
    save(fig, 'fig2-window')


# ---------------------------------------------------------------- fig 3
def fig_merge():
    fig, ax = plt.subplots(figsize=(7.1, 3.05))
    style(ax, grid='both')
    e, reps = A['energy'], A['reps']
    win = S.window_mask(e); ew = e[win]
    npts = ew.size; trim = max(1, npts // 20)
    sem_curve = A['eff']['cumulative_sem_pct']
    for n, col in [(2, '#9ec5f4'), (4, BLUE), (12, '#0d366b')]:
        sub = reps[:n][:, win]
        mu = sub.mean(axis=0)
        sem = sub.std(axis=0, ddof=1) / (_c4(n) * np.sqrt(n))
        ax.fill_between(ew, mu - sem, mu + sem, color=col, alpha=0.30, lw=0, zorder=2)
        ax.plot(ew, mu, lw=1.5, color=col, zorder=4,
                label=f'n = {n}   →   SEM = {sem_curve[n-1]:.2f} %')
    ax.set_xlim(ew[0], ew[-1]); ax.set_ylim(0.90, 1.78)
    ax.set_xlabel('E  (eV)'); ax.set_ylabel('merged spectrum  μₙ(E)')
    ax.set_title('merge of the first n reps, ± SEM band')
    ax.legend(loc='upper right', ncol=1, handlelength=1.6)
    save(fig, 'fig3-merge')


# ---------------------------------------------------------------- fig 4
def fig_perpoint():
    fig, axes = plt.subplots(2, 1, figsize=(7.1, 4.4), sharex=True,
                             gridspec_kw={'hspace': 0.30})
    e, reps = A['energy'], A['reps']
    win = S.window_mask(e); ew, sub = e[win], reps[:, win]
    n = sub.shape[0]
    mu = sub.mean(axis=0); s = sub.std(axis=0, ddof=1)
    sem = s / (_c4(n) * np.sqrt(n))
    trim = max(1, ew.size // 20)

    ax = style(axes[0], grid='both')
    for i in range(n):
        ax.plot(ew, sub[i], lw=0.5, color='#cbdaee', zorder=2)
    ax.errorbar(ew, mu, yerr=s, fmt='none', ecolor='#7ea9dd', elinewidth=0.9,
                capsize=1.8, zorder=3)
    ax.plot(ew, mu, lw=1.7, color=BLUE, zorder=4)
    ax.set_ylabel('μ₁₂(E)')
    ax.set_title('a — merged spectrum with the between-rep scatter sₙ(E)')
    ax.set_ylim(0.88, 1.72)
    ax.annotate('thin lines: the 12 individual reps\nbars: ± sₙ(E)',
                (0.018, 0.94), xycoords='axes fraction', ha='left', va='top',
                fontsize=8, color=MUTE, linespacing=1.4, bbox=BOX)

    ax = style(axes[1], grid='both')
    rel = sem / mu * 100
    ax.axvspan(ew[0], ew[trim], color=TRIM, zorder=1)
    ax.axvspan(ew[-trim - 1], ew[-1], color=TRIM, zorder=1)
    ax.plot(ew, rel, lw=1.5, color=VIOLET, zorder=4)
    avg = float(np.mean(rel[trim:-trim]))
    ax.axhline(avg, color=INK, lw=1.2, ls=(0, (4, 3)), zorder=5)
    ax.set_ylim(0, max(rel.max() * 1.30, avg * 2.1))
    ax.annotate(f'window average  =  SEM(12) = {avg:.2f} %',
                (0.30, 0.86), xycoords='axes fraction', fontsize=8.5, color=INK,
                va='top', ha='left', bbox=BOX)
    ax.annotate('trimmed', (ew[trim // 2], ax.get_ylim()[1] * 0.90), fontsize=7.5,
                color=MUTE, ha='center', rotation=90, va='top')
    ax.set_xlabel('E  (eV)')
    ax.set_ylabel('relative SEM  (%)')
    ax.set_title('b — the same thing as a relative error at each energy')
    ax.set_xlim(ew[0], ew[-1])
    save(fig, 'fig4-perpoint')


# ---------------------------------------------------------------- fig 5
def fig_c4():
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.85),
                             gridspec_kw={'wspace': 0.30})
    ax = style(axes[0], grid='both')
    ns = np.arange(2, 31)
    c4 = np.array([_c4(int(k)) for k in ns])
    ax.plot(ns, c4, lw=1.6, color=ORANGE, marker='o', ms=3.2, mfc='white', mew=1.0,
            zorder=4)
    ax.axhline(1.0, color=MUTE, lw=0.9, ls=(0, (4, 3)), zorder=3)
    ax.annotate('unbiased limit,  E[s] = σ', (30, 1.008), fontsize=8, color=MUTE,
                ha='right', va='bottom')
    for k, dx, dy, ha in ((2, 0.6, -0.014, 'left'), (4, 0.6, -0.014, 'left'),
                          (8, 0.0, -0.016, 'center'), (14, 0.0, -0.016, 'center')):
        ax.annotate(f'{_c4(k):.3f}', (k + dx, _c4(k) + dy), fontsize=7.8,
                    color=INK, ha=ha, va='top')
    ax.set_ylim(0.745, 1.035)
    ax.set_xlabel('number of reps  n'); ax.set_ylabel('c₄(n) = E[s] / σ')
    ax.set_title('a — the bias factor')

    ax = style(axes[1], grid='both')
    e, reps = A['energy'], A['reps']
    win = S.window_mask(e); sub = reps[:, win]
    trim = max(1, int(win.sum()) // 20)
    raw, cor = [], []
    for n in range(2, 13):
        d = sub[:n]; mu = d.mean(axis=0); sd = d.std(axis=0, ddof=1)
        raw.append(np.mean((sd / np.sqrt(n) / mu)[trim:-trim]) * 100)
        cor.append(np.mean((sd / (_c4(n) * np.sqrt(n)) / mu)[trim:-trim]) * 100)
    ns2 = np.arange(2, 13)
    fl = np.array(A['eff']['cumulative_floor_pct'])[1:]
    ax.plot(ns2, fl, lw=1.4, color=MUTE, ls=(0, (5, 3)), zorder=3,
            label='counting-statistics floor')
    ax.plot(ns2, raw, lw=1.5, color='#b0a99a', marker='s', ms=3.2, zorder=4,
            label='s, uncorrected')
    ax.plot(ns2, cor, lw=1.7, color=BLUE, marker='o', ms=3.6, mfc='white', mew=1.1,
            zorder=5, label='s / c₄(n)')
    ax.set_xlabel('number of reps  n'); ax.set_ylabel('SEM  (% of signal)')
    ax.set_title('b — effect on the measured curve')
    ax.set_ylim(0.75, 3.05)
    ax.legend(loc='upper right', handlelength=1.8)
    save(fig, 'fig5-c4')


# ---------------------------------------------------------------- fig 6 / 7
def _floor_fig(d, name, xt):
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.0),
                             gridspec_kw={'width_ratios': [1.45, 1], 'wspace': 0.28})
    eff = d['eff']
    sem = np.array([np.nan if v is None else v for v in eff['cumulative_sem_pct']])
    fl = np.array(eff['cumulative_floor_pct'])
    ns = np.arange(1, sem.size + 1)

    ax = style(axes[0], grid='both')
    ax.plot(ns, fl, lw=1.5, color=MUTE, ls=(0, (5, 3)), zorder=3)
    ax.plot(ns, sem, lw=1.9, color=BLUE, marker='o', ms=4.2, mfc='white', mew=1.3,
            zorder=5)
    ax.axhline(d['target'], color=RED, lw=1.2, ls=(0, (1.6, 2.4)), zorder=4)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.xaxis.set_major_locator(FixedLocator(xt))
    ax.xaxis.set_major_formatter(FixedFormatter([str(v) for v in xt]))
    yt = [0.2, 0.3, 0.5, 1.0, 2.0, 3.0]
    yt = [v for v in yt if v <= np.nanmax(fl) * 1.4 and v >= min(np.nanmin(sem), d['target']) * 0.7]
    ax.yaxis.set_major_locator(FixedLocator(yt))
    ax.yaxis.set_major_formatter(FixedFormatter([f'{v:g}' for v in yt]))
    ax.minorticks_off()
    ax.set_xlabel('reps merged  n'); ax.set_ylabel('% of signal')
    ax.set_title('a — SEM(n) against the floor  (log–log)')
    ax.annotate('floor(n) ∝ 1/√n', (ns[-1], fl[-1] * 0.80), fontsize=8, color=MUTE,
                ha='right', va='top')
    ax.annotate(f'target {d["target"]:.1f} %', (ns[0] * 1.02, d['target'] * 1.08),
                fontsize=8, color=RED, va='bottom')
    ax.annotate('SEM(n)', (ns[2], sem[2] * 1.30), fontsize=8.5, color=BLUE,
                fontweight='bold', ha='center')
    if eff['plateau_from_rep']:
        p = eff['plateau_from_rep']
        ax.axvline(p, color=ORANGE, lw=1.1, ls=(0, (3, 3)), zorder=2)
        # Label on whichever side of the marker has room left on the axis.
        right = np.log(p / ns[0]) / np.log(ns[-1] / ns[0]) > 0.5
        ax.annotate(f'plateau_from_rep = {p}',
                    (p * (0.94 if right else 1.06), 0.97),
                    xycoords=('data', 'axes fraction'), fontsize=8,
                    color=ORANGE, fontweight='bold', va='top',
                    ha='right' if right else 'left')
    if eff['target_reached_at_rep']:
        t = eff['target_reached_at_rep']
        ax.plot([t], [sem[t - 1]], marker='o', ms=9, mfc='none', mec=RED, mew=1.7,
                zorder=6)

    ax = style(axes[1], grid='both')
    ratio = sem / fl
    base = float(np.nanmedian(ratio[1:4]))
    ax.axhspan(0, base * 1.25, color='#f3f7fd', zorder=1)
    ax.plot(ns, ratio, lw=1.7, color=VIOLET, marker='o', ms=3.8, mfc='white',
            mew=1.1, zorder=5)
    ax.axhline(1.0, color=MUTE, lw=1.0, ls=(0, (5, 3)), zorder=3)
    ax.axhline(base * 1.25, color=ORANGE, lw=1.1, ls=(0, (2, 2.5)), zorder=4)
    ax.annotate('departure threshold\n1.25 × opening ratio',
                (ns[-1], base * 1.25 * 1.05), fontsize=7.8, color=ORANGE,
                ha='right', va='bottom', linespacing=1.35)
    ax.annotate('photon-limited', (ns[0], base * 1.25 * 0.965), fontsize=7.8,
                color=MUTE, ha='left', va='top')
    ax.set_xlabel('reps merged  n'); ax.set_ylabel('SEM(n) / floor(n)')
    ax.set_title('b — ratio to the floor')
    ax.set_xticks(xt)
    # Scale to the series. A clean series lives in a narrow band just above 1
    # and a departure runs to twice the floor; a shared axis renders one of the
    # two as a flat line, and on the clean series it is the individual points
    # crossing 1 -- the thing the panel exists to show -- that disappear.
    ax.set_ylim(min(0.92, float(np.nanmin(ratio)) - 0.03),
                max(float(np.nanmax(ratio)), base * 1.25) * 1.12)
    save(fig, name)


def fig_floor():
    _floor_fig(A, 'fig6-floor-A', [1, 2, 3, 4, 6, 8, 12])
    _floor_fig(B, 'fig7-floor-B', [1, 2, 3, 4, 6, 8, 10, 14])


# ---------------------------------------------------------------- fig 8
def fig_trend():
    from scipy import stats as st
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.05), gridspec_kw={'wspace': 0.26})
    for ax, d, ttl in [(axes[0], A, 'a — series A: stationary'),
                       (axes[1], C, 'b — series C: photoreduction')]:
        style(ax, grid='both')
        x = d['scalar']; n = x.size; r = np.arange(1, n + 1)
        mean = x.mean()
        sl, ic, _, _ = st.theilslopes(x, r.astype(float))
        ax.plot(r, (ic + sl * r) / mean * 100, lw=1.8, color=ORANGE, zorder=4)
        ax.plot(r, x / mean * 100, lw=0, marker='o', ms=5.6, color=BLUE,
                mec='white', mew=1.0, zorder=5)
        ax.axhline(100, color=MUTE, lw=0.9, ls=(0, (5, 3)), zorder=3)
        cv = d['conv']
        ax.set_title(ttl)
        ax.set_xlabel('rep  i'); ax.set_xticks(r[::2])
        ax.set_ylabel('white-line area  xᵢ   (% of mean)')
        col = RED if cv['verdict'] == 'drifting' else GREEN
        txt = (f'τ = {cv["trend_tau"]:+.2f}    p = {cv["trend_p_value"]:.3f}\n'
               f'Theil–Sen slope  {cv["trend_slope_frac_per_rep"]*100:+.2f} %/rep\n'
               f'total excursion  {cv["trend_total_frac"]*100:.2f} %').replace('-', '\u2212')
        ax.annotate(txt, (0.035, 0.045), xycoords='axes fraction', fontsize=8,
                    color=INK, va='bottom', linespacing=1.55,
                    bbox=dict(boxstyle='round,pad=0.45', fc='white', ec=col, lw=1.0))
        ax.annotate(cv['verdict'], (0.965, 0.93), xycoords='axes fraction',
                    fontsize=8.5, color=col, ha='right', va='top', fontweight='bold')
        ax.set_ylim(93.4, 106.6)
    save(fig, 'fig8-trend')


# ---------------------------------------------------------------- fig 9
def fig_trap():
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.0),
                             gridspec_kw={'width_ratios': [1.15, 1], 'wspace': 0.28})
    yt = [0.05, 0.1, 0.2, 0.5, 1.0, 2.0]

    def prep(ax):
        style(ax, grid='both')
        ax.set_yscale('log')
        ax.yaxis.set_major_locator(FixedLocator(yt))
        ax.yaxis.set_major_formatter(FixedFormatter([f'{v:g}' for v in yt]))
        ax.minorticks_off()
        ax.set_ylim(0.033, 2.6)
        ax.set_xlim(1.6, 12.6)
        ax.set_xticks(range(2, 13, 2))
        ax.set_xlabel('reps  n')
        ax.axhline(1.0, color=RED, lw=1.2, ls=(0, (1.6, 2.4)), zorder=4)

    def curve(ax, d, col, mk, lab):
        cv = d['conv']
        r = np.arange(1, cv['n'] + 1)
        y = np.array([np.nan if v in (None, 0.0) else v * 100
                      for v in cv['running_sem_frac']])
        ax.plot(r, y, lw=1.8, color=col, marker=mk, ms=4.4, mfc='white', mew=1.2,
                zorder=5, label=lab)
        return r, y

    ax = prep(axes[0]) or axes[0]
    ra, ya = curve(ax, A, BLUE, 'o', 'series A — stationary')
    rc, yc = curve(ax, C, ORANGE, 's', 'series C — photoreduction')
    ax.set_ylabel('running SEM of xₙ   (% of running mean)')
    ax.set_title('a — precision alone cannot separate them')
    ax.annotate('1 % target', (12.4, 1.10), fontsize=8, color=RED, ha='right',
                va='bottom')
    ax.annotate('A — stationary', (ra[-1], ya[-1] * 0.76), fontsize=8.2,
                color=BLUE, va='top', ha='right', fontweight='bold')
    ax.annotate('C — photoreduced', (rc[-1], yc[-1] * 1.28), fontsize=8.2,
                color=ORANGE, va='bottom', ha='right', fontweight='bold')
    worst = np.nanmax(np.r_[ya[1:], yc[1:]])
    ax.annotate(f'neither comes within {1.0 / worst:.0f}× of the target\n'
                f'at any rep count',
                (1.85, 0.62), fontsize=8.2, color=MUTE, va='center',
                ha='left', linespacing=1.45)

    ax = prep(axes[1]) or axes[1]
    r, y = curve(ax, D, VIOLET, '^', 'series D')
    tail = y[-max(2, y.size // 3):]
    lo = np.nanmin(tail)
    ax.axhline(lo * 1.25, color=ORANGE, lw=1.1, ls=(0, (2, 2.5)), zorder=3)
    ax.annotate('1.25 × the tail minimum', (1.75, lo * 1.25 * 0.90), fontsize=7.8,
                color=ORANGE, ha='left', va='top')
    ax.set_ylabel('running SEM of xₙ   (%)')
    ax.set_title('b — the rising-SEM veto')
    ax.annotate('sem_is_rising = true', (12.4, 0.068), fontsize=8.2, color=VIOLET,
                ha='right', va='bottom', fontweight='bold')
    ax.annotate('spot disturbed\nat rep 10', (10.0, 0.78), fontsize=8.2, color=MUTE,
                ha='center', va='center', linespacing=1.45)
    ax.annotate('', xy=(10.0, y[9] * 1.30), xytext=(10.0, 0.56),
                arrowprops=dict(arrowstyle='->', color=MUTE, lw=0.9))
    save(fig, 'fig9-trap')


# ---------------------------------------------------------------- fig 10
def fig_projection():
    fig, ax = plt.subplots(figsize=(7.1, 3.0))
    style(ax, grid='both')
    eff = A['eff']
    sem = np.array([np.nan if v is None else v for v in eff['cumulative_sem_pct']])
    ns = np.arange(1, sem.size + 1)
    n0 = 5
    k = sem[n0 - 1] * np.sqrt(n0)
    xs = np.linspace(n0, 13, 200)
    ax.plot(xs, k / np.sqrt(xs), lw=1.4, color=ORANGE, ls=(0, (4, 3)), zorder=4,
            label=f'projection from rep {n0}:  SEM ∝ 1/√n')
    ax.plot(ns[:n0], sem[:n0], lw=1.9, color=BLUE, marker='o', ms=4.6, mfc='white',
            mew=1.3, zorder=6, label=f'measured, reps 1–{n0} (known at decision time)')
    ax.plot(ns[n0 - 1:], sem[n0 - 1:], lw=1.4, color='#9ec5f4', marker='o', ms=4.0,
            mfc='white', mew=1.1, zorder=5, label='measured, reps collected afterwards')
    ax.axhline(A['target'], color=RED, lw=1.2, ls=(0, (1.6, 2.4)), zorder=3)
    pred = int(np.ceil(n0 * (sem[n0 - 1] / A['target']) ** 2))
    ax.axvline(pred, color=ORANGE, lw=1.0, ls=(0, (3, 3)), zorder=2)
    ax.plot([eff['target_reached_at_rep']], [sem[eff['target_reached_at_rep'] - 1]],
            marker='o', ms=9, mfc='none', mec=RED, mew=1.7, zorder=7)
    ax.set_xlim(1.4, 13); ax.set_ylim(0.72, 3.0)
    ax.set_xticks(range(2, 14))
    ax.set_xlabel('reps merged  n'); ax.set_ylabel('SEM  (% of signal)')
    ax.set_title('projecting the cost of finishing')
    ax.annotate(f'target {A["target"]:.0f} %', (12.9, A['target'] * 1.05), fontsize=8,
                color=RED, ha='right', va='bottom')
    ax.annotate(f'projected at rep {n0}:\n'
                f'n = {n0} × ({sem[n0 - 1]:.2f} / {A["target"]:.2f})² = {pred} reps',
                (6.2, 2.10), fontsize=8.2, color=INK, ha='left', va='top',
                linespacing=1.45, bbox=BOX)
    ax.annotate(f'actually met at rep {eff["target_reached_at_rep"]}',
                (eff['target_reached_at_rep'] - 0.25, 1.42), fontsize=8.2, color=RED,
                ha='right', va='bottom')
    ax.legend(loc='upper right', handlelength=1.9, borderaxespad=0.4)
    save(fig, 'fig10-projection')


FIGS = (fig_reps, fig_window, fig_merge, fig_perpoint, fig_c4, fig_floor,
        fig_trend, fig_trap, fig_projection)

if __name__ == '__main__':
    for f in FIGS:
        f()
