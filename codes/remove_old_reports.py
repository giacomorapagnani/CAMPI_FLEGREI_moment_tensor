import os
import subprocess

basedir = '/home/giaco/WORKS/FLEGREI_moment_tensor_work/GROND_inversion/report' #remote
#basedir = '/Users/giaco/UNI/PhD_CODE/WORKS/FLEGREI_moment_tensor_work/GROND_inversion/report' #local

for fn in os.listdir(basedir):

    if 'flegrei_' in fn:
        catdir =  os.path.join(basedir,fn)

    for evn in os.listdir(catdir):

        if 'cmt_devi_vrs1_flegrei' in evn: #1
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs2_flegrei' in evn: #2
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs3_flegrei' in evn: #3
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs4_flegrei' in evn: #4
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs5_flegrei' in evn: #5
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs6_flegrei' in evn: #6
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_full_vrs6_flegrei' in evn: #7
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_full_vrs4_flegrei' in evn: #8
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_full_vrs5_flegrei' in evn: #9
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs_small_eq_far_flegrei' in evn: #10
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs_far_only_eq_flegrei' in evn: #11
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs_big_eq_URG' in evn: #12
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs_small_eq_URG' in evn: #13
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )
        elif 'cmt_devi_vrs_mid_eq_URG' in evn: #14
            invdir =  os.path.join(catdir,evn)
            subprocess.call( ["rm", "-rf",invdir] )