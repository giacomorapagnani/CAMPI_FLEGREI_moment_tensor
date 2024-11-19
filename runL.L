srun -u --nodes=1  --ntasks=1 --mem=512G --cpus-per-task=9 --time=2880 grond go CONFIG/flegrei.devi.L.final.gronf all --parallel=9 --force
srun -u --nodes=1  --ntasks=1 --mem=512G --cpus-per-task=9 --time=2880 grond report runs/cmt_devi_L_final_flegrei* --parallel=9
