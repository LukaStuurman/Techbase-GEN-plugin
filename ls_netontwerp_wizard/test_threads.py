"""Lokale test voor de multithread-HiGHS-instellingen."""

import importlib.util
import os
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, milp


os.environ["LS_NETONTWERP_THREADS"] = "4"
path = (
    Path(__file__).resolve().parent
    / "algorithms"
    / "laagspanning_clustering_lib"
    / "maak_clustering_engine.py"
)
spec = importlib.util.spec_from_file_location("thread_test_engine", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.CPU_THREADS == 4
result = milp(
    c=np.asarray([1.0]),
    integrality=np.asarray([1], dtype=np.uint8),
    bounds=Bounds(np.asarray([1.0]), np.asarray([2.0])),
    options=module.milp_options(10, 0.01),
)
assert result.x is not None and round(float(result.x[0])) == 1
print("THREADING_HIGHS_TEST_OK")
