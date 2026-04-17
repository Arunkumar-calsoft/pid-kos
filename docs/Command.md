python scripts/register_pid.py --plant-id PLANT_001 --plant-name "Energy Impact Center" --skid-id SKID_01 --skid-type CONDENSATE --pid-id PID_0 --graphml PLANT_001/SKID_01/PID_0/0.graphml --image PLANT_001/SKID_01/PID_0/0.png --rev A --date 2020-09-01


python scripts/register_pid.py --plant-id PLANT_001 --plant-name "Energy Impact Center" --skid-id SKID_01 --skid-type CONDENSATE --pid-id PID_2 --graphml PLANT_001/SKID_01/PID_2/2.graphml --image PLANT_001/SKID_01/PID_2/2.png --rev A --date 2020-09-01




python scripts/run_phase0.py --pid PID_0
python scripts/run_phase0.py --pid PID_2 
