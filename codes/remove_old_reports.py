import os
import subprocess

basedir = '../report'
#basedir = '../../old_report_&_runs/report'

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
            elif 'cmt_devi_near_05_2_far_005_01_td_fd_flegrei' in evn: #15
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_near_05_2_far_005_01_td_RTZ_flegrei' in evn: #16
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_near_05_2_far_005_01_tdflegrei' in evn: #17
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_near_05_2_far_005_02_td_fd_flegrei' in evn: #18
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_near_05_2_far_005_02_td_flegrei' in evn: #19
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_near_05_2_far_008_03_td_fd_flegrei' in evn: #20
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_XL_flegrei' in evn: #21
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_XL_only_td_flegrei' in evn: #22
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_XL_v2_flegrei' in evn: #23
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_L_flegrei' in evn: #24
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
            elif 'cmt_devi_XL_final_lowf_' in evn: #25
                invdir =  os.path.join(catdir,evn)
                subprocess.call( ["rm", "-rf",invdir] )
#            elif 'cmt_dc_' in evn: #26          ELIMINATE ALL DC REPORTS
#                invdir =  os.path.join(catdir,evn)
#                subprocess.call( ["rm", "-rf",invdir] )
#            elif 'cmt_full_' in evn: #27          ELIMINATE ALL FULL REPORTS
#                invdir =  os.path.join(catdir,evn)
#                subprocess.call( ["rm", "-rf",invdir] )
#            elif 'cmt_devi_' in evn: #28          ELIMINATE ALL DEVI REPORTS
#                invdir =  os.path.join(catdir,evn)
#                subprocess.call( ["rm", "-rf",invdir] )