srun -u --nodes=1  --ntasks=15 --mem=128G --cpus-per-task=2 --pty --reservation=GPU --gres=gpu:1 grond go CONFIG/flegrei.devi.M.final.gronf all --parallel=15 --force
srun -u --nodes=1  --ntasks=15 --mem=128G --cpus-per-task=2 --pty --reservation=GPU --gres=gpu:1 grond report runs/cmt_devi_M_final_flegrei* --parallel=15
