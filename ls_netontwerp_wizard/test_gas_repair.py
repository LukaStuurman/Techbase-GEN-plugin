"""Gas-preserving repair and recalculation regressions without a QGIS install.

The arithmetic, repair method and full processing method are loaded from the
production sources. Small in-memory adapters replace only the QGIS data API.
This exercises the changed boundaries; it is not a GUI or provider integration
test. Run: python ls_netontwerp_wizard/test_gas_repair.py
"""
from __future__ import annotations

import ast
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from ls_netontwerp_wizard import bag_current_rules, current_edit_metadata, kader_20

SOURCE = ROOT / "algorithms" / "Ontwersptroom TRAFO, KABEL & OPWEK voor XML KADER 2026 V5.py"
COMPONENTS = ("Ontwerpstroom", "Ontwerpstroom kabel", "Opwek ontwerpstroom", "Kabel opwek ontwerpstroom")
CURRENT_KEYS = ("consumption_trafo", "consumption_cable", "generation_trafo", "generation_cable")


class Field:
    def __init__(self, name, kind=None):
        self._name = name

    def name(self):
        return self._name


class Fields(list):
    def lookupField(self, name):
        return next((i for i, f in enumerate(self) if f.name() == name), -1)

    indexOf = lookupField


class Feature:
    def __init__(self, fields, values=None, fid=-1):
        self._fields, self.values, self._fid = fields, dict(values or {}), fid

    def id(self):
        return self._fid

    def fields(self):
        return self._fields

    def __getitem__(self, key):
        name = self._fields[key].name() if isinstance(key, int) else key
        if self._fields.lookupField(name) < 0:
            raise KeyError(name)
        return self.values.get(name)

    def __setitem__(self, name, value):
        if self._fields.lookupField(name) < 0:
            raise KeyError(name)
        self.values[name] = value

    def attributes(self):
        return [self.values.get(f.name()) for f in self._fields]

    def setAttributes(self, values):
        self.values = {f.name(): value for f, value in zip(self._fields, values)}

    def geometry(self):
        return None

    def setGeometry(self, geometry):
        pass


class Request:
    def __init__(self):
        self.ids = None

    def setFilterFids(self, ids):
        self.ids = set(ids)
        return self

    def setSubsetOfAttributes(self, *args):
        return self


class Layer:
    def __init__(self, rows, extra_fields=(), gas_field="G_Type"):
        names = list(dict.fromkeys([
            "fid", "id", "service_connection_type_type", "Gebruiksdoel", gas_field,
            "Kader20ToekomstigeAansluitwaarde", "Gevonden_Woningtype", "Gevonden_Bouwjaar",
            "KaderVersie", "KaderType", *COMPONENTS, "Hoogste Trafo", "Hoogste Kabel",
            *extra_fields, *(key for row in rows for key in row),
        ]))
        self._fields = Fields(Field(name) for name in names if name)
        self.features = {}
        self.properties = {}
        for i, row in enumerate(rows, 1):
            values = {name: 0.0 for name in (*COMPONENTS, "Hoogste Trafo", "Hoogste Kabel")}
            values.update({"fid": i, "id": str(i), "Gebruiksdoel": "bedrijf", **row})
            self.features[i] = Feature(self._fields, values, i)

    def fields(self):
        return Fields(self._fields)

    def getFeatures(self, request=None):
        return iter(f for i, f in self.features.items() if request is None or request.ids is None or i in request.ids)

    def getFeature(self, fid):
        return self.features[fid]

    def dataProvider(self):
        return self

    def capabilities(self):
        return 1

    def addAttributes(self, fields):
        self._fields.extend(fields)
        return True

    def changeAttributeValues(self, changes):
        for fid, row in changes.items():
            for column, value in row.items():
                assert column >= 0, "Cannot write an unresolved field"
                self.features[fid][self._fields[column].name()] = value
        return True

    def customProperty(self, name, default=None):
        return self.properties.get(name, default)

    def setCustomProperty(self, name, value):
        self.properties[name] = value

    def isValid(self):
        return True

    def isEditable(self):
        return False

    def updateFields(self):
        pass

    def triggerRepaint(self):
        pass

    def featureCount(self):
        return len(self.features)

    def wkbType(self):
        return 0

    def sourceCrs(self):
        return None


class Feedback:
    def __init__(self):
        self.warnings = []

    def pushWarning(self, message):
        self.warnings.append(message)

    def pushInfo(self, message):
        pass

    def isCanceled(self):
        return False

    def setProgress(self, value):
        pass


class AlgorithmAPI:
    def parameterAsMatrix(self, parameters, name, context):
        return parameters[name]

    def parameterAsString(self, parameters, name, context):
        return str(parameters.get(name, ""))

    def parameterAsInt(self, parameters, name, context):
        return int(parameters[name])

    parameterAsEnum = parameterAsInt

    def parameterAsBool(self, parameters, name, context):
        return bool(parameters[name])

    def parameterAsDouble(self, parameters, name, context):
        return float(parameters[name])

    def parameterAsVectorLayer(self, parameters, name, context):
        return parameters[name]

    parameterAsSource = parameterAsVectorLayer

    def parameterAsSink(self, parameters, name, context, fields, *_args):
        self.output_features = []
        self.output_fields = fields
        sink = SimpleNamespace(addFeature=lambda feature, mode: self.output_features.append(feature))
        return sink, "in-memory-test-output"


