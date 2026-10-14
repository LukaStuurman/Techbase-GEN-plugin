"""Create the persistent QGIS project/layout in an isolated QGIS process."""

from __future__ import annotations

import os
import sys
import faulthandler
from pathlib import Path


def main(output_directory: str, geopackage: str) -> int:
    diagnostic_log = (Path(output_directory) / "qgis_project_worker.log").open("a", encoding="utf-8")
    diagnostic_log.write("QGIS-projectproces gestart\n")
    diagnostic_log.flush()
    faulthandler.enable(file=diagnostic_log, all_threads=True)
    library_directory = Path(__file__).resolve().parent
    sys.path.insert(0, str(library_directory))
    import maak_clustering_engine as engine

    os.environ["LS_QGIS_PROJECT_WORKER"] = "1"
    engine.OUT = Path(output_directory).resolve()
    result = engine.make_qgis_project(Path(geopackage).resolve())
    if result is None or not Path(result).exists():
        diagnostic_log.write("Projectopbouw niet voltooid; zie qgis_project_creation.log voor de procesuitvoer.\n")
        diagnostic_log.flush()
        return 1
    print(f"QGIS-project geschreven: {result}", flush=True)
    print(
        f"QGIS-layouttemplate geschreven: {engine.OUT / 'clustering_overzicht.qpt'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    exit_code = main(sys.argv[1], sys.argv[2])
    sys.stdout.flush()
    sys.stderr.flush()
    # Avoid known QGIS/Qt shutdown crashes after layout serialization. All
    # output files are closed and verified before this short-lived process ends.
    os._exit(exit_code)
