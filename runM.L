srun -u --nodes=1  --ntasks=1 --mem=64G --cpus-per-task=29 --pty --reservation=GPU --gres=gpu:1 grond go CONFIG/flegrei.devi.M.final.gronf all --parallel=29 --force
srun -u --nodes=1  --ntasks=1 --mem=64G --cpus-per-task=29 --pty --reservation=GPU --gres=gpu:1 grond report runs/cmt_devi_M_final_flegrei* --parallel=29
