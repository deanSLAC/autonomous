Sample Data Collection

Here is a guide for how to collect HERFD spectrum. It should be considered flexible, and left to your turn-by-turn judgement of how things look. 

However there are basic rules:
- We can only measure the designated element (eg "Au"). We cannot just decide to see how a Cu scan looks. Each element needs to be carefully set up in advance, and the spectrometer only holds crystals for that particular element, and even only for one emission line of that element (eg "Au L3M5"). 

For this sample collection phase of the experiment, we will move: 
    - The sample stages (Sx, Sy, Sz)
    - The incident beam energy
        - We may only make an energy move to go 200 eV above the edge for the active experiment plan, or run a eg Au_xas macro function which will perform the spectrum collection.
    - The emiss motor that controls the spectrometer emission
        - We will just be moving to the emiss value that was found during sample alignment. Make sure a value appears reasonable (within 10 eV of the tabulated emission line) before trying to move there.
    - filters
    - and we will control the shutter, maybe set some i0 gain

We WILL NOT move: 
    - any of the upstream optics (unless tracking is on and so moving energy moves mirror Tz)
    - no mono slits
    - no B stage (Bz or Bx)
    - no mirrors
    - no Tz/Tx

Before starting on sample_collection, we will already have run select_element, which will have: run xes_setup to configure the spectrometer crystals, mv emiss to the tabulated energy (then sample alignment will have found a measured value), and plotselected the appropriate counter (vortDT vs vortDT2, ...).

Before we proceed with these steps, we should have: 
- Aligned a sample holder, finding Sx, Sy, Sz low, Sz high, emiss, and number of filters for each of the samples

- Move to the top of a sample. Set the filters and emiss values to match what we found for this sample
- Check that we have some counts. If we have more than 50 kcps, add filters.


### Beam damage

The first thing we want to do is assess beam damage. We do this by running two spectra back-to-back and comparing them very closely (looking at vortDT/I0). If there are significant differences, we want to add filters until we cut the count rate in half, then try again, and so on, until there is very little difference between the consecutive scans. If however, on our first iteration there are no changes, and we have filters in, we can start removing filters. We want to stay below the absolute threshold of 200 kcps, otherwise we remove filters to double the countrate, then check again for beam damage.

How to find beam damage: Check the height of the white line relative to the post edge region. Look closely at a couple other features, including the pre-edge. Try to find any differences. 

### Spectra

The procedure for real data collection for a sample wil be something like: 
set the filename to reflect the name of the sample
Take <some number> of spectra on one spot
mvr 2 beam widths
take <the same number> of spectra on the new spot
continue until we run out of spots.

However, this should be considered very flexible.  Take into consideration the count rate, the progression of statistics (see section below), as well as the time each scan takes and how much time budget we have overall.  If the count rate is high, the first four spectra look amazing, we dont need to continue sampling for no reason. But to cover our bases, take at least 2 spectra on at least two spots for each sample.

In order to take a spectra, rely on the built in function specific to that element, eg Au_xas. The corresponding CLI tool will be called take HERFD

### Statistics

**Per agent-instructions §5, you must call `tool plot-scan` and write a one-sentence description of every scan before the next decision.** That is the mandatory per-scan baseline check, not optional advice.

Beyond that, beamtimehero CLI contains several tools to assist in analyzing the progression of the sample statistics across reps. Use them, but also keep visually inspecting the accumulating stack: plot all the spectra together each time a new spectrum is taken, look at the similarity between each consecutive scan (check for beam damage over time), and judge whether a scan looks anomalous and is recommended to be thrown out (via a note in spec). After each spectrum, look at the average of all scans taken, compare it to the previous average. Isolate the evolution of statistics for an individual feature within the spectrum. One flaw in some of the CLI tools is they look at some statistic applied to the whole spectrum altogether, and claim nothing is changing with successive scans anymore. But this can wash out the tiny details in small features that might still be resolving progressively. 