srun -u --nodes=1  --ntasks=29 --mem=128G --cpus-per-task=1 --pty --reservation=GPU --gres=gpu:1 grond go CONFIG/flegrei.devi.M.final.gronf all --parallel=29 --force
srun -u --nodes=1  --ntasks=29 --mem=128G --cpus-per-task=1 --pty --reservation=GPU --gres=gpu:1 grond report runs/cmt_devi_M_final_flegrei* --parallel=29
