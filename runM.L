srun -u --nodes=1  --ntasks=1 --mem=512G --cpus-per-task=10 --time=2880 grond go CONFIG/flegrei.devi.M.final.gronf all --parallel=10 --force
srun -u --nodes=1  --ntasks=1 --mem=512G --cpus-per-task=10 --time=2880 grond report runs/cmt_devi_M_final_flegrei* --parallel=10
