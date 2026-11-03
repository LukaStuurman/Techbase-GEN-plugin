"""Regression tests for reusing BAG housing footprints during LS clustering.

Run in a QGIS Python environment with geopandas:
    python -m unittest ls_netontwerp_wizard.test_bag_clustering_reuse
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import geopandas as gpd
from shapely.geometry import box

from .algorithms.laagspanning_clustering_lib import maak_clustering_engine as engine


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class BagReuseTests(unittest.TestCase):
    def setUp(self):
        self.original_path = engine.BAG_BUILDINGS_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(setattr, engine, "BAG_BUILDINGS_PATH", self.original_path)

    def test_local_housing_layer_is_used_without_http(self):
        path = Path(self.temp_dir.name) / "woningtypen.gpkg"
        gpd.GeoDataFrame(
            {
                "BAG_ID": ["0000000000000001", "0000000000000002"],
                "Status": ["Pand in gebruik", "Pand gesloopt"],
            },
            geometry=[
                box(120000, 440000, 120020, 440020),
                box(120025, 440000, 120040, 440020),
            ],
            crs=engine.CRS_RD,
        ).to_file(path, driver="GPKG")
        engine.BAG_BUILDINGS_PATH = path
        with patch.object(engine, "urlopen", side_effect=AssertionError("HTTP called")):
            found = engine.fetch_bag_buildings((119999, 439999, 120041, 440021))
        self.assertEqual(list(found["BAG_ID"]), ["0000000000000001"])
        self.assertEqual(found.crs.to_epsg(), 28992)

    def test_local_layer_missing_ids_fails_explicitly(self):
        path = Path(self.temp_dir.name) / "woningtypen.gpkg"
        gpd.GeoDataFrame(
            {"Status": ["Pand in gebruik"]},
            geometry=[box(120000, 440000, 120020, 440020)],
            crs=engine.CRS_RD,
        ).to_file(path, driver="GPKG")
        engine.BAG_BUILDINGS_PATH = path
        with self.assertRaisesRegex(RuntimeError, "BAG_ID"):
            engine.fetch_bag_buildings((119999, 439999, 120021, 440021))

    def test_timeout_retries_same_api_page(self):
        payload = {"type": "FeatureCollection", "features": [], "links": []}
        with patch.object(
            engine, "urlopen",
            side_effect=[TimeoutError("timed out"), _Response(payload)]
        ) as urlopen, patch.object(engine.time, "sleep") as sleeper:
            result = engine._fetch_bag_page("https://example.test/items")
        self.assertEqual(result, payload)
        self.assertEqual(urlopen.call_count, 2)
        sleeper.assert_called_once_with(1)

    def test_bad_request_does_not_retry(self):
        error = HTTPError("https://example.test/items", 400, "Bad request", {}, None)
        with patch.object(engine, "urlopen", side_effect=error) as urlopen:
            with self.assertRaisesRegex(RuntimeError, "poging 1/3"):
                engine._fetch_bag_page("https://example.test/items")
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
