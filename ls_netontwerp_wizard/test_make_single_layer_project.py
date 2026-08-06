"""Rebuild a QGIS project from an existing clustering GeoPackage."""

from __future__ import annotations

import os
import sys
from pathlib import Path


library = Path(__file__).resolve().parent / "algorithms" / "laagspanning_clustering_lib"
sys.path.insert(0, str(library))
import maak_clustering_engine as engine


source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
target.mkdir(parents=True, exist_ok=True)
target_gpkg = target / "clustering_ontwerp.gpkg"
if source != target_gpkg:
    import shutil

    shutil.copy2(source, target_gpkg)
    source_overview = source.with_name("cluster_overzicht.csv")
    if source_overview.exists():
        shutil.copy2(source_overview, target / "cluster_overzicht.csv")
engine.OUT = target
os.environ["LS_QGIS_PROJECT_WORKER"] = "1"
engine.make_qgis_project(target_gpkg)
