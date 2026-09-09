# `stopping-decision.html` — figure generator

Sources for `../stopping-decision.html`. Every plotted number in that
document is the return value of the shipped implementation in
`beamtimehero_cli.science.statistics`; nothing here re-implements the maths.

| file | role |
| --- | --- |
| `simdata.py` | the simulated Fe K-edge rep stack: clean spectrum, count model, Poisson draw, and the normalisation the counting noise is propagated through |
| `series.py` | the four example series (A clean, B disturbed at rep 6, C photoreduced, D bumped at rep 10) and the real `analyze_scan_efficiency` / `analyze_scalar_convergence` output for each |
| `mkfigs.py` | renders `figs/*.svg` from those results |
| `body.html` | the prose, with `{{FIG1}}`…`{{FIG10}}` placeholders |
| `build.py` | CSS + `body.html` + `figs/*.svg` → `../stopping-decision.html` |

## Rebuild

```bash
cd docs/stopping-decision
../../venv/bin/python mkfigs.py     # regenerate figs/*.svg
../../venv/bin/python build.py      # regenerate the document
```

Edit prose in `body.html`, not in the built HTML — `build.py` overwrites it.

`../stopping-decision.html` is checked in alongside these sources. Rerunning
`mkfigs.py` rewrites matplotlib's element ids and the timestamp it embeds in
each SVG, so expect a large diff even when no plotted number changed; run
`build.py` alone if the data has not moved.

## The count model

`simdata.make_stack` draws Poisson counts

    lam(E) = C * [ b + (1 - b) * mu(E) / EDGE_TOP ]

and then *inverts* that mapping to get the measured normalised spectrum, so the
counting noise reaches it through the background subtraction and the edge-step
division rather than being pasted onto the clean shape. That is what puts the
achieved SEM a few percent above the single-channel counting floor, exactly as
the propagation note in §5 of the document says it must: the bracket
`[1 + b(E)/(edge step * mu)]` is always at least 1. Series A therefore sits on
the floor from just above it, with a single rep count dipping below on
estimator scatter alone.
