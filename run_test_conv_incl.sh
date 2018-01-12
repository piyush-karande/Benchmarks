#!/bin/bash
. ~/spack-activate.sh

cd /p/gscratchr/karande1/Benchmarks/Pilot2/P2B1/
DATE=`date +%m%d%Y_%H%M%S`
save_path="/p/gscratchr/karande1/Benchmarks/Pilot2/P2B1/molecular_AE_results/$DATE"
mkdir $save_path
mpirun -np 1 ipython -i p2b1_baseline_keras2_mol_AE.py -- --save-dir $save_path --case Full --conv-AE --include-type --config-file p2b1_default_model.txt

echo 'Done'
