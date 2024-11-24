import os
import subprocess


start_dir = '/Users/giaco/UNI/PhD_CODE/GIT/old_report_&_runs/report'
end_dir='/Users/giaco/UNI/PhD_CODE/GIT/CAMPI_FLEGREI_moment_tensor/report/report'

ev_list=[]
for fn in os.listdir(start_dir):

    if 'flegrei_' in fn:
        catdir =  os.path.join(start_dir,fn)

        for evn in os.listdir(catdir):

            if 'cmt_devi_S_flegrei' in evn: 
                invdir =  os.path.join(catdir,evn)
                subprocess.run(['cp', '-r', catdir, end_dir])
                ev_list.append(evn)

print(ev_list)
print(f'total events copied : {len(ev_list)}')