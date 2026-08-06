"""Isolated worker for adding and noding a drawn trench route."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def main(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    library_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(library_dir))

    # Keep drawing a trench lightweight: importing the full clustering engine
    # also initializes SciPy, Matplotlib and NetworkX although none are needed
    # for this local topology edit.
    import network_noding as engine

    engine.log = lambda message: print(str(message), flush=True)
    print("Sleuven en aansluitpunten in de rekenomgeving lezen...", flush=True)
    inputs = {
        name: engine.gpd.read_file(spec["path"], layer=spec["layer"])
        for name, spec in config["inputs"].items()
    }
    cables = inputs["sleuven"]
    new_routes = inputs["nieuwe_sleuf"]
    points = inputs["aansluitingen"]
    stations = inputs["stations"]
    if cables.empty or new_routes.empty:
        raise RuntimeError("De bestaande of nieuw getekende sleuvenlaag is leeg")
    if any(frame.crs is None for frame in (cables, new_routes, points, stations)):
        raise RuntimeError("Alle netwerklagen moeten een geldige CRS hebben")

    original_crs = cables.crs
    cables_rd = cables.to_crs(engine.CRS_RD).copy()
    new_rd = new_routes.to_crs(engine.CRS_RD).copy()
    points_rd = points.to_crs(engine.CRS_RD).copy()
    stations_rd = stations.to_crs(engine.CRS_RD).copy()
    plan = inputs.get("plangebied")
    if plan is not None and not plan.empty:
        plan_rd = plan.to_crs(engine.CRS_RD)
        boundary = engine.unary_union(
            plan_rd.loc[
                plan_rd.geometry.notna() & ~plan_rd.geometry.is_empty,
                "geometry",
            ].tolist()
        ).buffer(0)
        if boundary.is_empty:
            raise RuntimeError("Het plangebied is leeg of ongeldig")
        new_rd.geometry = new_rd.geometry.intersection(boundary)
        new_rd = new_rd.loc[
            new_rd.geometry.notna() & ~new_rd.geometry.is_empty
        ].copy()
        if new_rd.empty:
            raise RuntimeError("De nieuwe sleuf ligt volledig buiten het plangebied")

    backup_path = Path(config["backup_path"])
    result_path = Path(config["result_path"])
    backup_path.unlink(missing_ok=True)
    cables.to_file(backup_path, layer="sleuven_genood", driver="GPKG")
    print(f"Back-up van het bestaande sleuvennet geschreven: {backup_path}", flush=True)
    print("Nieuwe sleuf met alle kruisingen en T-aansluitingen knippen/noden...", flush=True)
    noded, affected_count, used_local_noding = engine.incremental_node_cable_network(
        cables_rd,
        new_rd,
        points_rd,
        stations_rd,
        float(config.get("node_tolerance_m", 1.0)),
    )
    noded = noded.to_crs(original_crs)
    result_path.unlink(missing_ok=True)
    noded.to_file(result_path, layer="sleuven_genood", driver="GPKG")
    summary = {
        "new_route_count": int(len(new_rd)),
        "noded_part_count": int(len(noded)),
        "new_route_length_m": float(new_rd.geometry.length.sum()),
        "affected_existing_parts": int(affected_count),
        "used_local_noding": bool(used_local_noding),
    }
    Path(config["summary_path"]).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Genood sleuvennet geschreven: {len(noded):,} lijnstukken.", flush=True
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1]))
    except Exception as exc:
        print(f"FOUT: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
