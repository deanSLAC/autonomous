---
name: user-reference
description: Quick reference guide for BL15-2 users — sample alignment, data collection, troubleshooting
---

# BL15-2 User Reference

Quick reference for users collecting data at BL15-2.

---

## Overview

Once the beamline is aligned, users take over for data collection. Your main tasks are:
1. Align your sample in the X-ray beam
2. Collect spectroscopy data using templates

---

## Sample Alignment

### Set photon energy above the edge 

1. Photon energy must be above the edge (300 eV or so) during sample alignment in order to get fluorescence.
   ```spec
   umvr energy 300      # a move relative to the current position
   umv energy 7400      # an absolute move
   ```

### Sample Stage Motors

| Motor | Description | Command |
|-------|-------------|---------|
| `Sx` | Horizontal position | `umv Sx <position>` |
| `Sy` | Depth (in/out of beam) | `umv Sy <position>` |
| `Sz` | Vertical position | `umv Sz <position>` |

**Check current positions:**
```spec
wsamp    # Display all sample motor positions
```

### Finding Good Sample Positions

The X-ray beam is much smaller than most samples, so you can collect spectra at different positions on one sample. To find good spots:

1. **Scan across the sample** and monitor fluorescence counts:
   ```spec
   plotselect vortDT     # Select the vortDT counter (fluorescence intensity)
   dscan Sz -2 2 40 1    # Vertical scan, look at vortDT counts
   dscan Sx -2 2 40 1    # Horizontal scan
   ```

2. **Identify sample boundaries** and regions with good signal

3. **Move to chosen position:** (and enter coordinates in run_template accordingly)
   ```spec
   umv Sz <position>
   umv Sx <position>
   ```

---

## Data Collection

### Using the Run Template

Data collection at BL15-2 uses a template macro that automates scanning across multiple samples. You fill out the template with your experimental parameters, and the macro handles the rest.

**Workflow:**
1. Beamline staff will provide a copy of the run template
2. Fill in your sample and scan parameters (see below)
3. Run the template: `load run_template.mac`
4. The macro cycles through your samples automatically

### How It Works

The template automatically:
- Moves to each enabled sample position
- Moves to fresh spots on the sample (if `change_spot = 1`) to avoid beam damage
- Runs the specified number of XAS/XES scans
- Tracks how many spots remain on each sample
- Continues to the next sample when spots are exhausted

### File Naming

Each sample section in the template includes a `newfile` command:

```spec
newfile sample_1
```

**Naming convention:** Be descriptive! Include:
- Sample composition
- In situ/operando conditions (if applicable)
- Environmental parameters

Example: `newfile Fe2O3_500C_H2_5percent_operando`

### Filters (Beam Attenuation)

If your sample is sensitive to beam damage, use filters to reduce intensity:

```spec
mv filter <value>    # 0-255 bitmask for 8 filters
```

**Important:** When changing filters, you typically need to adjust the I0/I1 amplifier gain and offset settings to maintain good signal levels.

---

## Useful Commands

### Position Display
| Command | Shows |
|---------|-------|
| `wsamp` | Sample motor positions |
| `wm Sx Sy Sz` | Sample motor positions |

### Basic Motor Movement
| Command | Description |
|---------|-------------|
| `umv motor position` | Move motor (shows progress) |
| `umvr motor distance` | Relative move |
| `mv motor position` | Move motor (silent) |

### Simple Scans
| Command | Description |
|---------|-------------|
| `dscan motor start end npts time` | Relative scan around current position |
| `ascan motor start end npts time` | Absolute position scan |

### After a Scan
| Command | Description |
|---------|-------------|
| `cen` | Move motor to center of feature |
| `peak` | Move motor to peak of feature |

---

## Primary Detectors

| Name | Description |
|------|-------------|
| `I0` | Incident beam intensity (before sample) |
| `I1` | Transmitted beam intensity (downstream of sample) |
| `vortDT` | Vortex fluorescence detector (main signal for HERFD) |

---

## Quick Troubleshooting

**Low counts / no signal:**
- Verify beam is on (SPEAR has beam; BL15 is open; hutch stoppers are open; signal on i2 or i0?; shutter is open? fson)
- Energy is above the edge? (if during sample alignment)
- sample position? 'wm Sx Sy Sz'

**Sample damage:**
- Increase filter value
- Move to fresh sample position
