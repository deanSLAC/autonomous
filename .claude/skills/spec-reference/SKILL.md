---
name: spec-reference
description: SPEC protocol reference for BL15-2 — motors, scans, detectors, macros, data file format
---

# BL15-2 User Operations Reference

## Beamline Overview

BL15-2 is a hard X-ray spectroscopy beamline at SSRL producing tunable X-rays in the energy range **4950 - 25000 eV**.

**SPEC** is the beamline control software.

---

## Key Motors

| Motor | Description |
|-------|-------------|
| `energy` | Beam energy (eV) — coordinates undulator gap and crystal angle |
| `emiss` | Emission energy (eV) — drives the XES analyzer system |
| `Sx`, `Sy`, `Sz`, `Sr` | Sample stage (horizontal, depth, vertical, rotation) |
| `filter` | Attenuator bitmask (0-255) for 8 filters |

### Moving Motors
| Command | Description |
|---------|-------------|
| `umv motor position` | Move motor with position updates |
| `umvr motor distance` | Relative move with position updates |
| `mv motor position` | Move motor (silent) |

### Checking Positions
```spec
wsamp           # Sample motors (Sx, Sy, Sz, Sr)
wm Sx Sy Sz     # Specific motor positions
```

---

## Scan Types

### Standard Scans
| Command | Description |
|---------|-------------|
| `dscan motor start end npts time` | Relative scan around current position |
| `ascan motor start end npts time` | Absolute position scan |

### Variable Step Scan
```
gscan motor start end1 step1 [end2 step2] ... sec
```
Example: `gscan mono 6540 6542 1 6550 0.2 6570 1 6770 1.0 6820 2 7100 5 1`

### EXAFS k-space Scan
```
kscan_energy start step1 sec1 end1 ... E0 k1 kstep k2 ksec1 ksec2 kweight
```

Note: Users typically interact with scans via the **run template** macro rather than running these commands directly.

### After a Scan
| Command | Description |
|---------|-------------|
| `cen` | Move motor to center of feature |
| `peak` | Move motor to peak of feature |
| `plotselect counter` | Select which counter to plot |

### Counter Access
```spec
S[I0]   # Incident intensity
S[I1]   # Transmitted intensity
S[sec]  # Collection time
```

---

## Detectors & Counters

| Detector | Description |
|----------|-------------|
| **I0** | Incident beam intensity (ion chamber upstream of sample) |
| **I1** | Transmitted beam intensity (ion chamber downstream of sample) |
| **I2** | Second transmitted beam detector |
| **vortDT** | Vortex fluorescence detector (main signal for HERFD) |
| **vortDT2** | Second Vortex channel |
| **cryoct** | Cryostat temperature (K) |

### Vortex Detector
```spec
vortex_roi <ch> <min> <max>     # Set ROI (ch 1 or 3)
vortex_roi auto [1|3]           # Auto ROI +/-200eV around emiss
vortex enable|disable           # Toggle detector
```

### Cryostat Temperature
```spec
cryo                    # Print temperature (K)
cryo enable|disable     # Toggle counter
```

---

## Filters (Beam Attenuation)

```spec
filter                  # Motor (0-255 bitmask for 8 filters)
safely_remove_filters   # Remove filters with safety check
```

When changing filters, you typically need to adjust the I0/I1 amplifier gain and offset settings to maintain good signal levels.

---

## Energy Control

### Photon Energy
```spec
umv energy 7400         # Move to absolute energy (eV)
umvr energy 300         # Relative energy move
```

### Harmonic Selection
```spec
set_harmonic 3|5|7|9|11|13|auto   # Select harmonic
get_harmonic [eV]                  # Show which harmonic would be used
show_harmonics                     # Print energy ranges
```

Harmonic ranges:
- 3rd: 4597–7682 eV
- 5th: 7683–10761 eV
- Higher harmonics for higher energies

---

## XAS Macros

Element-specific macros define energy scan routines. Common elements: Cu, Fe, Co, Se, As — each with variants like `_pre`, `_Ka`, `_exafs`, etc.

---

## Cherfd Integration

Cherfd is a continuous energy scanning data acquisition system (continuous HERFD). This is a special mode that is not always relevant — ask staff if you need to use it.

### SPEC Commands
| Macro | Description |
|-------|-------------|
| `cherfd_start` | Initiate continuous scan |
| `cherfd_wait` | Block until scan completes |
| `cherfd_status` | Query current scan state (0/1) |
| `do_cherfd start_eV stop_eV sweeps file_root` | Top-level wrapper |

---

## Time-Resolved Experiments

These modes are used in specialized sessions and are not always available. Consult staff before using.

### Pump-Probe (ADQ14 fast ADC)
```spec
pp enable|disable                       # Toggle pump-probe systems
adq enable|disable|start|end|kill|raw   # ADQ control
```
Counters: `ppbon`, `ppboff`, `ppbdiff`

### Delay Line
```spec
pdlmot                          # Motor (picoseconds)
pdl enable|disable|del [num] ps|ns
```

### Modulation
```spec
modulation enable|disable|print     # Toggle/show modulation
spectrogram <npts> <time>           # Run spectrogram
```
Counters: `modfft`, `modmod`, `moddif`

---

## Data Files

### SPEC Data File Structure
```
#F <filename>           # File path
#E <epoch_seconds>      # Unix timestamp
#D <date_string>        # Human-readable date
#S 1  scan_command      # Scan number + command
#T 1  (Seconds)         # Counting mode
#P0 pos1 pos2...        # Motor positions at scan start
#N <num_columns>        # Number of data columns
#L col1  col2  col3...  # Column labels
<data rows>             # Space-separated values
```

---

## Beam Monitoring

```spec
check_beam_on|off       # Toggle auto-pause on beam loss
```
Checks: SPEAR current >200mA, BL15 open, gap ownership.
