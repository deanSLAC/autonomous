Cryostat sample alignment

### Intro
After aligning the beamline, and aligning the spectrometer, we will be ready to put in the first sample. Our standard cryostat sample holder holds 4 sample aligned vertically. It is positioned at 45 degrees (rotated about the z axis) relative to the incident beam, so that it is open to the spectrometer acceptance (the beam spot on the sample can 'see' all the crystals in the spectrometer). We collect spectra on multiple spots on the sample, using a dedicated macro for the spectrum of the element in question.

For this sample alignment phase of the experiment, we will move: 
    - The sample stages (Sx, Sy, Sz)
    - The incident beam energy
    - The emiss motor that controls the spectrometer emission
    - filters
    - and we will control the shutter, maybe set some i0 gain

We WILL NOT move: 
    - any of the upstream optics (unless tracking is on and so moving energy moves mirror Tz)
    - no mono slits
    - no B stage (Bz or Bx)
    - no mirrors
    - no Tz/Tx 

We expect the sample to block the beam, and therefore we do not expect to get any use out of I1 during this process.

Before starting on sample alignment, we will already have run select_element, which will have: run xes_setup to configure the spectrometer crystals, mv emiss to the tabulated energy, and plotselected the appropriate counter (vortDT vs vortDT2, ...).

### Setup

To prepare the sample holder for data collection:
- Cryostat samples are generally sensitive to beam damage. Begin with the shutter closed, and in auto shutter mode, to reduce damage during alignment.
- collect alignment scans in the 'alignment' data file
- mv the energy above the edge of interest by 100 eV
- Move to the default cryostat starting position: Sx 0, Sy 0, Sz 25
- Do a large and coarse Sz scan to identify all the samples in the holder.
    - typical scan (starting from Sz 25): dscan Sz -10 20 60 .3
- Look at the result. Try to identify the position of the 4 samples
- Get a rough estimate of each sample's cps

### Alignment for one sample
- mv to the center of the top sample (lowest Sz val)
- Depending on count rate from the coarse scan, add filters if needed (As a starting point, if <8 keV put 4, above that put 10), then check the counts again.
- do a ct, look at the proper vortDTN counter, make sure we have something
- Now do fine position scans of the sample holder. Typical scans would be: 
    - dscan Sz -3 3 30 .3
        - Vertically check out the homogeneity and finer alignment of the sample. Note the boundaries of the sample counts, Sz low and Sz high.
    - dscan Sy -8 8 40 .3 
        - The y axis scans the sample in the beam direction, moving the sample through the focus of the spectrometer. We should see a wide, symmetric peak on the vortDTN counter.
    - d2scan Sx -8 8 Sy -8 8 40 .3 -- see beamtimehero CLI run_diagonal_scan
        - Sample is aligned at 45 degrees, so we scan 2 dimensions to align the sample in the beam
- Next we scan the emiss motor (assuming we have found at least 300 cps).  Typical scan: 'dscan emiss 8 -8 50 .
3' (emiss should be scanned in the negative direction due to motor backlash) but this can be adjusted as needed.
- Look at a plot of the emiss scan, does it look reasonable? If not, do some more sample scans (as described below), then repeat an emiss scan again later.
- Use the get herfd energy tool to mv emiss to the optimal position.

- Keep track of the per-sample values you'll need later in collection:
    1. Sx and Sy positions
    2. Sz boundaries. We will measure from multiple spots on one sample, moving vertically by 2 beam sizes between spots. Therefore we will want to know the start and end Sz values we could step between.
    3. The exact emiss value we aligned to, as this will be off the tabulated value by nature of our alignment.
    4. The number of filters we have used
- Check the count rate again.  If we have > 50 kcps, add filters. We want to begin with a relatively low count rate until we assess sample damage from the beam.

Repeat the steps for the other 3 samples.

Once those scans have been completed successfully, we are ready to move on to sample data collection, described in sample-data-collection.md
