#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys

target = Path(__file__).resolve().parents[1] / "server" / "scripts" / Path(__file__).name
sys.argv[0] = str(target)
runpy.run_path(str(target), run_name="__main__")
