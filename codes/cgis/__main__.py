'''
cgis - interactive viewer for catalogues, focal mechanisms and stations.

Usage (from the ``codes`` folder)::

    python3 cgis                      # empty window, add data from the GUI
    python3 cgis -res                 # resume the last (autosaved) session
    python3 cgis -res my_session      # resume cgis/sessions/my_session.yaml
    python3 cgis -c ../CAT/catalogue_flegrei_MT_final.pf \\
                 -s ../META_DATA/stations_flegrei_INGV_final.xml
    python3 cgis --browser            # use the web browser instead of the
                                      # Qt window
'''

import os
import sys

# Running ``python3 cgis`` puts the cgis folder itself on sys.path: add its
# parent so that the package can be imported by name.
_here = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_here)
# the package folder itself must not be on the path (its module names,
# e.g. session or paths, could shadow other modules)
sys.path = [p for p in sys.path
            if os.path.abspath(p or os.curdir) != _here]
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from cgis.app import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
