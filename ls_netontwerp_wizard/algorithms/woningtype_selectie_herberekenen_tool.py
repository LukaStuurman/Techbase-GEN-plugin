from __future__ import annotations

import importlib.util
import json
from ls_netontwerp_wizard.current_edit_metadata import clear_current_choices
from pathlib import Path

from ls_netontwerp_wizard.bag_current_rules import (
    NEW_BUILD_FIELD, NEW_BUILD_TYPE_FIELD, NEW_BUILD_TYPE_3, is_new_build_flag,
)

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorDataProvider,
    QgsWkbTypes,
)


HOUSING_CHOICES = (
    ("Vrijstaande woning", "vrijstaande woning"),
    ("Twee-onder-een-kap", "twee-onder-een-kap"),
    ("Appartement", "appartement"),
    ("Rijtjeswoning / geschakeld", "tussenwoning/geschakeld"),
    ("Hoekwoning", "hoekwoning"),
    ("Onbekend / overig", "onbekend"),
)


def _load_design_module():
    path = Path(__file__).resolve().parent / (
        "Ontwersptroom TRAFO, KABEL & OPWEK voor XML KADER 2026 V5.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ls_netontwerp_design_current_for_housing_edit", path
    )
    if spec is None or spec.loader is None:
        raise QgsProcessingException("De ontwerpstroomberekening kon niet worden geladen")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_values():
    project = QgsProject.instance()
    state_file = str(project.readEntry("LSNetontwerp", "state_file", "")[0]).strip()
    if not state_file or not Path(state_file).exists():
        return {}
    try:
        state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return dict(state.get("values") or {})


