'''
csta - interactive editor for station catalogues (StationXML).

Usage (from the ``codes`` folder)::

    python3 csta                      # choose the files in the window
    python3 csta stations_flegrei_INGV_final.xml \\
                 stations_flegrei_INGV_simone.xml
                                      # names are looked up in META_DATA
    python3 csta --browser            # use the web browser instead of the
                                      # Qt window
'''

import os
import sys

# Running ``python3 csta`` puts the csta folder itself on sys.path: add its
# parent so that csta (and cgis, whose window and dialogs are reused) can be
# imported by name.
_here = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_here)
# the package folder itself must not be on the path (its module names,
# e.g. paths or state, could shadow other modules)
sys.path = [p for p in sys.path
            if os.path.abspath(p or os.curdir) != _here]
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from csta.app import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
