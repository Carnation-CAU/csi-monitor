from __future__ import annotations
import sys
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path: sys.path.insert(0,str(PROJECT))
from ml.v5.check_environment import main
if __name__=="__main__": main()

