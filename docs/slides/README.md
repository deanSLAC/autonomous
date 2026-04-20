# Slide deck

Presentation deck that explains the autonomous-beamline-agent project.
Open `index.html` in a browser to view.

## Why these live in the repo

The deck is committed alongside the code so that *what we say about the
project* and *what the project actually does* stay version-controlled
together. When the system gains a new capability, the slides change in
the same commit (or at least the same PR) so a checkout at any point in
history shows a coherent snapshot of "code + story".

## Source

Synced (with relative-path adjustments) from:

```
../design_handoff_autonomous_beamline_agent/ssrl-beamline-design-system/project/
├── slides/index.html
├── slides/deck-stage.js
├── colors_and_type.css
└── assets/
```

If the upstream design system is updated, re-pull and copy the changed
files into this directory. The only edit needed is in `index.html`:
asset references should be `assets/...` and `colors_and_type.css`
(local), not `../assets/...` and `../colors_and_type.css` (the
upstream layout that puts assets one level up).