def _compile(nodes, filename, scope):
    prefix = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[prefix, *nodes], type_ignores=[]))
    exec(compile(tree, str(filename), "exec"), scope)


def load_production():
    project = SimpleNamespace(setDirty=lambda value: None, fileName=lambda: "", write=lambda: True)
    scope = {
        "re": re, "math": math, "kader_20": kader_20,
        "QgsField": Field, "QgsFeature": Feature, "QgsFeatureRequest": Request,
        "QVariant": SimpleNamespace(String=str, Double=float),
        "QgsVectorDataProvider": SimpleNamespace(ChangeAttributeValues=1),
        "QgsFeatureSink": SimpleNamespace(FastInsert=1),
        "QgsProcessingAlgorithm": AlgorithmAPI,
        "QgsProject": SimpleNamespace(instance=lambda: project), "QWidget": object,
        **{name: getattr(bag_current_rules, name) for name in dir(bag_current_rules) if not name.startswith("_")},
        **{name: getattr(current_edit_metadata, name) for name in dir(current_edit_metadata) if not name.startswith("_")},
    }
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.Assign))]
    algorithm = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OntwerpstroomSpatial")
    _compile([*nodes, algorithm], SOURCE, scope)
    module = SimpleNamespace(**scope)
    config_path = ROOT / "algorithms" / "woningtype_selectie_herberekenen_tool.py"
    config_tree = ast.parse(config_path.read_text(encoding="utf-8-sig"))
    _compile([node for node in config_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_configurations"], config_path, scope)
    presets_path = ROOT / "current_presets.py"
    presets_tree = ast.parse(presets_path.read_text(encoding="utf-8-sig"))
    _compile([node for node in presets_tree.body if isinstance(node, (ast.FunctionDef, ast.Assign))], presets_path, scope)
    page_path = ROOT / "zero_current_page.py"
    page_tree = ast.parse(page_path.read_text(encoding="utf-8-sig"))
    page = next(node for node in page_tree.body if isinstance(node, ast.ClassDef) and node.name == "ZeroCurrentPage")
    _compile([page], page_path, scope)
    return scope, module


def component_values(feature):
    return tuple(feature[name] for name in COMPONENTS)


def fixture(service="3 x 63 A", gas="G4", future="3 x 63 A", gas_field="G_Type", **extra):
    return {"service_connection_type_type": service, gas_field: gas, "Kader20ToekomstigeAansluitwaarde": future, **extra}


class GasRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.production, cls.calc = load_production()

    def context(self, framework="2.0", gas_field="G_Type"):
        values = {"design_framework": framework, "field_gas": gas_field,
                  "field_passthrough": "service_connection_type_type", "one_phase_exception": True}
        return (self.calc, values, *self.production["_configurations"](values, self.calc))

    def page(self, framework="2.0", gas_field="G_Type"):
        context = self.context(framework, gas_field)
        page = object.__new__(self.production["ZeroCurrentPage"])
        page.host = SimpleNamespace(_workflow_field_defaults=lambda: context[1])
        page._household_context = lambda: context
        return page

    def repair(self, layer, framework="2.0", gas_field="G_Type", ids=None, values=(999, 998, 997, 996), **kwargs):
        return self.page(framework, gas_field).apply_values_to_layer(
            layer, list(layer.features) if ids is None else ids, "Zakelijk",
            dict(zip(CURRENT_KEYS, values)), **kwargs,
        )

    def process(self, layer, framework="2.0", gas_field="G_Type"):
        params = {
            "INPUT_LAYER": layer, "INPUT_PANDEN": Layer([]), "FLD_DOORLAAT": "service_connection_type_type",
            "FLD_GEBRUIK": "Gebruiksdoel", "FLD_GAS": gas_field,
            "FLD_WONINGTYPE": "woningtype", "FLD_BOUWJAAR": "bouwjaar",
            "VAL_KADER": {"3.0": 0, "3.1": 1, "3.2": 1, "2.0": 2}[framework],
            "VAL_1FASE_EXCEPTION": True, "VAL_APPARTEMENT_ZONDER_DOORLAAT": True,
            "VAL_OPWEK_ZERO_IDS": "8,9", "VAL_OPWEK_ZERO_TEXT": "",
            "VAL_LIMIT_FASE": 3, "VAL_LIMIT_AMP": 40, "VAL_FALLBACK_LAAD": 3.7,
            "VAL_BOUWJAAR_GRENS": 2022,
        }
        for suffix, constant in {
            "WOONHUIS":"WOONHUIS", "WOONHUIS_2022":"WOONHUIS_2022", "WOONHUIS_KABEL":"WOONHUIS_KABEL",
            "WOONHUIS_KABEL_2022":"WOONHUIS_KABEL_2022", "WOONHUIS_OPWEK":"WOONHUIS_OPWEK",
            "WOONHUIS_OPWEK_KABEL":"WOONHUIS_OPWEK_KABEL", "AMP":"AMP_GLOBAL", "TYPE":"TYPE_CFG",
            "STRAAT":"STRAAT", "LAAD":"LAAD", "LAAD_KABEL":"LAAD_KABEL", "GAS":"GAS_ADVIES",
            "GAS_KABEL":"GAS_ADVIES_KABEL", "REGEX":"REGEX", "KEYWORDS":"KEYWORDS",
        }.items():
            params["MAT_"+suffix] = self.production["DEF_"+constant]
        algorithm = self.production["OntwerpstroomSpatial"]()
        feedback = Feedback()
        algorithm.processAlgorithm(params, None, feedback)
        result = Layer([dict(f.values) for f in algorithm.output_features],
                       extra_fields=[f.name() for f in algorithm.output_fields], gas_field=gas_field)
        # Simulate the next processing layer: project properties are not copied,
        # provider feature IDs may differ, stable source IDs and fields remain.
        result.features = {1000+i: Feature(result._fields, f.values, 1000+i)
                           for i, f in result.features.items()}
        return result

    def by_source_id(self, layer):
        return {int(f["fid"]): f for f in layer.getFeatures()}

    def preview(self, layer, framework):
        page = self.page(framework)
        return page.unit_preview(
            self.context(framework), list(layer.getFeatures()), "Zakelijk",
            page.KEEP_EXISTING_UNIT, gas_category=None, layer=layer,
        )[0]

    def test_mixed_gas_bulk_preserves_source_and_distinct_components(self):
        layer = Layer([fixture(gas=gas) for gas in ("G4", "G10", "G16")])
        self.repair(layer, gas_category=None, future_connection="3 x 63 A")
        self.assertEqual([f["G_Type"] for f in layer.getFeatures()], ["G4", "G10", "G16"])
        self.assertEqual([component_values(f) for f in layer.getFeatures()],
                         [(65.,65.,65.,65.), (138.,65.,138.,65.), (138.,65.,138.,65.)])

    def test_saved_mixed_futures_are_preserved_per_connection(self):
        layer = Layer([fixture(gas="G10"), fixture(service="3 x 160 A", gas="G16", future="3 x 160 A")])
        self.repair(layer, gas_category=None, future_connection=None)
        self.assertEqual([f["Kader20ToekomstigeAansluitwaarde"] for f in layer.getFeatures()], ["3 x 63 A", "3 x 160 A"])
        self.assertEqual([component_values(f) for f in layer.getFeatures()], [(138.,65.,138.,65.), (210.,210.,210.,210.)])

    def test_current_gas_advice_does_not_use_the_future_service(self):
        layer = Layer([fixture(service="3 x 25 A", gas="G10", future="3 x 160 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 25 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 160 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 95 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 125 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 315 A"),
                       fixture(service="3 x 25 A", gas="G4", future="3 x 63 A"),
                       fixture(service="3 x 63 A", gas="G10", future="3 x 45 A")])
        self.repair(layer, gas_category=None, future_connection=None)
        expected = [
            (138.,138.,138.,138.), (138.,65.,138.,65.),
            (138.,138.,138.,138.), (138.,85.,138.,85.),
            (138.,106.,138.,106.), (267.8,267.8,267.8,267.8),
            (65.,65.,65.,65.), (0.,0.,0.,0.),
        ]
        self.assertEqual([component_values(f) for f in layer.getFeatures()], expected)
        first = self.process(layer)
        self.assertEqual([component_values(f) for f in first.getFeatures()], expected)
        # Below/equal to 80 A only supported 2.0 rows apply. A future 45 A
        # gap is not replaced by the current 63 A supply or by gas advice.
        self.assertEqual(layer.getFeature(8)["Kader20ToekomstigeAansluitwaarde"], "3 x 45 A")

    def test_explicit_gas_override_changes_only_selected_sources(self):
        layer = Layer([fixture(gas=gas) for gas in ("G4", "G10", "G16")])
        self.repair(layer, ids=[1,2], gas_category=">G25", future_connection="3 x 63 A")
        self.assertEqual([f["G_Type"] for f in layer.getFeatures()], [">G25", ">G25", "G16"])
        self.assertEqual(component_values(layer.getFeature(1)), (210.,65.,210.,65.))
        self.assertEqual(component_values(layer.getFeature(3)), (0.,0.,0.,0.))

    def test_custom_gas_field_and_unknown_values_are_not_filled(self):
        class NullValue:
            def __str__(self):
                return "NULL"
        unknown = NullValue()
        gases = ("G16", "", None, unknown, "Onbekend")
        layer = Layer([fixture(gas=g, gas_field="Gasbron") for g in gases], gas_field="Gasbron")
        self.repair(layer, gas_field="Gasbron", gas_category=None, future_connection="3 x 63 A")
        self.assertEqual([f["Gasbron"] for f in layer.getFeatures()], list(gases))
        self.assertEqual(layer.fields().lookupField("G_Type"), -1)
        self.assertEqual(component_values(layer.getFeature(1)), (138.,65.,138.,65.))
        for fid in (2,3,4,5):
            self.assertEqual(component_values(layer.getFeature(fid)), (65.,65.,65.,65.))

    def test_current_staffel_fallback_does_not_become_explicit_future(self):
        rows = (
            ("3 x 35 A", "G4", (32.,32.,32.,32.)),
            ("3 x 40 A", "G4", (32.,32.,32.,32.)),
            ("3 x 50 A", "G4", (44.,44.,44.,44.)),
            ("3 x 63 A", "G10", (138.,65.,138.,65.)),
            ("3 x 80 A", "G4", (65.,65.,65.,65.)),
            ("3 x 160 A", "G16", (210.,210.,210.,210.)),
            ("3 x 250 A", "G4", (210.,210.,210.,210.)),
            ("3 x 95 A", "G4", (85.,85.,85.,85.)),
            ("3 x 125 A", "G4", (106.,106.,106.,106.)),
            ("3 x 315 A", "G4", (267.8,267.8,267.8,267.8)),
            ("3 x 1000 A", "G4", (850.,850.,850.,850.)),
            ("3 x 45 A", "G4", (0.,0.,0.,0.)),
            ("3 x 60 A", "G4", (0.,0.,0.,0.)),
        )
        layer = Layer([fixture(service=service, gas=gas, future=None) for service, gas, _ in rows])
        self.repair(layer, gas_category=None, future_connection=None)
        first = self.process(layer)
        second = self.process(first)
        for result in (layer, first, second):
            for feature, (service, gas, expected) in zip(result.getFeatures(), rows):
                self.assertEqual(component_values(feature), expected, service)
                self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))
                self.assertEqual(feature["service_connection_type_type"], service)
                self.assertEqual(feature["G_Type"], gas)
        small = Layer([fixture(service=service, future=None)
                       for service in ("1 x 25 A", "3 x 20 A", "3 x 25 A")])
        self.repair(small, gas_category=None, future_connection=None)
        self.assertEqual([component_values(f) for f in small.getFeatures()], [(8.7,8.7,8.7,8.7)]*3)

    def test_amp_conversion_boundaries_and_full_connection_parser(self):
        for text, expected in (
            ("3x999A", (3,999.)), ("3x1000A", (3,1000.)),
            ("3 × 1000 A", (3,1000.)), ("3 fase 1000 A", (3,1000.)),
            ("1000 A", (3,1000.)), ("3x80.1A", (3,80.1)),
            ("3 fase 100,1 A", (3,100.1)), ("Onbekend", (0,0.)),
        ):
            with self.subTest(connection=text):
                self.assertEqual(self.calc.parse_doorlaat(text), expected)
        boundaries = (
            (80,65.), (80.1,85.), (100,85.), (100.1,106.),
            (125,106.), (125.1,138.), (160,138.), (160.1,210.),
            (250,210.), (251,213.3), (315,267.8), (1000,850.),
        )
        layer = Layer([fixture(service=f"3 x {amps:g} A", future=None) for amps, _ in boundaries])
        first = self.process(layer)
        self.assertEqual([component_values(f) for f in first.getFeatures()],
                         [(current,)*4 for _, current in boundaries])

    def test_large_business_fallback_uses_the_active_conversion_matrix(self):
        context = list(self.context("2.0"))
        for index, expected in ((2,90.), (3,92.)):
            config = dict(context[index])
            config["AMP_GLOBAL"] = [dict(row) for row in config["AMP_GLOBAL"]]
            for row in config["AMP_GLOBAL"]:
                if row["min"] == 80 and row["max"] == 100:
                    row["fix"] = expected
            context[index] = config
        page = self.page("2.0")
        page._household_context = lambda: tuple(context)
        layer = Layer([fixture(service="3 x 95 A", future=None)])
        page.apply_values_to_layer(layer, [1], "Zakelijk", dict(zip(CURRENT_KEYS,(0.,)*4)),
                                   gas_category=None, future_connection=None)
        self.assertEqual(component_values(layer.getFeature(1)), (90.,92.,90.,92.))
        self.assertIn(layer.getFeature(1)["Kader20ToekomstigeAansluitwaarde"], (None,""))

    def test_street_and_charging_extensions_keep_profile_and_source_values(self):
        cases = [
            ("straatmeubilair", "1 x 6 A", 5.8),
            ("straatmeubilair", "1 x 10 A", 5.8),
            ("straatmeubilair", "1 x 25 A", 5.8),
            ("straatmeubilair", "1 x 35 A", 5.8),
            ("straatmeubilair", "1 x 125 A", 5.8),
            ("straatmeubilair", "3 x 35 A", 22.),
            ("straatmeubilair", "3 x 40 A", 22.),
            ("straatmeubilair", "3 x 80 A", 36.),
            ("straatmeubilair", "3 x 55 A", 0.),
            ("straatmeubilair", "3 x 35.1 A", 0.),
            ("straatmeubilair", "1 x 0 A", 0.),
            ("straatmeubilair", "Onbekend", 5.8),
            ("straatmeubilair", None, 5.8),
            ("oplaadpunt", "3 x 55 A", 0.),
        ]
        for category in ("straatmeubilair", "oplaadpunt"):
            cases.extend((category, service, current) for service, current in
                         (("3 x 95 A",85.), ("3 x 125 A",106.), ("3 x 315 A",267.8)))
        # G40 would force business gas advice upward. These profiles must
        # keep their consumption conversion, zero generation and category.
        layer = Layer([fixture(service=service, gas="G40", future=None,
                               Gebruiksdoel=category) for category, service, _ in cases])
        first = self.process(layer)
        second = self.process(first)
        for result in (first, second):
            for feature, (category, service, expected) in zip(result.getFeatures(), cases):
                self.assertEqual(component_values(feature), (expected,expected,0.,0.), (category,service))
                self.assertEqual(feature["Gebruiksdoel"], category)
                self.assertEqual(feature["service_connection_type_type"], service)
                self.assertEqual(feature["G_Type"], "G40")
                self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))
        page = self.page("2.0")
        for key, expected in (("straat6",5.8), ("straat10",5.8), ("straat25",5.8),
                              ("straat35",22.), ("straat40_50",22.)):
            preview, _ = page.unit_preview(self.context("2.0"), [], "Straatmeubilair", key)
            self.assertEqual(preview, (expected,expected,0.,0.))

    def test_automatic_current_basis_follows_changed_source_connection(self):
        layer = Layer([fixture(service="3 x 50 A", gas="G4", future=None)])
        page = self.page("2.0")
        preview, note = page.unit_preview(
            self.context("2.0"), list(layer.getFeatures()), "Zakelijk",
            page.KEEP_EXISTING_UNIT, gas_category=None, layer=layer,
        )
        self.assertEqual(preview, (44.,44.,44.,44.))
        self.assertIn("huidige aansluiting", note.casefold())
        self.assertIn("geen afzonderlijke toekomstige waarde", note.casefold())
        self.repair(layer, gas_category=None, future_connection=None)
        self.assertEqual(component_values(layer.getFeature(1)), (44.,44.,44.,44.))
        self.assertIn(layer.getFeature(1)["Kader20ToekomstigeAansluitwaarde"], (None,""))
        layer.getFeature(1)["service_connection_type_type"] = "3 x 63 A"
        self.assertEqual(self.preview(layer, "2.0"), (65.,65.,65.,65.))
        first = self.process(layer)
        f = self.by_source_id(first)[1]
        self.assertEqual(component_values(f), (65.,65.,65.,65.))
        self.assertIn(f["Kader20ToekomstigeAansluitwaarde"], (None,""))
        f["service_connection_type_type"] = "3 x 160 A"
        second = self.process(first)
        f = self.by_source_id(second)[1]
        self.assertEqual(component_values(f), (138.,138.,138.,138.))
        self.assertIn(f["Kader20ToekomstigeAansluitwaarde"], (None,""))
        self.assertEqual(f["G_Type"], "G4")

    def test_street_missing_rating_preserves_phase_evidence_and_conflicts(self):
        cases = (
            ("Onbekend", "1 fase", None, 5.8),
            (None, None, "1F", 5.8),
            ("Onbekend", "3 fase", None, 5.8),
            (None, None, "3F", 5.8),
            ("Onbekend", "1 fase", "3F", 5.8),
            ("3 fase", "1 fase", None, 5.8),
            ("3 x 40 A", "1 fase", None, 22.),
            ("3 x 35 A", "1 fase", "1F", 22.),
            ("1 x 10 A", "3 fase", "3F", 5.8),
            ("Onbekend", None, "L1", 5.8),
            ("Onbekend", None, "R", 5.8),
            ("Onbekend", None, 1, 5.8),
            ("Onbekend", None, None, 5.8),
            (None, "Onbekend", "Onbekend", 5.8),
            ("3 x 55 A", "1 fase", "1F", 0.),
            ("1 x 0 A", "1 fase", "1F", 0.),
            ("onleesbare aansluiting", "1 fase", "1F", 0.),
            ("3 x ?? A", "1 fase", None, 0.),
        )
        layer = Layer([fixture(
            service=service, gas="G40", future=None,
            Gebruiksdoel="straatmeubilair", number_of_phases=count, phase=phase,
        ) for service, count, phase, _ in cases])
        first = self.process(layer, "2.0")
        second = self.process(first, "2.0")
        for result in (first, second):
            for feature, (service, count, phase, expected) in zip(result.getFeatures(), cases):
                with self.subTest(service=service, count=count, phase=phase):
                    self.assertEqual(component_values(feature), (expected,expected,0.,0.))
                    self.assertEqual(feature["service_connection_type_type"], service)
                    self.assertEqual(feature["number_of_phases"], count)
                    self.assertEqual(feature["phase"], phase)
                    self.assertEqual(feature["G_Type"], "G40")
                    self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))
                    if service in (None, "Onbekend", "3 fase"):
                        label = str(feature["KaderType"]).casefold()
                        self.assertIn("aanname", label)
                        self.assertIn("3x25", label.replace(" ", ""))
                    if (service,count,phase) in (("Onbekend","1 fase","3F"), ("3 fase","1 fase",None)):
                        self.assertIn("tegenstrijdige fasevelden", str(feature["KaderType"]).casefold())
        # Phase evidence stays separate from the missing-rating assumption.
        # Conflicts remain visible even when the lowest design profile applies.
        for service, count, phase in (("Onbekend","1 fase","3F"), ("3 fase","1 fase",None)):
            hint = kader_20.street_phase_hint(service, count, phase)
            self.assertTrue(hint[2], (service,count,phase,hint))
        # The supplement is specific to street furniture. Charging still
        # requires its electrical rating; business retains its existing rule.
        other = Layer([
            fixture(service="Onbekend", gas="G40", future=None,
                    Gebruiksdoel="oplaadpunt", number_of_phases="1 fase"),
            fixture(service="Onbekend", gas="G40", future=None,
                    Gebruiksdoel="bedrijf", number_of_phases="1 fase"),
        ])
        result = self.process(other, "2.0")
        self.assertEqual([component_values(f) for f in result.getFeatures()],
                         [(0.,0.,0.,0.), (210.,65.,210.,65.)])

    def test_street_missing_rating_assumption_follows_source_and_preserves_other_frameworks(self):
        services = (None, "", "  ", "Onbekend", "NULL", "n.v.t.", "3 fase", "3F")
        layer = Layer([fixture(service=service, gas=None, future=None,
                               Gebruiksdoel="straatmeubilair") for service in services])
        first = self.process(layer, "2.0")
        second = self.process(first, "2.0")
        for result in (first, second):
            for feature, service in zip(result.getFeatures(), services):
                self.assertEqual(component_values(feature), (5.8,5.8,0.,0.))
                self.assertEqual(feature["service_connection_type_type"], service)
                self.assertIsNone(feature["G_Type"])
                self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))
                self.assertIn("aanname", str(feature["KaderType"]).casefold())
        # A later known rating replaces the assumption without a saved fake
        # 3x25 current or future supply fixing the result to 5.8 A.
        by_id = self.by_source_id(second)
        by_id[1]["service_connection_type_type"] = "3 x 35 A"
        by_id[2]["service_connection_type_type"] = "3 x 55 A"
        resolved = self.by_source_id(self.process(second, "2.0"))
        self.assertEqual(component_values(resolved[1]), (22.,22.,0.,0.))
        self.assertEqual(component_values(resolved[2]), (0.,0.,0.,0.))
        for fid in (1,2):
            self.assertNotIn("aanname", str(resolved[fid]["KaderType"]).casefold())
            self.assertIn(resolved[fid]["Kader20ToekomstigeAansluitwaarde"], (None,""))
        # These are the existing 3.x results, independently read before this
        # change. The 2.0 fallback must not alter their coefficients or charging.
        unchanged = (
            ("straatmeubilair",None,5.8), ("straatmeubilair","Onbekend",5.8),
            ("straatmeubilair","3 fase",5.8), ("straatmeubilair","3 x 35 A",5.8),
            ("straatmeubilair","3 x 55 A",51.), ("oplaadpunt",None,0.),
            ("oplaadpunt","Onbekend",0.), ("oplaadpunt","3 fase",0.),
        )
        for framework in ("3.0","3.2","3.1"):
            with self.subTest(framework=framework):
                original = Layer([fixture(service=service, gas="G40", future=None,
                                          Gebruiksdoel=category, number_of_phases="3 fase", phase="3F")
                                  for category,service,_ in unchanged])
                result = self.process(original, framework)
                self.assertEqual([component_values(f) for f in result.getFeatures()],
                                 [(value,value,0.,0.) for _,_,value in unchanged])
                for feature,(_,service,_) in zip(result.getFeatures(),unchanged):
                    self.assertEqual(feature["service_connection_type_type"], service)
                    self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))
                    self.assertNotIn("aanname", str(feature["KaderType"]).casefold())

    def test_housing_selection_recalculation_passes_street_phase_fields(self):
        # A street point can intersect a selected building. Exercise that
        # production recalculation caller with one deliberately matched shape.
        class Geometry:
            def __init__(self, *_args):
                pass
            def isEmpty(self):
                return False
            def boundingBox(self):
                return None
            def intersects(self, _other):
                return True
            def distance(self, _other):
                return 0.0
        class Rectangle:
            def __init__(self, *_args):
                pass
            def grow(self, _distance):
                pass
        class SpatialIndex:
            def __init__(self):
                self.ids = []
            def addFeature(self, feature):
                self.ids.append(feature.id())
            def intersects(self, _rectangle):
                return self.ids
        path = ROOT / "algorithms" / "woningtype_selectie_herberekenen_tool.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "WoningtypeSelectieHerberekenenAlgorithm"]
        nodes += [node for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "HOUSING_CHOICES"
                          for target in node.targets)]
        scope = dict(self.production)
        scope.update(QgsGeometry=Geometry, QgsRectangle=Rectangle, QgsSpatialIndex=SpatialIndex,
                     QgsProcessingException=RuntimeError, _load_design_module=lambda: self.calc,
                     _workflow_values=lambda: self.context("2.0")[1])
        _compile(nodes, path, scope)
        housing = Layer([{"Woningtype":"vrijstaande woning", "bouwjaar":2010}])
        housing.selectedFeatures = lambda: list(housing.getFeatures())
        points = Layer([fixture(service="Onbekend", gas="G40", future=None,
                                Gebruiksdoel="straatmeubilair", number_of_phases=count)
                        for count in ("1 fase", "3 fase")])
        for layer in (housing, points):
            layer.crs = lambda: "test-crs"
            for feature in layer.getFeatures():
                feature.geometry = lambda: Geometry()
        parameters = {
            "WONINGEN": housing, "AANSLUITINGEN": points,
            "VELD_WONINGTYPE":"Woningtype", "VELD_BOUWJAAR":"bouwjaar",
            "VELD_DOORLAAT":"service_connection_type_type", "VELD_GEBRUIK":"Gebruiksdoel",
            "VELD_GAS":"G_Type", "NIEUW_WONINGTYPE":0,
        }
        algorithm = scope["WoningtypeSelectieHerberekenenAlgorithm"]()
        for _ in range(2):
            result = algorithm.processAlgorithm(parameters, None, Feedback())
            self.assertEqual(result["AANTAL_AANSLUITINGEN"], 2)
            self.assertEqual([component_values(f) for f in points.getFeatures()],
                             [(5.8,5.8,0.,0.), (5.8,5.8,0.,0.)])
            self.assertIn("number_of_phases", points.getFeature(1)["KaderType"])
            for feature, count in zip(points.getFeatures(), ("1 fase","3 fase")):
                self.assertEqual(feature["service_connection_type_type"], "Onbekend")
                self.assertEqual(feature["number_of_phases"], count)
                self.assertIn(feature["Kader20ToekomstigeAansluitwaarde"], (None,""))

    def test_manual_four_values_including_zero_survive_two_recalculations(self):
        for framework in ("2.0", "3.0", "3.2", "3.1"):
            with self.subTest(framework=framework):
                layer = Layer([fixture(gas="G16")])
                expected = (11.125, 12.5, 0., 14.75)
                self.repair(layer, framework, values=expected, gas_category=None,
                            unit_name="Zelf invullen", manual_override=True)
                first = self.process(layer, framework)
                second = self.process(first, framework)
                for result in (first, second):
                    feature = self.by_source_id(result)[1]
                    self.assertEqual(component_values(feature), expected)
                    self.assertEqual((feature["Hoogste Trafo"],feature["Hoogste Kabel"]), (11.125,14.75))
                    self.assertEqual(feature["G_Type"], "G16")

    def test_automatic_20_repair_recalculates_changed_gas_twice(self):
        layer = Layer([fixture(gas="G4"), fixture(service="3 x 160 A", gas="G16", future="3 x 160 A")])
        self.repair(layer, gas_category=None, future_connection=None)
        layer.getFeature(1)["G_Type"] = "G16"
        first = self.process(layer)
        f = self.by_source_id(first)
        self.assertEqual(component_values(f[1]), (138.,65.,138.,65.))
        self.assertEqual(component_values(f[2]), (210.,210.,210.,210.))
        self.assertEqual(f[1]["HerstelCat"], "Zakelijk")
        f[1]["G_Type"] = "G4"
        second = self.process(first)
        f = self.by_source_id(second)
        self.assertEqual(component_values(f[1]), (65.,65.,65.,65.))
        self.assertEqual(component_values(f[2]), (210.,210.,210.,210.))
        self.assertEqual(f[1]["Kader20ToekomstigeAansluitwaarde"], "3 x 63 A")

    def test_existing_frameworks_calculate_each_selected_gas_separately(self):
        for framework in ("3.0", "3.2", "3.1"):
            with self.subTest(framework=framework):
                layer = Layer([fixture(gas=gas) for gas in ("G4", "G10", "G16")])
                self.repair(layer, framework, gas_category=None, unit_name="Huidige aansluitwaarde: 3x63A", unit_key="63")
                self.assertEqual([f["G_Type"] for f in layer.getFeatures()], ["G4","G10","G16"])
                self.assertEqual([component_values(f) for f in layer.getFeatures()],
                                 [(51.,51.,51.,51.), (138.,65.,138.,65.), (138.,65.,138.,65.)])

    def test_existing_framework_saved_preset_and_actual_gas_survive_twice(self):
        for framework in ("3.0", "3.2", "3.1"):
            with self.subTest(framework=framework):
                layer = Layer([fixture(service="3 x 25 A", gas="G4", future=None)])
                self.repair(layer, framework, gas_category=None, unit_name="Huidige aansluitwaarde: 3x63A", unit_key="63")
                self.assertEqual(component_values(layer.getFeature(1)), (51.,51.,51.,51.))
                layer.getFeature(1)["G_Type"] = "G16"
                first = self.process(layer, framework)
                f = self.by_source_id(first)[1]
                self.assertEqual(component_values(f), (138.,65.,138.,65.))
                self.assertEqual(f["service_connection_type_type"], "3 x 25 A")
                self.assertEqual(f["HerstelAansluitwaarde"], "3 x 63 A")
                f["G_Type"] = "G4"
                second = self.process(first, framework)
                self.assertEqual(component_values(self.by_source_id(second)[1]), (51.,51.,51.,51.))

    def test_legacy_business_current_choice_survives_bag_recalculation(self):
        for framework in ("3.0", "3.2", "3.1"):
            with self.subTest(framework=framework):
                layer = Layer([fixture(
                    service="Verblijfsobject", gas="G16", future=None,
                    HerstelCat="Zakelijk", HerstelType="Huidige aansluitwaarde: 3x63A",
                    HerstelHandmatig="0", KaderVersie=framework,
                )])
                self.assertEqual(self.preview(layer, framework), (138.,65.,138.,65.))
                first = self.process(layer, framework)
                f = self.by_source_id(first)[1]
                self.assertEqual(component_values(f), (138.,65.,138.,65.))
                self.assertEqual(f["service_connection_type_type"], "Verblijfsobject")
                self.assertEqual(f["HerstelAansluitwaarde"], "3 x 63 A")
                f["G_Type"] = "G4"
                second = self.process(first, framework)
                self.assertEqual(component_values(self.by_source_id(second)[1]), (51.,51.,51.,51.))

    def test_legacy_20_business_choice_uses_original_framework(self):
        # Old versions stored this label even when the 2.0 UI meant FUTURE.
        # KaderVersie is the retained provenance for that older project.
        layer = Layer([fixture(
            service="Verblijfsobject", gas="G16", future=None,
            HerstelCat="Zakelijk", HerstelType="Huidige aansluitwaarde: 3x63A",
            HerstelHandmatig="0", KaderVersie="2.0",
        )])
        # This older output has only its saved choice, no future-value column.
        # Saving a preserve action must materialize that future before replacing
        # the old choice with the new 'keep existing' metadata.
        future_field = "Kader20ToekomstigeAansluitwaarde"
        layer._fields.pop(layer._fields.lookupField(future_field))
        layer.getFeature(1).values.pop(future_field)
        self.assertEqual(layer.fields().lookupField(future_field), -1)
        self.assertEqual(self.preview(layer, "2.0"), (65.,65.,65.,65.))
        self.repair(layer, "2.0", gas_category=None,
                    unit_name="Bestaande toekomstige aansluitwaarde per aansluiting behouden",
                    unit_key=self.production["ZeroCurrentPage"].KEEP_EXISTING_UNIT)
        self.assertGreaterEqual(layer.fields().lookupField(future_field), 0)
        self.assertEqual(layer.getFeature(1)[future_field], "3 x 63 A")
        self.assertEqual(layer.getFeature(1)["G_Type"], "G16")
        first = self.process(layer, "2.0")
        f = self.by_source_id(first)[1]
        self.assertEqual(component_values(f), (65.,65.,65.,65.))
        self.assertEqual(f["Kader20ToekomstigeAansluitwaarde"], "3 x 63 A")
        f["G_Type"] = ">G25"
        second = self.process(first, "2.0")
        self.assertEqual(component_values(self.by_source_id(second)[1]), (210.,65.,210.,65.))

    def test_switch_to_32_keeps_current_service_separate_from_20_future(self):
        layer = Layer([fixture(service="3 x 63 A", gas="G10", future=None)])
        self.repair(layer, "2.0", gas_category=None, future_connection="3 x 160 A",
                    unit_name="Toekomstige aansluitwaarde: 3x160A", unit_key="160")
        self.assertEqual(component_values(layer.getFeature(1)), (138.,138.,138.,138.))
        self.assertEqual(self.preview(layer, "3.2"), (138.,65.,138.,65.))
        first = self.process(layer, "3.2")
        second = self.process(first, "3.2")
        for result in (first, second):
            f = self.by_source_id(result)[1]
            self.assertEqual(component_values(f), (138.,65.,138.,65.))
            self.assertEqual(f["service_connection_type_type"], "3 x 63 A")
            self.assertEqual(f["Kader20ToekomstigeAansluitwaarde"], "3 x 160 A")
        self.repair(layer, "3.2", gas_category=None,
                    unit_key=self.production["ZeroCurrentPage"].KEEP_EXISTING_UNIT)
        f = layer.getFeature(1)
        self.assertEqual(component_values(f), (138.,65.,138.,65.))
        self.assertEqual(f["KaderVersie"], "3.2")
        self.assertNotIn("2.0", str(f["KaderType"]))

    def test_switch_to_20_does_not_promote_a_current_preset_to_future(self):
        layer = Layer([fixture(service="3 x 50 A", gas="G4", future=None)])
        self.repair(layer, "3.2", gas_category=None,
                    unit_name="Huidige aansluitwaarde: 3x63A", unit_key="63")
        self.assertEqual(component_values(layer.getFeature(1)), (51.,51.,51.,51.))
        self.assertEqual(self.preview(layer, "2.0"), (44.,44.,44.,44.))
        first = self.process(layer, "2.0")
        second = self.process(first, "2.0")
        for result in (first, second):
            f = self.by_source_id(result)[1]
            self.assertEqual(component_values(f), (44.,44.,44.,44.))
            self.assertEqual(f["service_connection_type_type"], "3 x 50 A")
            self.assertIn(f["Kader20ToekomstigeAansluitwaarde"], (None,""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
