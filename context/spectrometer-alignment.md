Spectrometer alignment

- Run xes_setup to configure the crystal cut we are using in the spectrometerd
    - syntax: xes_setup <crystal element: 0 Si | 1 Ge> <h> <k> <l> <bend radius>
    - ex: xes_setup 1 5 5 5 1000  # Si 555 crystals with 1m bend radius

- mv emiss (the macromotor for emission energy of the spectrometer) to the theoretical emission line
    - ex: mv emiss 9713 # Au L3

- Set the vortex ROI for this emission line
    - vortex_roi auto

- We cannot expose the vortex detector to more than 200 kcps. Begin by protecting it by attenuating the incident beam
    - `mv filter 10` or if emiss < 8 keV `mv filter 5` should be sufficient

- Move the incident beam energy to the elastic peak
    - mv energy 9713

- Verify the initial count rate
    - plotselect vortDT
    - ct

- Scan the mono to align the incident beam energy to that of the spectrometer emission energy
    - dmm  # runs dscan mono -3 3 30 .2
    - look at the result. If no peak is evident at all, remove all filters and try again.
    - peak
    - The monochromator is calibrated with a metal foil, while the spectrometer is aligned by ruler. therefore they may disagree slightly on energy (the elastic peak position would not line up exactly). Our practice is to move the mono to where the elastic peak is, and leave emiss at the tabulated emission line. They should not differ by more than 3 eV

- Check count rate again, adjust filters as needed, so that vortDT is between 1 kcps and 30 kcps

- Run the crystal pitch/yaw alignment script
    - xes_align(1234567)  # sometimes we have multiple crystal sets installed, this is the default case of having all 7 crystals being the same cut. Otherwise you might do xes_align(135) for one setup, then start over with xes_setup, mv emiss, mv mono, dmm, etc and run a second xes_align(2467) for the other crystal cut.

- Part of the routine for xes_align, is to not only steer each crystal into the detector, but also to check the elastic peak of each crystal individually. When that script is finished, we then need to shift the crystals forward/backward to overlap their elastic peaks. This is done via relative moves of AxN. If crystal 7 has an elastic peak position that is lower than all the other crystals, we would mvr Ax7 -.5, then re-scan its elastic peak to measure whether it has overlapped successfully.
