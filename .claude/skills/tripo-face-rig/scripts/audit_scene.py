"""Compatibility entry point; maintained implementation is in scripts/face_pipeline."""
from pathlib import Path
import runpy
import sys

script = Path(__file__).resolve().parents[4] / "scripts" / "face_pipeline" / Path(__file__).name
sys.path.insert(0, str(script.parent))
runpy.run_path(str(script), run_name="__main__")
