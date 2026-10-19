"""BAG use separation, interactive review and both actual recalculation routes."""
import os
from pathlib import Path
import sys

from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsApplication, QgsFeature, QgsField, QgsGeometry,
                       QgsProcessingContext, QgsProcessingFeedback, QgsProject, QgsVectorLayer)


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.test_connection_sources import make_layer, add
    from ls_netontwerp_wizard.connection_sources import add_selected_objects, CURRENT_FIELDS
    from ls_netontwerp_wizard.bag_current_rules import has_residential_usage
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.algorithms.woningtype_selectie_herberekenen_tool import (
        _load_design_module, WoningtypeSelectieHerberekenenAlgorithm)

    for usage in ("woonfunctie", "Woonfunctie", ["kantoorfunctie", "woonfunctie"], '["woonfunctie", "winkelfunctie"]'):
        assert has_residential_usage(usage), usage
    for usage in ("nietwoonfunctie", "woonhuis", "kantoorfunctie", "", None):
        assert not has_residential_usage(usage), usage

    target = make_layer("Point", "LS-aansluitingen ontwerpstroom", [
        ("service_connection_type_type", QVariant.String), ("Gebruiksdoel", QVariant.String),
        ("G_Type", QVariant.String), ("Gevonden_Woningtype", QVariant.String),
        ("Gevonden_Bouwjaar", QVariant.String),
    ] + [(name, QVariant.Double) for name in CURRENT_FIELDS])
    target.setCustomProperty("LSNetontwerp/review_current_layer", True)
    housing = make_layer("Polygon", "Woningtypen BAG", [
        ("Woningtype", QVariant.String), ("bouwjaar", QVariant.Int),
    ] + [(name, QVariant.Double) for name in CURRENT_FIELDS[:4]])
    for x, house_type, year in ((0, "vrijstaande woning", 2000), (30, "hoekwoning", 2026), (60, "appartement", 2026)):
        attrs = {"Woningtype": house_type, "bouwjaar": year}
        # An apartment pand has explicit currents, which must not leak into its office.
        attrs.update(dict(zip(CURRENT_FIELDS[:4], (14, 15, 16, 17) if x == 60 else (0, 0, 0, 0))))
        add(housing, f"POLYGON(({x} 0,{x+20} 0,{x+20} 20,{x} 20,{x} 0))", attrs)
    source = make_layer("Point", "BAG verblijfsobjecten", [(name, QVariant.String) for name in (
        "identificatie", "gebruiksdoel", "huisnummer", "postcode", "openbare_ruimte_naam", "woonplaats_naam")])
    uses = ("woonfunctie", "woonfunctie", "woonfunctie", "kantoorfunctie", "winkelfunctie",
            "bijeenkomstfunctie", "industriefunctie", "", '["kantoorfunctie", "woonfunctie"]')
    for i, use in enumerate(uses):
        x = (10, 40, 70)[i] if i < 3 else 72
        add(source, f"POINT({x} 10)", {"identificatie": f"{i+1:016d}", "gebruiksdoel": use,
            "huisnummer": str(i+1), "postcode": "5502HC", "openbare_ruimte_naam": "Teststraat", "woonplaats_naam": "Zeelst"})
    source.selectAll()
    dialog = LSNetontwerpDashboardDialog(None)
    zero = dialog.zero_current_page
    result = add_selected_objects(source, target, housing, zero, fallback_type="vrijstaande woning", manual_currents=[99]*4)
    assert result == {"added": 9, "skipped": 0, "missing": 5}, result
    by_id = {f["BAG_VBO_ID"]: f for f in target.getFeatures()}
    assert by_id["0000000000000001"]["Ontwerpstroom"] == 7.0  # new-build VBO uses Type 3 despite original 2000 pand year
    assert by_id["0000000000000001"]["Nieuwbouw"] == "1"
    assert by_id["0000000000000001"]["OntwerpstroomType"] == (
        "Type 3: Laagbouw huishoudens vanaf bouwjaar 2022 met een individuele warmtepomp en tapwaterbuffer"
    )
    assert by_id["0000000000000001"]["Gevonden_Bouwjaar"] == "2000"
    assert by_id["0000000000000002"]["Ontwerpstroom"] == 5.3
    assert [by_id["0000000000000003"][name] for name in CURRENT_FIELDS[:4]] == [14, 15, 16, 17]
    for i in range(4, 9):
        f = by_id[f"{i:016d}"]
        assert [f[name] for name in CURRENT_FIELDS] == [0]*6
        assert not str(f["Gevonden_Woningtype"]).strip()
    legacy = by_id["0000000000000004"]
    target.dataProvider().changeAttributeValues({legacy.id(): {target.fields().lookupField(name): 77 for name in CURRENT_FIELDS}})
    # Earlier imports with inherited positive currents still need explicit review.
    assert zero.refresh(review_layer=target) == 5
    assert zero.table.columnCount() == 13
    assert zero.table.item(0, 1).text()
    assert "Teststraat" in zero.table.item(0, 2).text()
    # The actual repair action fills a business category and stores gas metadata.
    zero.table.selectRow(0)
    chosen_id = zero._selected_feature_ids()[0]
    zero.category_combo.setCurrentIndex(zero.category_combo.findData("Zakelijk"))
    zero.unit_combo.setCurrentIndex(zero.unit_combo.findData("63"))
    zero.gas_combo.setCurrentIndex(zero.gas_combo.findData("G10-G25"))
    zero.apply_category()
    chosen = target.getFeature(chosen_id)
    assert chosen["HerstelCat"] == "Zakelijk" and chosen["G_Type"] == "G10-G25"
    chosen_currents = [chosen[name] for name in CURRENT_FIELDS]
    assert zero.table.rowCount() == 4

    # Full spatial recalculation on a layer that already has output fields.
    module = _load_design_module()
    alg = module.OntwerpstroomSpatial()
    alg.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    feedback = QgsProcessingFeedback()
    output, ok = alg.run({alg.INPUT_LAYER: target, alg.INPUT_PANDEN: housing,
                         alg.VAL_APPARTEMENT_ZONDER_DOORLAAT: False,
                         alg.OUTPUT: "memory:"}, context, feedback)
    assert ok, output
    recalculated = context.getMapLayer(output[alg.OUTPUT])
    assert recalculated is not None and recalculated.featureCount() == 9
    assert len(recalculated.fields()) == len(target.fields())
    by_id = {f["BAG_VBO_ID"]: f for f in recalculated.getFeatures()}
    assert [by_id["0000000000000001"][name] for name in CURRENT_FIELDS] == [7.0, 7.5, 8.9, 9.2, 8.9, 9.2]
    assert by_id["0000000000000001"]["Nieuwbouw"] == "1"
    assert by_id["0000000000000001"]["Gevonden_Bouwjaar"] == "2000"
    assert [by_id["0000000000000002"][name] for name in CURRENT_FIELDS] == [5.3, 6.3, 5.7, 5.9, 5.7, 6.3]
    assert [by_id["0000000000000003"][name] for name in CURRENT_FIELDS] == [4.2, 5.1, 0, 0, 4.2, 5.1]
    assert [by_id[chosen["BAG_VBO_ID"]][name] for name in CURRENT_FIELDS] == chosen_currents
    for i in range(4, 9):
        f = by_id[f"{i:016d}"]
        if f["BAG_VBO_ID"] != chosen["BAG_VBO_ID"]:
            assert [f[name] for name in CURRENT_FIELDS] == [0]*6

    # Raw GEN inputs receive the missing output fields and their original calculations.
    raw = make_layer("Point", "GEN bron", [("service_connection_type_type", QVariant.String),
                     ("Gebruiksdoel", QVariant.String), ("G_Type", QVariant.String)])
    add(raw, "POINT(10 10)", {"service_connection_type_type": "3 x 25 A", "Gebruiksdoel": "woonhuis", "G_Type": ""})
    add(raw, "POINT(500 500)", {"service_connection_type_type": "verblijfsobject", "Gebruiksdoel": "woonfunctie", "G_Type": ""})
    output, ok = alg.run({alg.INPUT_LAYER: raw, alg.INPUT_PANDEN: housing, alg.OUTPUT: "memory:"}, context, feedback)
    assert ok, output
    raw_result = list(context.getMapLayer(output[alg.OUTPUT]).getFeatures())
    assert [raw_result[0][name] for name in CURRENT_FIELDS] == [7.5, 8.1, 8.9, 9.2, 8.9, 9.2]
    assert [raw_result[1][name] for name in CURRENT_FIELDS] == [0]*6  # missing woningtype needs review

    residential = next(f for f in target.getFeatures() if f["BAG_VBO_ID"] == "0000000000000001")
    zero.apply_values_to_layer(target, [residential.id()], "Huishoudelijk", {
        "consumption_trafo": 1.25, "consumption_cable": 2.5,
        "generation_trafo": 3.75, "generation_cable": 0,
    }, house_type="vrijstaande woning", manual_override=True)
    output, ok = alg.run({alg.INPUT_LAYER: target, alg.INPUT_PANDEN: housing, alg.OUTPUT: "memory:"}, context, feedback)
    assert ok, output
    manual = next(f for f in context.getMapLayer(output[alg.OUTPUT]).getFeatures() if f["BAG_VBO_ID"] == residential["BAG_VBO_ID"])
    assert [manual[name] for name in CURRENT_FIELDS] == [1.25, 2.5, 3.75, 0, 3.75, 2.5]

    # Changing a pand's housing type must recalculate residential BAG objects only.
    housing.selectAll()
    housing_alg = WoningtypeSelectieHerberekenenAlgorithm()
    housing_alg.initAlgorithm()
    output, ok = housing_alg.run({housing_alg.WONINGEN: housing, housing_alg.AANSLUITINGEN: target,
                                housing_alg.NIEUW_WONINGTYPE: 3}, context, feedback)
    assert ok, output
    assert [target.getFeature(chosen_id)[name] for name in CURRENT_FIELDS] == chosen_currents
    assert target.getFeature(chosen_id)["HerstelCat"] == "Zakelijk"
    residential = next(f for f in target.getFeatures() if f["BAG_VBO_ID"] == "0000000000000001")
    assert residential["Ontwerpstroom"] > 0 and residential["Gevonden_Woningtype"] == "tussenwoning/geschakeld"

    # The source page automatically opens review for the explicitly chosen target layer.
    other_target = make_layer("Point", "Andere aansluitingen", [(field.name(), field.type()) for field in target.fields()])
    other_target.setCustomProperty("LSNetontwerp/review_current_layer", True)
    source.selectByIds([next(f.id() for f in source.getFeatures() if f["gebruiksdoel"] == "winkelfunctie")])
    dialog.show_connection_sources_page()
    page = dialog.connection_sources_page
    page.target_combo.setCurrentIndex(page.target_combo.findData(other_target.id()))
    page.source_combo.setCurrentIndex(page.source_combo.findData(source.id()))
    page.housing_combo.setCurrentIndex(page.housing_combo.findData(housing.id()))
    page.add_objects()
    assert dialog.page_stack.currentWidget() is zero
    assert zero.layer is other_target and zero.table.rowCount() == 1
    assert zero.table.item(0, 3).text() == "winkelfunctie"
    zero.refresh_button.click()
    assert zero.layer is other_target and zero.table.rowCount() == 1
    assert next(other_target.getFeatures())["Hoogste Trafo"] == 0
    no_pand = add(source, "POINT(500 500)", {"identificatie": "0000000000000099", "gebruiksdoel": "woonfunctie", "huisnummer": "99"})
    source.selectByIds([no_pand.id()])
    result = add_selected_objects(source, other_target, None, zero, manual_currents=[10, 11, 12, 13])
    assert result == {"added": 1, "skipped": 0, "missing": 0}
    no_pand_manual = next(f for f in other_target.getFeatures() if f["BAG_VBO_ID"] == "0000000000000099")
    assert no_pand_manual["HerstelHandmatig"] == "1"
    output, ok = alg.run({alg.INPUT_LAYER: other_target, alg.INPUT_PANDEN: housing, alg.OUTPUT: "memory:"}, context, feedback)
    assert ok, output
    no_pand_saved = next(f for f in context.getMapLayer(output[alg.OUTPUT]).getFeatures() if f["BAG_VBO_ID"] == "0000000000000099")
    assert [no_pand_saved[name] for name in CURRENT_FIELDS] == [10, 11, 12, 13, 12, 13]
    zero.apply_values_to_layer(other_target, [no_pand_manual.id()], "Huishoudelijk", {}, house_type="hoekwoning")
    output, ok = alg.run({alg.INPUT_LAYER: other_target, alg.INPUT_PANDEN: housing, alg.OUTPUT: "memory:"}, context, feedback)
    assert ok, output
    no_pand_saved = next(f for f in context.getMapLayer(output[alg.OUTPUT]).getFeatures() if f["BAG_VBO_ID"] == "0000000000000099")
    assert [no_pand_saved[name] for name in CURRENT_FIELDS] == [5.3, 6.3, 5.7, 5.9, 5.7, 6.3]
    assert no_pand_saved["Nieuwbouw"] == "1"
    if "--preview" in sys.argv:
        from qgis.PyQt.QtGui import QFont, QFontDatabase
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
        app.setFont(QFont("Segoe UI", 10))
        zero.category_combo.setCurrentIndex(zero.category_combo.findData("Zakelijk"))
        dialog.resize(1200, 950)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
    print("BAG_USAGE_CURRENTS_TEST_OK (mixed uses, shared apartment pand, actual review UI, full spatial recalculation, housing edit, target selection)", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
