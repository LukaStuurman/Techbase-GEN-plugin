"""QGIS integration regressions for station imports, BAG additions and unknown housing."""
import os
from pathlib import Path
import sys
import tempfile

from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsApplication, QgsCoordinateTransform, QgsFeature, QgsField,
                       QgsGeometry, QgsProject, QgsVectorLayer, QgsVectorFileWriter)


def make_layer(kind, name, fields):
    layer = QgsVectorLayer(f"{kind}?crs=EPSG:28992", name, "memory")
    layer.dataProvider().addAttributes([QgsField(n, t) for n, t in fields])
    layer.updateFields()
    QgsProject.instance().addMapLayer(layer)
    return layer


def add(layer, wkt, attrs):
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromWkt(wkt))
    for name, val in attrs.items():
        feature[name] = val
    assert layer.dataProvider().addFeature(feature)
    return feature


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    sys.path.insert(0, str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))
    from processing.core.Processing import Processing
    Processing.initialize()
    from ls_netontwerp_wizard.provider import LSNetontwerpProvider
    provider = LSNetontwerpProvider()
    QgsApplication.processingRegistry().addProvider(provider)
    from ls_netontwerp_wizard.connection_sources import CURRENT_FIELDS, add_selected_objects, assign_station, pdok_objects_layer
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    from ls_netontwerp_wizard.station_name_csv import load_station_name_lookup

    target = make_layer("Point", "LS-aansluitingen ontwerpstroom", [
        ("Master Asset ID", QVariant.String), ("Station", QVariant.String),
        ("service_connection_type_type", QVariant.String), ("Gebruiksdoel", QVariant.String),
        ("G_Type", QVariant.String), ("Gevonden_Woningtype", QVariant.String),
        ("Gevonden_Bouwjaar", QVariant.String),
    ] + [(n, QVariant.Double) for n in CURRENT_FIELDS])
    target.setCustomProperty("LSNetontwerp/review_current_layer", True)
    first = add(target, "POINT(156010 381010)", {"Master Asset ID": "8410456966819408130", "Station": "old", "Gebruiksdoel": "woonhuis"})
    second = add(target, "POINT(156011 381011)", {"Master Asset ID": "8410456966791976966", "Station": "keep"})
    housing = make_layer("Polygon", "Woningtypen BAG/3DBAG", [
        ("identificatie", QVariant.String), ("Woningtype", QVariant.String), ("bouwjaar", QVariant.Int)])
    building = add(housing, "POLYGON((156000 381000,156020 381000,156020 381020,156000 381020,156000 381000))",
                   {"identificatie": "0000000000000001", "Woningtype": "appartement", "bouwjaar": 2026})
    source = make_layer("Point", "BAG verblijfsobjecten", [(n, QVariant.String) for n in (
        "identificatie", "bronhouder_naam", "woonplaats_naam", "huisnummer", "huisletter",
        "postcode", "openbare_ruimte_naam", "toevoeging", "gebruiksdoel", "status")])
    attrs = {"bronhouder_naam": "Veldhoven", "woonplaats_naam": "Zeelst", "huisnummer": "12", "huisletter": "A",
             "postcode": "5502HC", "openbare_ruimte_naam": "Teststraat", "toevoeging": "1",
             "gebruiksdoel": "woonfunctie", "status": "Verblijfsobject gevormd"}
    add(source, "POINT(156012 381012)", {**attrs, "identificatie": "0000010000000001"})
    # Same coordinate, separate apartment: must survive deduplication.
    add(source, "POINT(156012 381012)", {**attrs, "identificatie": "0000010000000002", "toevoeging": "2"})
    add(source, "POINT(156050 381050)", {**attrs, "identificatie": "0000010000000003", "huisnummer": "14"})
    source.selectAll()
    dialog = LSNetontwerpDashboardDialog(None)
    dialog.show_connection_sources_page()
    assert dialog.page_stack.currentWidget() is dialog.connection_sources_page
    assert any(b.text() == "2e. Stationskoppeling & nieuwbouw" for b, _ in dialog._dashboard_mirrors)
    page = dialog.zero_current_page
    # QGIS' OGR connection pool may keep the GeoPackage open until process exit.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        csv = Path(directory) / "stations.csv"
        csv.write_text('"SourceFile","Master Asset ID"\n"159.528","8410456966819408130"\n', encoding="utf-8-sig")
        summary = WorkflowRunner._apply_station_names_from_csv(target, {"station_names_csv": str(csv), "station_name_csv_field": "SourceFile"})
        assert summary["matched"] == 1
        assert target.getFeature(first.id())["Station"] == "159.528"
        assert target.getFeature(second.id())["Station"] == "keep"
        target.selectByIds([first.id()])
        assert assign_station(target, "001.020") == 1
        assert target.getFeature(first.id())["Station"] == "001.020"
        assert target.getFeature(second.id())["Station"] == "keep"
        target.startEditing()
        try:
            assign_station(target, "wrong")
            raise AssertionError("Pending user edits should be refused")
        except ValueError:
            pass
        assert target.isEditable()
        target.rollBack()
        # Exercise CRS conversion as well as persistence.
        from qgis.core import QgsCoordinateReferenceSystem
        geographic = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source.crs(), geographic, QgsProject.instance())
        geometries = {}
        for feature in source.getFeatures():
            geometry = feature.geometry()
            geometry.transform(transform)
            geometries[feature.id()] = geometry
        assert source.dataProvider().changeGeometryValues(geometries)
        source.setCrs(geographic)
        result = add_selected_objects(source, target, housing, page, station="159.528")
        assert result == {"added": 3, "skipped": 0, "missing": 1}, result
        added = [f for f in target.getFeatures() if f["BAG_VBO_ID"] == "0000010000000001"]
        assert len(added) == 1
        f = added[0]
        assert [f[n] for n in ("city", "parish", "housenumber", "toevoeging", "zip_code", "huisnummertoevoeging")] == ["Veldhoven", "Zeelst", "12", "A", "5502HC", "1"]
        assert f["Gevonden_Woningtype"] == "appartement"
        assert f["Gevonden_Bouwjaar"] == "2026"
        config = page._household_context()
        assert f["Ontwerpstroom"] == config[2]["WOONHUIS_2022"]["appartement"]
        assert f["Ontwerpstroom kabel"] == config[3]["WOONHUIS_2022"]["appartement"]
        assert f["Opwek ontwerpstroom"] == 0
        assert target.selectedFeatureCount() == 3
        assert add_selected_objects(source, target, housing, page)["added"] == 0
        assert target.featureCount() == 5
        path = Path(directory) / "review.gpkg"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "connections"
        assert QgsVectorFileWriter.writeAsVectorFormatV3(target, str(path), QgsProject.instance().transformContext(), options)[0] == QgsVectorFileWriter.NoError
        reopened = QgsVectorLayer(str(path) + "|layername=connections", "saved", "ogr")
        assert reopened.isValid() and reopened.featureCount() == 5
        assert reopened.fields().lookupField("BAG_VBO_ID") >= 0
        manual_object = add(source, "POINT(5.4 51.4)", {**attrs, "identificatie": "0000010000000004", "huisnummer": "16"})
        source.selectByIds([manual_object.id()])
        assert add_selected_objects(source, reopened, None, page, manual_currents=[10, 11, 12, 13])["missing"] == 0
        reopened = None
        reopened = QgsVectorLayer(str(path) + "|layername=connections", "saved", "ogr")
        persisted = [f for f in reopened.getFeatures() if f["BAG_VBO_ID"] == "0000010000000004"][0]
        assert [persisted[n] for n in CURRENT_FIELDS] == [10, 11, 12, 13, 12, 13]
        assert reopened.featureCount() == 6
        reopened = None
        # Unknown selection works both in 2a and 2b, including absent doorlaat.
        target.selectByIds([first.id()])
        dialog.show_value_page()
        dialog.value_category_combo.setCurrentIndex(dialog.value_category_combo.findData("Huishoudelijk"))
        dialog.value_housing_combo.setCurrentIndex(dialog.value_housing_combo.findData("onbekend"))
        dialog.run_value_edit()
        assert target.getFeature(first.id())["Ontwerpstroom"] == config[2]["WOONHUIS"]["onbekend"]
        housing.selectByIds([building.id()])
        algorithm = QgsApplication.processingRegistry().algorithmById("lsnetontwerp:woningtype_selectie_herberekenen")
        assert algorithm is not None
        algorithm.createInstance().initAlgorithm()
        dialog.show_housing_page()
        dialog.housing_type_combo.setCurrentIndex(5)
        dialog.run_housing_edit()
        assert "mislukt" not in dialog.housing_status_label.text().casefold(), dialog.housing_status_label.text()
        assert target.getFeature(first.id())["Ontwerpstroom"] == config[2]["WOONHUIS_2022"]["onbekend"]
        assert target.getFeature(first.id())["Gevonden_Woningtype"] == "onbekend"
        # Explicit pand currents win over the category-table calculation.
        housing.dataProvider().addAttributes([QgsField(n, QVariant.Double) for n in CURRENT_FIELDS[:4]])
        housing.updateFields()
        assert housing.dataProvider().changeAttributeValues({building.id(): {
            housing.fields().lookupField(n): val for n, val in zip(CURRENT_FIELDS[:4], [14, 15, 16, 17])}})
        inherited = add(source, "POINT(0 0)", {**attrs, "identificatie": "0000010000000005", "huisnummer": "18"})
        geometry = QgsGeometry.fromWkt("POINT(156015 381015)")
        geometry.transform(transform)
        assert source.dataProvider().changeGeometryValues({inherited.id(): geometry})
        source.selectByIds([inherited.id()])
        result = add_selected_objects(source, target, housing, page, manual_currents=[99] * 4)
        assert result["added"] == 1 and result["missing"] == 0
        f = next(f for f in target.getFeatures() if f["BAG_VBO_ID"] == "0000010000000005")
        assert [f[n] for n in CURRENT_FIELDS] == [14, 15, 16, 17, 16, 17]
        source.selectByIds([manual_object.id()])
        result = add_selected_objects(source, target, None, page, fallback_type="onbekend")
        assert result["added"] == 1 and result["missing"] == 0
        f = next(f for f in target.getFeatures() if f["BAG_VBO_ID"] == "0000010000000004")
        assert f["Ontwerpstroom"] == config[2]["WOONHUIS"]["onbekend"]
    if "--live-pdok" in sys.argv:
        layer = pdok_objects_layer("https://api.pdok.nl/kadaster/bag/ogc/v2")
        assert layer.fields().lookupField("huisnummer") >= 0
        assert layer.fields().lookupField("bronhouder_naam") >= 0
        from qgis.core import QgsFeatureRequest, QgsRectangle
        transform = QgsCoordinateTransform(target.crs(), layer.crs(), QgsProject.instance())
        bounds = transform.transformBoundingBox(QgsRectangle(156650, 381600, 156800, 381800))
        features = list(layer.getFeatures(QgsFeatureRequest().setFilterRect(bounds).setLimit(5)))
        assert features, "Live PDOK returned no objects in the test extent"
        print("PDOK_PROVIDER_OK", flush=True)
    if "--csv" in sys.argv:
        path = sys.argv[sys.argv.index("--csv") + 1]
        lookup, summary = load_station_name_lookup(path, "SourceFile")
        assert lookup["8410456966819408130"] == "159.528"
        print("EXAMPLE_CSV_OK", summary["csv_rows"], "rows", len(set(lookup.values())), "stations", flush=True)
    print("CONNECTION_SOURCES_TEST_OK", flush=True)
    if "--preview" in sys.argv:
        dialog.show_connection_sources_page()
        dialog.resize(1020, 850)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
    os._exit(0)


if __name__ == "__main__":
    main()
