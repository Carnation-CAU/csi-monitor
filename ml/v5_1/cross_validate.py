"""v5.1 entry point; shared CNN implementation remains in v5."""
from __future__ import annotations
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0,str(PROJECT))
from ml.v5.cross_validate import main

if __name__=="__main__":
    sys.argv[1:1]=["--output",str(HERE/"output"/"cross_validation"),"--results-file",str(HERE/"RESULTS.md")]
    main()

