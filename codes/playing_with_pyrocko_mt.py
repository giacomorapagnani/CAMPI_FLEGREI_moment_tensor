#!/usr/local/bin/python
#
#     DECOMPOSE-DC-COLLAPSE.PY
#
#     Copyright 2014 Simone Cesca
#
#     Developed by:
#     Simone Cesca
#     GFZ Potsdam, GFZ Potsdam
#     simone.cesca@gfz-potsdam.de
#  
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#  
#         http://www.apache.org/licenses/LICENSE-2.0
#  
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
# 


# Naming conventions
#   i* for counters
#   j* also for counters
#   k* also for counters
#   n* for quantities
#   f* for file names
#   d* for directory names


import sys
import re
import math
import numpy as num
from pyrocko import moment_tensor, orthodrome


def strDecim(num,decim):
   i=1
   for j in range(decim):
     i=i*10
   str_decim=str(float(round(float(num)*i))/float(i))
   return str_decim

 
# MAIN


#try:
#    mxx,myy,mzz = float(sys.argv[1]),float(sys.argv[2]),float(sys.argv[3])
#    mxy,mxz,myz = float(sys.argv[4]),float(sys.argv[5]),float(sys.argv[6])
#except:
#   print "Correct usage: python decompose-dc-collapse.py mxx myy mzz mxy mxz myz"
#   sys.exit("ERROR: Wrong input file name")

#older ones
#mxx,myy,mzz = 1.83e16,1.89e16,-0.978e16
#mxy,mxz,myz = -0.555e16,0.673e16,-0.141e16
#mxx,myy,mzz = 2.88e16,3.86e16,-1.81e16
#mxy,mxz,myz = -1.66e16,0.105e16,-0.23e16
# North Korea 6.1.2016 paper R2 - empirical restituted
#mxx,myy,mzz = 1.046e16,1.070e16,2.072e16
#mxy,mxz,myz = -8.162e14,1.088e16,5.712e15
# North Korea 9.9.2016 paper R2 - empirical restituted
#mxx,myy,mzz = 1.364e16,1.544e16,2.500e16
#mxy,mxz,myz = -9.255e14,-8.757e15,-7.157e15
#mxx,myy,mzz = 1.508e16,1.682e16,2.998e16
#mxy,mxz,myz = -9.215e14,-8.312e15,-7.756e15
# North Korea 3.9.2017
mxx,myy,mzz =  0.615e+18/36.,0.610e+18/36.,-0.382e+18/36.
mxy,mxz,myz =  -0.195e+18/36.,-0.231e+17/36.,0.119e18/36.

mt6 = moment_tensor.symmat6(mxx,myy,mzz,mxy,mxz,myz)
mt  = moment_tensor.MomentTensor(mt6) 
m0=mt.scalar_moment()
mw=mt.moment_magnitude()
decomposition=mt.standard_decomposition()
(moment_iso, ratio_iso, m_iso)=decomposition[0]
(moment_dc, ratio_dc, m_dc)=decomposition[1]
(moment_clvd, ratio_clvd, m_clvd)=decomposition[2]
(moment_devi, ratio_devi, m_devi)=decomposition[3]
moment, m=decomposition[4][0],decomposition[4][2]
mtiso=moment_tensor.MomentTensor(m_iso)

#print 'scalar moment',m0
#print 'magnitude',mw
#print mt.str_fault_planes()
print ('iso-dc-clvd',strDecim(ratio_iso*100.,1),strDecim(ratio_dc*100.,1),strDecim(ratio_clvd*100.,1),'total:',ratio_iso+ratio_dc+ratio_clvd,
       '\ndevi:',ratio_devi,'\nnon DC pecentage=',1-ratio_dc)

print ('\n---\nmt')
print (mt)
print (mt.moment_magnitude())

print ('\n---\nmtiso')
print (mtiso)
print (mtiso.moment_magnitude())

print ('\n---\nmtclvd')
mtclvd=moment_tensor.MomentTensor(m_clvd) 
mw=mtclvd.moment_magnitude()
print (moment_clvd, ratio_clvd, m_clvd)
print (mw)

print ('\n---\nmdc')
mtdc=moment_tensor.MomentTensor(m_dc) 
mw=mtdc.moment_magnitude()
print (moment_dc, ratio_dc, m_dc)
print (mw)