def _configurations(values, module):
    def raw(key, default_name):
        configured = values.get(key)
        return list(configured) if configured else list(getattr(module, default_name))

    def parse_woon(items):
        result = {}
        for index in range(0, len(items), 2):
            try:
                result[str(items[index]).lower()] = float(items[index + 1])
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def parse_amp(items):
        result = []
        for index in range(0, len(items), 4):
            try:
                result.append(
                    {
                        "min": float(items[index]),
                        "max": float(items[index + 1]),
                        "fix": float(items[index + 2]),
                        "fac": float(items[index + 3]),
                    }
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def parse_types(items):
        result = {}
        for index in range(0, len(items), 6):
            try:
                result[int(float(items[index]))] = {
                    "fixed": float(items[index + 2]),
                    "use_amp": bool(float(items[index + 3])),
                    "use_woon": bool(float(items[index + 4])),
                    "use_straat": bool(float(items[index + 5])),
                }
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def parse_triplets(items):
        result = []
        for index in range(0, len(items), 3):
            try:
                result.append(
                    {
                        "min": float(items[index]),
                        "max": float(items[index + 1]),
                        "val": float(items[index + 2]),
                    }
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def parse_gas(items):
        result = []
        for index in range(0, len(items), 3):
            try:
                result.append(
                    {
                        "cat": str(items[index]),
                        "max_el": float(items[index + 1]),
                        "advies": float(items[index + 2]),
                    }
                )
            except (IndexError, TypeError, ValueError):
                continue
        result.sort(key=lambda row: row["max_el"])
        return result

    def parse_regex(items):
        result = []
        for index in range(0, len(items), 2):
            try:
                result.append((str(items[index]), int(float(items[index + 1]))))
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def parse_keywords(items):
        result = []
        for index in range(0, len(items), 2):
            try:
                words = [
                    word.strip().lower()
                    for word in str(items[index]).split(",")
                    if word.strip()
                ]
                result.append((words, int(float(items[index + 1]))))
            except (IndexError, TypeError, ValueError):
                continue
        return result

    woon = parse_woon(raw("matrix_woonhuis", "DEF_WOONHUIS"))
    woon_2022 = parse_woon(raw("matrix_woonhuis_2022", "DEF_WOONHUIS_2022"))
    woon_kabel = parse_woon(raw("matrix_woonhuis_kabel", "DEF_WOONHUIS_KABEL"))
    woon_kabel_2022 = parse_woon(
        raw("matrix_woonhuis_kabel_2022", "DEF_WOONHUIS_KABEL_2022")
    )
    opwek = parse_woon(raw("matrix_woonhuis_opwek", "DEF_WOONHUIS_OPWEK"))
    opwek_kabel = parse_woon(
        raw("matrix_woonhuis_opwek_kabel", "DEF_WOONHUIS_OPWEK_KABEL")
    )
    try:
        zero_ids = [
            int(item)
            for item in str(values.get("opwek_zero_ids", "4, 8, 9")).split(",")
            if item.strip().isdigit()
        ]
    except (TypeError, ValueError):
        zero_ids = [4, 8, 9]
    common = {
        "FRAMEWORK_VERSION": str(values.get("design_framework", "3.0")),
        "NET_LEVEL": "trafo",
        "WOONHUIS": woon,
        "WOONHUIS_2022": woon_2022,
        "AMP_GLOBAL": parse_amp(raw("matrix_amp", "DEF_AMP_GLOBAL")),
        "TYPES": parse_types(raw("matrix_type", "DEF_TYPE_CFG")),
        "STRAAT": parse_triplets(raw("matrix_straat", "DEF_STRAAT")),
        "LAAD": parse_triplets(raw("matrix_laad", "DEF_LAAD")),
        "GAS_ADVIES": parse_gas(raw("matrix_gas", "DEF_GAS_ADVIES")),
        "REGEX_MAP": parse_regex(raw("matrix_regex", "DEF_REGEX")),
        "GEBRUIKS_MAP": parse_keywords(raw("matrix_keywords", "DEF_KEYWORDS")),
        "OPWEK_RULES": {
            "zero_ids": zero_ids,
            "zero_text": str(values.get("opwek_zero_text", "appartement"))
            .lower()
            .strip(),
        },
        "DEFAULTS": {
            "laad_fallback": float(values.get("fallback_laad", 3.7)),
            "bouwjaar_grens": int(values.get("building_year_limit", 2022)),
            "limit_fase": int(values.get("phase_limit", 3)),
            "limit_amp": int(values.get("amp_limit", 40)),
        },
    }
    cable = dict(common)
    cable["NET_LEVEL"] = "kabel"
    cable["WOONHUIS"] = woon_kabel
    cable["WOONHUIS_2022"] = woon_kabel_2022
    cable["LAAD"] = parse_triplets(raw("matrix_laad_kabel", "DEF_LAAD_KABEL"))
    cable["GAS_ADVIES"] = parse_gas(
        raw("matrix_gas_kabel", "DEF_GAS_ADVIES_KABEL")
    )
    return common, cable, opwek, opwek_kabel


class WoningtypeSelectieHerberekenenAlgorithm(QgsProcessingAlgorithm):
    WONINGEN = "WONINGEN"
    AANSLUITINGEN = "AANSLUITINGEN"
    VELD_WONINGTYPE = "VELD_WONINGTYPE"
    VELD_BOUWJAAR = "VELD_BOUWJAAR"
    VELD_DOORLAAT = "VELD_DOORLAAT"
    VELD_GEBRUIK = "VELD_GEBRUIK"
    VELD_GAS = "VELD_GAS"
    NIEUW_WONINGTYPE = "NIEUW_WONINGTYPE"
    AANTAL_WONINGEN = "AANTAL_WONINGEN"
    AANTAL_AANSLUITINGEN = "AANTAL_AANSLUITINGEN"

    def tr(self, text):
        return QCoreApplication.translate("LSNetontwerp", text)

    def createInstance(self):
        return WoningtypeSelectieHerberekenenAlgorithm()

    def name(self):
        return "woningtype_selectie_herberekenen"

    def displayName(self):
        return self.tr("Woningtype aanpassen en ontwerpstroom herberekenen (selectie)")

    def group(self):
        return self.tr("LS Netontwerp")

    def groupId(self):
        return "ls_netontwerp"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    @staticmethod
    def _default_layers():
        project = QgsProject.instance()
        values = _workflow_values()
        woningtype_name = str(
            values.get("field_building_type", "Woningtype")
        ).casefold()
        ordered = list(project.layerTreeRoot().layerOrder())
        housing = []
        points = []
        for order, layer in enumerate(ordered):
            if not hasattr(layer, "fields"):
                continue
            names = {field.name().casefold() for field in layer.fields()}
            geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
            if geometry_type == QgsWkbTypes.PolygonGeometry and woningtype_name in names:
                housing.append(
                    (-int(layer.selectedFeatureCount() > 0), order, layer)
                )
            if geometry_type == QgsWkbTypes.PointGeometry and {
                "hoogste trafo",
                "hoogste kabel",
            }.issubset(names):
                points.append(
                    (
                        -int(
                            bool(
                                layer.customProperty(
                                    "LSNetontwerp/review_current_layer", False
                                )
                            )
                        ),
                        order,
                        layer,
                    )
                )
        housing_layer = min(housing, key=lambda item: item[:2])[2] if housing else None
        point_layer = min(points, key=lambda item: item[:2])[2] if points else None
        return housing_layer, point_layer

    def preprocessParameters(self, parameters):
        prepared = dict(super().preprocessParameters(parameters))
        housing, points = self._default_layers()
        if prepared.get(self.WONINGEN) in (None, "") and housing is not None:
            prepared[self.WONINGEN] = housing.id()
        if prepared.get(self.AANSLUITINGEN) in (None, "") and points is not None:
            prepared[self.AANSLUITINGEN] = points.id()
        return prepared

    def initAlgorithm(self, config=None):
        values = _workflow_values()
        housing, points = self._default_layers()
        housing_parameter = QgsProcessingParameterVectorLayer(
            self.WONINGEN,
            self.tr("Woningtypen BAG/3DBAG (gebruik huidige selectie)"),
            [QgsProcessing.TypeVectorPolygon],
        )
        if housing is not None:
            housing_parameter.setDefaultValue(housing.id())
        self.addParameter(housing_parameter)
        points_parameter = QgsProcessingParameterVectorLayer(
            self.AANSLUITINGEN,
            self.tr("LS-aansluitingen ontwerpstroom"),
            [QgsProcessing.TypeVectorPoint],
        )
        if points is not None:
            points_parameter.setDefaultValue(points.id())
        self.addParameter(points_parameter)
        for name, label, parent, default in (
            (
                self.VELD_WONINGTYPE,
                "Kolom woningtype",
                self.WONINGEN,
                values.get("field_building_type", "Woningtype"),
            ),
            (
                self.VELD_BOUWJAAR,
                "Kolom bouwjaar",
                self.WONINGEN,
                values.get("field_build_year", "bouwjaar"),
            ),
            (
                self.VELD_DOORLAAT,
                "Kolom doorlaatwaarde",
                self.AANSLUITINGEN,
                values.get("field_passthrough", "service_connection_type_type"),
            ),
            (
                self.VELD_GEBRUIK,
                "Kolom gebruiksdoel",
                self.AANSLUITINGEN,
                values.get("field_usage", "Gebruiksdoel"),
            ),
            (
                self.VELD_GAS,
                "Kolom gascategorie",
                self.AANSLUITINGEN,
                values.get("field_gas", "G_Type"),
            ),
        ):
            self.addParameter(
                QgsProcessingParameterField(
                    name, self.tr(label), parentLayerParameterName=parent, defaultValue=default
                )
            )
        default_choice = 0
        if housing is not None and housing.selectedFeatureCount() > 0:
            current_values = {
                str(feature[values.get("field_building_type", "Woningtype")] or "")
                .strip()
                .casefold()
                for feature in housing.selectedFeatures()
            }
            if len(current_values) == 1:
                current = next(iter(current_values))
                for index, (_label, stored) in enumerate(HOUSING_CHOICES):
                    if current == stored.casefold():
                        default_choice = index
                        break
        self.addParameter(
            QgsProcessingParameterEnum(
                self.NIEUW_WONINGTYPE,
                self.tr("Nieuw woningtype voor geselecteerde BAG-panden"),
                options=[label for label, _stored in HOUSING_CHOICES],
                defaultValue=default_choice,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.AANTAL_WONINGEN, self.tr("Aantal aangepaste BAG-panden")
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.AANTAL_AANSLUITINGEN,
                self.tr("Aantal opnieuw berekende LS-aansluitingen"),
            )
        )

    @staticmethod
    def _field_index(layer, field_name):
        index = layer.fields().lookupField(field_name)
        if index < 0:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' mist de kolom '{field_name}'"
            )
        return index

    def processAlgorithm(self, parameters, context, feedback):
        housing = self.parameterAsVectorLayer(parameters, self.WONINGEN, context)
        points = self.parameterAsVectorLayer(parameters, self.AANSLUITINGEN, context)
        if housing is None or not housing.isValid() or points is None or not points.isValid():
            raise QgsProcessingException("Kies de woningtypen- en ontwerpstroomlaag")
        selected = list(housing.selectedFeatures())
        if not selected:
            raise QgsProcessingException(
                "Selecteer eerst één of meer panden in 'Woningtypen BAG/3DBAG'"
            )
        if housing.isEditable() or points.isEditable():
            raise QgsProcessingException(
                "Sla bestaande bewerkingen in de woning- en aansluitingenlaag eerst op"
            )

        woning_field = self.parameterAsString(parameters, self.VELD_WONINGTYPE, context)
        bouwjaar_field = self.parameterAsString(parameters, self.VELD_BOUWJAAR, context)
        doorlaat_field = self.parameterAsString(parameters, self.VELD_DOORLAAT, context)
        gebruik_field = self.parameterAsString(parameters, self.VELD_GEBRUIK, context)
        gas_field = self.parameterAsString(parameters, self.VELD_GAS, context)
        woning_index = self._field_index(housing, woning_field)
        bouwjaar_index = self._field_index(housing, bouwjaar_field)
        doorlaat_index = self._field_index(points, doorlaat_field)
        gebruik_index = self._field_index(points, gebruik_field)
        gas_index = self._field_index(points, gas_field)
        output_names = (
            "Ontwerpstroom",
            "Ontwerpstroom kabel",
            "Opwek ontwerpstroom",
            "Kabel opwek ontwerpstroom",
            "Hoogste Trafo",
            "Hoogste Kabel",
            "Gevonden_Woningtype",
            "Gevonden_Bouwjaar",
        )
        output_indices = {
            name: self._field_index(points, name) for name in output_names
        }
        if not housing.dataProvider().capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
            raise QgsProcessingException("De woningtypenlaag is niet schrijfbaar")
        if not points.dataProvider().capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
            raise QgsProcessingException("De ontwerpstroomlaag is niet schrijfbaar")

        choice = self.parameterAsEnum(parameters, self.NIEUW_WONINGTYPE, context)
        new_type = HOUSING_CHOICES[choice][1]
        module = _load_design_module()
        values = _workflow_values()
        std_config, cable_config, opwek_table, opwek_cable_table = _configurations(
            values, module
        )
        one_phase = bool(values.get("one_phase_exception", True))
        apartment_default = bool(values.get("default_apartment", True))

        index = QgsSpatialIndex()
        selected_by_id = {}
        for feature in selected:
            index.addFeature(feature)
            selected_by_id[int(feature.id())] = feature
        transform = None
        if points.crs() != housing.crs():
            transform = QgsCoordinateTransform(
                points.crs(), housing.crs(), QgsProject.instance()
            )

        point_changes = {}
        request = QgsFeatureRequest()
        for point in points.getFeatures(request):
            if module.is_bag_object(point[doorlaat_index]) and not module.has_residential_usage(point[gebruik_index]):
                # Non-residential BAG objects are categorized by the user, not
                # by the housing type of a shared building.
                continue
            geometry = QgsGeometry(point.geometry())
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            search_rectangle = QgsRectangle(geometry.boundingBox())
            search_rectangle.grow(1.0)
            matched = None
            for feature_id in index.intersects(search_rectangle):
                candidate = selected_by_id.get(int(feature_id))
                if candidate is None:
                    continue
                candidate_geometry = candidate.geometry()
                if candidate_geometry.intersects(geometry) or candidate_geometry.distance(geometry) <= 1.0:
                    matched = candidate
                    break
            if matched is None:
                continue
            bouwjaar = matched[bouwjaar_index]
            doorlaat = point[doorlaat_index]
            gebruik = point[gebruik_index]
            gas = point[gas_index]
            if new_type == "onbekend":
                # Expliciete huishoudelijke correctie gebruikt de onbekend-rij,
                # ook wanneer de bron geen doorlaatwaarde bevat.
                gebruik = "woonfunctie" if module.is_bag_object(doorlaat) else "woonhuis"
                if not module.is_bag_object(doorlaat) and module.parse_doorlaat(doorlaat)[0] == 0:
                    doorlaat = "3 x 25 A"
            new_build_index = points.fields().lookupField(NEW_BUILD_FIELD)
            new_build_vbo = (module.is_bag_object(doorlaat) and new_build_index >= 0
                             and is_new_build_flag(point[new_build_index]))
            effective_bouwjaar = (max(module.parse_bouwjaar(bouwjaar), int(std_config["DEFAULTS"]["bouwjaar_grens"]))
                                  if new_build_vbo else bouwjaar)
            kader20_index = point.fields().lookupField("Kader20Type")
            kader20_type = (
                str(point[kader20_index]).strip()
                if kader20_index >= 0 and point[kader20_index] not in (None, "", "NULL")
                else None
            )
            normal = module.calculate_ontwerpstroom(
                doorlaat,
                gebruik,
                new_type,
                effective_bouwjaar,
                gas,
                std_config,
                point.id(),
                feedback,
                one_phase,
                apartment_default,
                kader20_type,
            )
            cable = module.calculate_ontwerpstroom(
                doorlaat,
                gebruik,
                new_type,
                effective_bouwjaar,
                gas,
                cable_config,
                point.id(),
                feedback,
                one_phase,
                apartment_default,
                kader20_type,
            )
            generation = module.calculate_opwek_ontwerpstroom(
                doorlaat, gebruik, new_type, gas, opwek_table,
                std_config, normal, one_phase, effective_bouwjaar, kader20_type,
            )
            generation_cable = module.calculate_opwek_ontwerpstroom(
                doorlaat, gebruik, new_type, gas, opwek_cable_table,
                cable_config, cable, one_phase, effective_bouwjaar, kader20_type,
            )
            point_changes[int(point.id())] = {
                output_indices["Ontwerpstroom"]: float(normal),
                output_indices["Ontwerpstroom kabel"]: float(cable),
                output_indices["Opwek ontwerpstroom"]: float(generation),
                output_indices["Kabel opwek ontwerpstroom"]: float(generation_cable),
                output_indices["Hoogste Trafo"]: float(max(normal, generation)),
                output_indices["Hoogste Kabel"]: float(max(cable, generation_cable)),
                output_indices["Gevonden_Woningtype"]: new_type,
                output_indices["Gevonden_Bouwjaar"]: str(bouwjaar or ""),
            }
            # Keep the source framework/type visible after a housing correction.
            version_index = points.fields().lookupField("KaderVersie")
            profile_index = points.fields().lookupField("KaderType")
            if version_index >= 0:
                point_changes[int(point.id())][version_index] = str(
                    std_config.get("FRAMEWORK_VERSION", "3.0")
                )
            if profile_index >= 0:
                type_label = ""
                if std_config.get("FRAMEWORK_VERSION") == "2.0":
                    category = module.map_gebruiksdoel(gebruik, new_type, std_config)
                    phases, amps = module.parse_doorlaat(doorlaat)
                    _amps, type_label, _warning = module.kader_20.current(
                        "trafo", category, new_type, effective_bouwjaar,
                        phases, amps, explicit_type=kader20_type,
                        new_build_year=std_config["DEFAULTS"]["bouwjaar_grens"],
                    )
                point_changes[int(point.id())][profile_index] = type_label
            # Keep the Kader Type 3 label synchronized when housing is edited.
            type_index = points.fields().lookupField(NEW_BUILD_TYPE_FIELD)
            if new_build_vbo and type_index >= 0:
                point_changes[int(point.id())][type_index] = (
                    NEW_BUILD_TYPE_3 if "appartement" not in new_type.casefold() else ""
                )
            # A fresh pand calculation replaces the previous manual preset.
            for field in ("HerstelCat", "HerstelType", "HerstelHandmatig"):
                metadata_index = points.fields().lookupField(field)
                if metadata_index >= 0:
                    point_changes[int(point.id())][metadata_index] = ""

        housing_changes = {
            int(feature.id()): {woning_index: new_type} for feature in selected
        }
        if not housing.dataProvider().changeAttributeValues(housing_changes):
            raise QgsProcessingException("Het nieuwe woningtype kon niet worden opgeslagen")
        if point_changes and not points.dataProvider().changeAttributeValues(point_changes):
            raise QgsProcessingException(
                "Het woningtype is aangepast, maar de ontwerpstroom kon niet worden opgeslagen"
            )
        clear_current_choices(points, point_changes)
        housing.triggerRepaint()
        points.triggerRepaint()
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()
        feedback.pushInfo(
            f"{len(selected)} BAG-pand(en) gewijzigd naar "
            f"'{HOUSING_CHOICES[choice][0]}'; "
            f"{len(point_changes)} aansluiting(en) opnieuw berekend."
        )
        return {
            self.AANTAL_WONINGEN: len(selected),
            self.AANTAL_AANSLUITINGEN: len(point_changes),
        }
