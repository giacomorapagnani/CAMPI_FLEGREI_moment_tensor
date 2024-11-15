srun -u --nodes=1  --ntasks=7 --mem=64G --cpus-per-task=7 --pty --reservation=GPU --gres=gpu:1 grond go CONFIG/flegrei.devi.XL.final.gronf all --parallel=7 --force
srun -u --nodes=1  --ntasks=7 --mem=64G --cpus-per-task=7 --pty --reservation=GPU --gres=gpu:1 grond report runs/cmt_devi_XL_final_flegrei* --parallel=7
