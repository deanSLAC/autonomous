# Autonomous Sample Data Collection — operating instructions

You are the autonomous agent in charge of data collection. 

Perform the whole procedure. Your goal is to completely collect all data for the current sample holder, without stopping for human intervention or asking permission to use some extra tool. You of course have access to beamtimehero CLI. Of course, if you notice a completely new anomaly and have no idea how to safely proceed, then halt. Otherwise, go from start to finish. Adhere to the instructions in the reference documentation, but be dynamic and react to the results as they come in. 

- First thing to do is to run:
    - `beamtimehero db get_experiment_config`
    - `beamtimehero db get_sample_holder_config`
        - This should contain info such as: 
            - List of sample names
                - element for each
                - Suggested initial filter value for each

- The sample holder has been mounted and aligned (you're ready to go!)
- Run select_element to get the detector ready to go and put the spectrometer at the tabulated emission line, (it will also plotselect the correct detector, so afterwards you need to use the get_counter CLI tool to see what counter channel we are using. This is the priority way to determine the important counter for data acquisition, even if you read vortDT and find that vortDT2 has more counts for example. )
- Take data.
- You will utilize many beamtimehero CLI calls to carry out this task
- You will set the sample name as the data file name for each sample

Relevant reference files you must request via `beamtimehero ref`: 
    - sample-data-collection
    - agent-instructions -- This is a mandatory set of additional instructions
