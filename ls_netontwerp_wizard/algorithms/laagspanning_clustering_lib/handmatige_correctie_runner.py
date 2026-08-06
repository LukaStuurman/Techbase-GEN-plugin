"""Short-lived worker for the manual QGIS cluster correction tool.

The network calculation imports GeoPandas, SciPy and a large NetworkX graph.
Running that work in the persistent QGIS Desktop process retains a substantial
amount of native memory between runs.  This worker deliberately exits after one
calculation so repeated manual corrections remain stable.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def main(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    library_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(library_dir))

    import maak_clustering_engine as engine

    engine.log = lambda message: print(str(message), flush=True)
    print("Invoerlagen in de rekenomgeving lezen...", flush=True)
    inputs = {
        name: engine.gpd.read_file(spec["path"], layer=spec["layer"])
        for name, spec in config["inputs"].items()
    }

    backup_path = Path(config["backup_path"])
    result_path = Path(config["result_path"])
    engine.write_manual_cluster_snapshot(
        backup_path,
        inputs["aansluitingen"],
        inputs["stations"],
        inputs["gebieden"],
        inputs["routes"],
        inputs["sleuven"],
        inputs.get("plangebied"),
    )
    print(f"Back-up geschreven: {backup_path}", flush=True)

    legacy_safety_value = bool(config.get("safety_checks_enabled", True))
    result = engine.recalculate_manual_assignment(
        inputs["aansluitingen"],
        inputs["stations"],
        inputs["gebieden"],
        inputs["routes"],
        inputs["sleuven"],
        selected_source_fids={int(value) for value in config["selected_source_fids"]},
        target_station_source_fid=int(config["target_station_source_fid"]),
        remove_source_clusters=bool(config.get("remove_source_clusters", False)),
        force_assignment=bool(config.get("allow_all", False)),
        max_route_m=float(config["max_route_m"]),
        node_tolerance_m=float(config["node_tolerance_m"]),
        plan_layer=inputs.get("plangebied"),
        check_station_capacity=bool(
            config.get("check_station_capacity", legacy_safety_value)
        ),
        check_max_route=bool(config.get("check_max_route", legacy_safety_value)),
        block_other_cluster_routes=bool(
            config.get("block_other_cluster_routes", legacy_safety_value)
        ),
        check_shared_routes_and_branches=bool(
            config.get("check_shared_routes_and_branches", legacy_safety_value)
        ),
        refresh_all_routes=bool(config.get("refresh_all_routes", False)),
        refresh_cluster_names={
            str(name).strip()
            for name in config.get("refresh_cluster_names", [])
            if str(name).strip()
        },
    )
    (
        connections,
        stations,
        areas,
        routes,
        cables,
        summary,
    ) = result
    print("Resultaat en back-up naar GeoPackage schrijven...", flush=True)
    engine.write_manual_cluster_snapshot(
        result_path,
        connections,
        stations,
        areas,
        routes,
        cables,
        inputs.get("plangebied"),
    )
    Path(config["summary_path"]).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Resultaatkopie geschreven: {result_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1]))
    except Exception as exc:
        print(f"FOUT: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
