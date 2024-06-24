import os
basedir = '/Users/giaco/UNI/GIT/seis/FLEGREI/WORK/DATA'
for fn in os.listdir(basedir):
  if not os.path.isdir(os.path.join(basedir, fn)):
    continue # Not a directory
  if 'flegrei_' in fn:
    continue # Already in the correct form
#  if ' ' not in fn:
#    continue # Invalid format
  firstname,_,surname = fn.rpartition(' ')
  os.rename(os.path.join(basedir, fn),
            os.path.join(basedir, 'flegrei_' + fn))