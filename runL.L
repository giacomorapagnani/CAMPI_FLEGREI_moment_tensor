srun -u --nodes=1  --ntasks=18 --mem=128G --cpus-per-task=1 --pty --reservation=GPU --gres=gpu:1 grond go CONFIG/flegrei.devi.L.final.gronf all --parallel=18 --force
srun -u --nodes=1  --ntasks=18 --mem=128G --cpus-per-task=1 --pty --reservation=GPU --gres=gpu:1 grond report runs/cmt_devi_L_final_flegrei* --parallel=18
