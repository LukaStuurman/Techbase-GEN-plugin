# -*- coding: utf-8 -*-

"""
***************************************************************************
* *
* Woningtypering BAG (PDOK WFS + 3DBAG LoD 2.2, snel)                    *
* *
***************************************************************************
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsFeatureRequest,
                       QgsSpatialIndex,
                       QgsField,
                       QgsFeature,
                       QgsGeometry,
                       QgsRectangle,
                       QgsProject,
                       QgsCoordinateTransform,
                       QgsCategorizedSymbolRenderer,
                       QgsRendererCategory,
                       QgsSymbol,
                       QgsVectorLayer,
                       QgsProcessingException)
import concurrent.futures
import math

from ls_netontwerp_wizard.ahn_roof_contact import AhnRoofContact


PDOK_BAG_WFS_URL = "https://service.pdok.nl/kadaster/bag/wfs/v2_0"
PDOK_BAG_TYPENAME = "bag:pand"
PDOK_BAG_CRS_AUTHID = "EPSG:28992"
# PDOK's WFS capabilities bbox is ruim op zee; deze RD-extent dekt de BAG-panden op land zonder veel lege noordelijke tegels.
PDOK_FULL_NL_EXTENT = QgsRectangle(-50000.0, 246000.0, 297000.0, 630000.0)

BAG3D_WFS_URL = "https://data.3dbag.nl/api/BAG3D/wfs"
BAG3D_LOD22_TYPENAME = "BAG3D:lod22"
BAG3D_IDENT_PREFIX = "NL.IMBAG.Pand."
BAG3D_TOP_HEIGHT_FIELD = "b3_h_max"

WONINGTYPE_HOEK = "hoekwoning"
WONINGTYPE_TUSSEN = "tussenwoning/geschakeld"
WONINGTYPE_TWEE_KAP = "twee-onder-een-kap"
WONINGTYPE_VRIJSTAAND = "vrijstaande woning"
RIJTJES_WONINGTYPES = {WONINGTYPE_HOEK, WONINGTYPE_TUSSEN}

WONINGTYPE_STYLE = [
    (WONINGTYPE_VRIJSTAAND, "Vrijstaande woning", "#8B0000"),
    (WONINGTYPE_TWEE_KAP, "Twee-onder-een-kap", "#8EC9F0"),
    ("appartement", "Appartement", "#FF99CC"),
    (WONINGTYPE_TUSSEN, "Rijtjeswoning", "#90EE90"),
    (WONINGTYPE_HOEK, "Hoekwoning", "#006400"),
    ("", "Overige panden", "#D9D9D9"),
]

EXCLUDED_STATUSES = {
    "niet gerealiseerd",
    "niet gerealiseerd pand",
    "pand gesloopt",
}


def safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_excluded_status(value):
    return str(value or "").strip().lower() in EXCLUDED_STATUSES


def normalize_bag_identification(value):
    bag_id = str(value or "").strip()
    if bag_id.startswith(BAG3D_IDENT_PREFIX):
        bag_id = bag_id[len(BAG3D_IDENT_PREFIX):]
    return bag_id


def resolve_field(fields, preferred_name):
    idx = fields.indexOf(preferred_name)
    if idx >= 0:
        return preferred_name

    preferred_lower = preferred_name.lower()
    for field in fields:
        if field.name().lower() == preferred_lower:
            return field.name()

    raise QgsProcessingException(f"Veld '{preferred_name}' ontbreekt in de laag.")


def quote_expression_field(field_name):
    return '"' + field_name.replace('"', '""') + '"'


def format_rect(rect):
    return (
        f"{rect.xMinimum():.2f}, {rect.yMinimum():.2f}, "
        f"{rect.xMaximum():.2f}, {rect.yMaximum():.2f}"
    )


def make_woningtype_symbol(layer, fill_color):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(QColor(fill_color))

    if symbol.symbolLayerCount() > 0:
        symbol_layer = symbol.symbolLayer(0)
        if hasattr(symbol_layer, 'setStrokeColor'):
            symbol_layer.setStrokeColor(QColor("#333333"))
        if hasattr(symbol_layer, 'setStrokeWidth'):
            symbol_layer.setStrokeWidth(0.15)

    return symbol


def apply_woningtype_symbology(layer, field_name):
    if layer is None or not layer.isValid():
        return False
    if layer.fields().indexOf(field_name) < 0:
        return False

    categories = []
    for value, label, fill_color in WONINGTYPE_STYLE:
        categories.append(
            QgsRendererCategory(
                value,
                make_woningtype_symbol(layer, fill_color),
                label
            )
        )

    renderer = QgsCategorizedSymbolRenderer(field_name, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return True


def top_geometries_connected(geoms_a, geoms_b, tolerance):
    if not geoms_a or not geoms_b:
        return False

    for geom_a in geoms_a:
        if geom_a is None or geom_a.isEmpty():
            continue

        for geom_b in geoms_b:
            if geom_b is None or geom_b.isEmpty():
                continue
            if geom_a.intersects(geom_b):
                return True
            if geom_a.distance(geom_b) <= tolerance:
                return True

    return False


def count_connected_top_neighbors(item, neighbor_ids, local_map, tolerance):
    top_geoms = item.get('lod22_top_geoms', [])
    ahn_links = item.get('ahn_roof_links', {})
    checked_top_neighbors = 0
    connected_top_neighbors = 0
    for neighbor_id in neighbor_ids:
        if neighbor_id in ahn_links:
            checked_top_neighbors += 1
            if ahn_links[neighbor_id]:
                connected_top_neighbors += 1
            continue
        neighbor = local_map[neighbor_id]
        neighbor_top_geoms = neighbor.get('lod22_top_geoms', [])
        if not top_geoms or not neighbor_top_geoms:
            continue
        checked_top_neighbors += 1
        if top_geometries_connected(top_geoms, neighbor_top_geoms, tolerance):
            connected_top_neighbors += 1
    return checked_top_neighbors, connected_top_neighbors


def typed_neighbors(item, local_map, woningtypes):
    neighbors = []
    for neighbor_id in item.get('neighbors', []):
        neighbor = local_map.get(neighbor_id)
        if neighbor and neighbor.get('woningtype') in woningtypes:
            neighbors.append(neighbor)
    return neighbors


def row_type_from_neighbors(row_neighbor_count, fallback):
    if row_neighbor_count <= 0:
        return fallback
    if row_neighbor_count == 1:
        return WONINGTYPE_HOEK
    return WONINGTYPE_TUSSEN


def apply_row_sequence_corrections(tile_data, local_map):
    for item in tile_data:
        if 'base_woningtype' not in item:
            item['base_woningtype'] = item.get('woningtype', "")

    # Rij-kandidaten die niet meer aan een rij-kandidaat grenzen maar wel aan
    # tweekappers liggen, horen bij de tweekap-groep.
    changes = []
    for item in tile_data:
        if item.get('woningtype') not in RIJTJES_WONINGTYPES:
            continue

        row_neighbors = typed_neighbors(item, local_map, RIJTJES_WONINGTYPES)
        two_kap_neighbors = typed_neighbors(item, local_map, {WONINGTYPE_TWEE_KAP})

        if item.get('woningtype') == WONINGTYPE_HOEK and not row_neighbors and two_kap_neighbors:
            changes.append((item, WONINGTYPE_TWEE_KAP))
        elif (
            item.get('woningtype') == WONINGTYPE_TUSSEN
            and not row_neighbors
            and len(two_kap_neighbors) >= 2
        ):
            changes.append((item, WONINGTYPE_TWEE_KAP))

    for item, woningtype in changes:
        item['woningtype'] = woningtype

    # Als er nog een rij-kandidaat naast ligt, is het pand onderdeel van een rij.
    # Eindes worden hoekwoningen; panden met meerdere rij-buren blijven tussenwoning.
    changed = True
    while changed:
        changed = False
        changes = []

        for item in tile_data:
            if item.get('base_woningtype') not in RIJTJES_WONINGTYPES:
                continue
            if item.get('woningtype') != WONINGTYPE_TWEE_KAP:
                continue

            row_neighbors = typed_neighbors(item, local_map, RIJTJES_WONINGTYPES)
            if row_neighbors:
                changes.append((
                    item,
                    row_type_from_neighbors(
                        len(row_neighbors),
                        item.get('base_woningtype', WONINGTYPE_HOEK)
                    )
                ))

        for item, woningtype in changes:
            if item.get('woningtype') != woningtype:
                item['woningtype'] = woningtype
                changed = True

    for item in tile_data:
        if item.get('base_woningtype') not in RIJTJES_WONINGTYPES:
            continue
        if item.get('woningtype') not in RIJTJES_WONINGTYPES:
            continue

        row_neighbors = typed_neighbors(item, local_map, RIJTJES_WONINGTYPES)
        if row_neighbors:
            item['woningtype'] = row_type_from_neighbors(
                len(row_neighbors),
                item.get('base_woningtype', WONINGTYPE_HOEK)
            )

    # EXTRA CORRECTIE: Hoekwoningen die grenzen aan een twee-onder-een-kap woning
    # én aan een andere rijtjeswoning, worden geclassificeerd als tussenwoning (rijtjeswoning).
    # Tevens wordt de direct aangrenzende twee-onder-een-kap woning omgezet naar een hoekwoning.
    twee_kap_to_hoek = []
    for item in tile_data:
        if item.get('woningtype') == WONINGTYPE_HOEK:
            row_neighbors = typed_neighbors(item, local_map, RIJTJES_WONINGTYPES)
            two_kap_neighbors = typed_neighbors(item, local_map, {WONINGTYPE_TWEE_KAP})
            if row_neighbors and two_kap_neighbors:
                item['woningtype'] = WONINGTYPE_TUSSEN
                for tk_neighbor in two_kap_neighbors:
                    twee_kap_to_hoek.append(tk_neighbor)

    for tk_item in twee_kap_to_hoek:
        tk_item['woningtype'] = WONINGTYPE_HOEK


def apply_detached_carport_corrections(tile_data, local_map, tolerance):
    for item in tile_data:
        if item.get('woningtype') != WONINGTYPE_TWEE_KAP:
            continue

        checked_top_neighbors, connected_top_neighbors = count_connected_top_neighbors(
            item, item.get('neighbors', []), local_map, tolerance
        )
        if checked_top_neighbors >= 1 and connected_top_neighbors == 0:
            item['woningtype'] = WONINGTYPE_VRIJSTAAND


def is_geometric_neighbor(geom_a, geom_b, tolerance):
    if geom_a.intersects(geom_b):
        return True
    return geom_a.distance(geom_b) <= tolerance


def build_neighbor_lists(tile_data, spatial_index, local_map, tolerance):
    for item in tile_data:
        item['neighbors'] = []
        if item.get('ignore_neighbor'):
            continue

        geom = item['geom']
        bbox = geom.boundingBox()
        bbox.grow(tolerance)

        for candidate_id in spatial_index.intersects(bbox):
            if candidate_id == item['work_id']:
                continue

            candidate = local_map.get(candidate_id)
            if candidate is None or candidate.get('ignore_neighbor'):
                continue

            if is_geometric_neighbor(geom, candidate['geom'], tolerance):
                item['neighbors'].append(candidate_id)


def calculate_tile_worker(tile_data, tile_rect_coords, buffer_dist):
    """
    Snellere worker: bouwt alle buurrelaties een keer en hergebruikt die
    voor hoekwoning-, rijtjeshuis- en tweekap-correcties.
    """
    tile_rect = QgsRectangle(tile_rect_coords[0], tile_rect_coords[1],
                             tile_rect_coords[2], tile_rect_coords[3])

    features_for_index = []
    local_map = {}

    for work_id, item in enumerate(tile_data):
        item['work_id'] = work_id

        feat = QgsFeature(work_id)
        geom = item['geom']
        feat.setGeometry(geom)
        features_for_index.append(feat)

        if geom.isEmpty():
            is_inside = False
        else:
            c = geom.centroid()
            if c.isEmpty():
                is_inside = False
            else:
                is_inside = tile_rect.contains(c.asPoint())

        item['inside_tile'] = is_inside
        item['neighbors'] = []
        item['woningtype'] = ""
        local_map[work_id] = item

    spatial_index = QgsSpatialIndex()
    if features_for_index:
        spatial_index.addFeatures(features_for_index)

    build_neighbor_lists(tile_data, spatial_index, local_map, buffer_dist)

    results_background = []
    results_foreground = []

    for item in tile_data:
        woningtype = ""

        if item['has_woon']:
            if item['is_app']:
                woningtype = "appartement"
            else:
                neighbors = item['neighbors']
                cnt = len(neighbors)

                if cnt == 0:
                    woningtype = WONINGTYPE_VRIJSTAAND
                elif cnt >= 2:
                    woningtype = WONINGTYPE_TUSSEN
                    checked_top_neighbors, connected_top_neighbors = count_connected_top_neighbors(
                        item, neighbors, local_map, buffer_dist
                    )
                    if checked_top_neighbors >= 2 and connected_top_neighbors < 2:
                        woningtype = WONINGTYPE_TWEE_KAP
                elif cnt == 1:
                    buur_id = neighbors[0]
                    buur = local_map[buur_id]
                    buur_buur_count = len(buur.get('neighbors', []))

                    if buur_buur_count > 1:
                        woningtype = WONINGTYPE_HOEK
                    else:
                        if buur['is_app']:
                            woningtype = WONINGTYPE_HOEK
                        else:
                            woningtype = WONINGTYPE_TWEE_KAP

        item['woningtype'] = woningtype

    apply_row_sequence_corrections(tile_data, local_map)
    apply_detached_carport_corrections(tile_data, local_map, buffer_dist)

    for item in tile_data:
        if not item.get('inside_tile'):
            continue

        result_item = {
            'geom': item['geom'],
            'attrs': item['attrs'],
            'woningtype': item.get('woningtype', ""),
            'dakbron': item.get('dakbron', 'BAG'),
            'dakcontacten': len(item.get('ahn_roof_links', {})),
            'dakverbindingen': sum(bool(v) for v in item.get('ahn_roof_links', {}).values()),
            'dakonzeker': item.get('ahn_unknown_count', 0),
        }

        if result_item['woningtype']:
            results_foreground.append(result_item)
        else:
            results_background.append(result_item)

    return results_background + results_foreground


class WoningTyperingSortedAlgorithm(QgsProcessingAlgorithm):
    FETCH_MODE = 'FETCH_MODE'
    ROOF_SOURCE = 'ROOF_SOURCE'
    AHN_OFFLINE_ONLY = 'AHN_OFFLINE_ONLY'
    AHN_REFRESH_CACHE = 'AHN_REFRESH_CACHE'
    PROCESSING_EXTENT = 'PROCESSING_EXTENT'
    TILE_SIZE = 'TILE_SIZE'
    BUFFER = 'BUFFER'
    USE_3DBAG_LOD22 = 'USE_3DBAG_LOD22'
    USE_MT = 'USE_MT'
    CORES = 'CORES'
    OUTPUT = 'OUTPUT'

    MODE_CURRENT_CANVAS = 0
    MODE_FULL_NL = 1

    def createInstance(self):
        return WoningTyperingSortedAlgorithm()

    def name(self):
        return 'woningtypering_bag_pdok_final'

    def displayName(self):
        return 'Woningtypering BAG FINAL'

    def group(self):
        return 'BAG TOOLS'

    def groupId(self):
        return 'bag_tools'

    def shortHelpString(self):
        return "Haalt BAG panden automatisch op uit de PDOK BAG WFS en classificeert woningtypen.\n" \
               "- Keuze tussen huidige QGIS kaartvenster-extent en heel Nederland\n" \
               "- Controleert rijtjeshuizen met 3DBAG LoD 2.2 2D hoogste panddelen\n" \
               "- Snellere buurrelatieberekening per tegel\n" \
               "- Slaat 3DBAG-opvraging over voor tegels waar die niet nodig is"

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum(
            self.FETCH_MODE,
            'Gebied ophalen vanaf PDOK',
            options=[
                'Huidige QGIS kaartvenster-extent',
                'Heel Nederland'
            ],
            defaultValue=self.MODE_CURRENT_CANVAS
        ))
        self.addParameter(QgsProcessingParameterExtent(
            self.PROCESSING_EXTENT,
            'Gebied/extent (optioneel; overschrijft kaartvenster)',
            optional=True
        ))

        self.addParameter(QgsProcessingParameterNumber(self.TILE_SIZE, 'Tegelgrootte (meters)', type=QgsProcessingParameterNumber.Integer, defaultValue=10000, minValue=100))

        self.addParameter(QgsProcessingParameterNumber(self.BUFFER, 'Buffer afstand (meters)', type=QgsProcessingParameterNumber.Double, defaultValue=0.20, minValue=0.0, maxValue=10.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.ROOF_SOURCE,
            'Dakcontrole (AHN is onafhankelijk van 3DBAG)',
            options=['AHN DSM lokaal afleiden + cachen (aanbevolen)',
                     'Alleen BAG-pandcontouren (geen dakhoogtes)',
                     '3DBAG LoD2.2 (oude methode, optioneel)'],
            defaultValue=0
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.AHN_OFFLINE_ONLY, 'AHN: alleen lokaal opgeslagen DSM-tegels gebruiken',
            defaultValue=False
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.AHN_REFRESH_CACHE, 'AHN: opgeslagen DSM-tegels opnieuw downloaden',
            defaultValue=False
        ))
        # Compatibiliteitsparameter voor oudere Processing-aanroepen.
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_3DBAG_LOD22, 'Compatibiliteit: oude 3DBAG-optie',
            defaultValue=False
        ))
        self.addParameter(QgsProcessingParameterBoolean(self.USE_MT, 'Gebruik Multithreading', defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(self.CORES, 'Aantal Threads', type=QgsProcessingParameterNumber.Integer, defaultValue=4, minValue=1, maxValue=32))

        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, 'Resultaat'))

    def create_pdok_panden_layer(self):
        uri = (
            "pagingEnabled='true' "
            "pageSize='1000' "
            "restrictToRequestBBOX='1' "
            f"srsname='{PDOK_BAG_CRS_AUTHID}' "
            f"typename='{PDOK_BAG_TYPENAME}' "
            f"url='{PDOK_BAG_WFS_URL}' "
            "version='2.0.0'"
        )
        layer = QgsVectorLayer(uri, 'BAG panden (PDOK WFS)', 'WFS')
        if not layer.isValid():
            raise QgsProcessingException(
                f"Kan de PDOK BAG WFS niet openen: {PDOK_BAG_WFS_URL}"
            )
        return layer

    def create_3dbag_lod22_layer(self):
        uri = (
            "pagingEnabled='true' "
            "pageSize='10000' "
            "restrictToRequestBBOX='1' "
            f"srsname='{PDOK_BAG_CRS_AUTHID}' "
            f"typename='{BAG3D_LOD22_TYPENAME}' "
            f"url='{BAG3D_WFS_URL}' "
            "version='2.0.0'"
        )
        layer = QgsVectorLayer(uri, '3DBAG LoD 2.2 2D', 'WFS')
        if not layer.isValid():
            raise QgsProcessingException(
                f"Kan de 3DBAG LoD 2.2 2D WFS niet openen: {BAG3D_WFS_URL}"
            )
        return layer

    def collect_3dbag_top_geometries(self, lod22_layer, search_rect, feedback, wanted_bag_ids=None):
        fields = lod22_layer.fields()
        fld_ident = resolve_field(fields, 'identificatie')
        fld_height = resolve_field(fields, BAG3D_TOP_HEIGHT_FIELD)
        idx_ident = fields.indexOf(fld_ident)
        idx_height = fields.indexOf(fld_height)
        wanted_bag_ids = set(wanted_bag_ids or [])

        request = QgsFeatureRequest()
        request.setFilterRect(search_rect)
        request.setSubsetOfAttributes([fld_ident, fld_height], fields)

        top_parts = {}
        try:
            features = lod22_layer.getFeatures(request)
            for lod22_part in features:
                attrs = lod22_part.attributes()
                bag_id = normalize_bag_identification(attrs[idx_ident])
                if not bag_id:
                    continue
                if wanted_bag_ids and bag_id not in wanted_bag_ids:
                    continue

                height = safe_float(attrs[idx_height])
                if height is None:
                    continue

                geom = lod22_part.geometry()
                if geom is None or geom.isEmpty():
                    continue

                current = top_parts.get(bag_id)
                if current is None or height > current['height'] + 0.001:
                    top_parts[bag_id] = {
                        'height': height,
                        'geoms': [QgsGeometry(geom)]
                    }
                elif abs(height - current['height']) <= 0.001:
                    current['geoms'].append(QgsGeometry(geom))
        except Exception as e:
            feedback.reportError(f"3DBAG LoD 2.2 2D kon niet worden opgehaald voor tegel {format_rect(search_rect)}: {e}")
            return {}

        return {bag_id: data['geoms'] for bag_id, data in top_parts.items()}

    def current_canvas_extent(self, target_crs):
        try:
            from qgis.utils import iface
        except Exception:
            iface = None

        if iface is None or iface.mapCanvas() is None:
            raise QgsProcessingException(
                "Kan de huidige QGIS kaartvenster-extent niet bepalen. "
                "Start dit algoritme vanuit de QGIS GUI of kies 'Heel Nederland'."
            )

        canvas = iface.mapCanvas()
        extent = QgsRectangle(canvas.extent())
        canvas_crs = canvas.mapSettings().destinationCrs()

        if canvas_crs.isValid() and target_crs.isValid() and canvas_crs != target_crs:
            transform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)

        return extent

    def selected_processing_extent(self, fetch_mode, panden_layer, feedback):
        target_crs = panden_layer.sourceCrs()

        if fetch_mode == self.MODE_CURRENT_CANVAS:
            extent = self.current_canvas_extent(target_crs)
            feedback.pushInfo(
                f"Gebied: huidige QGIS kaartvenster-extent ({format_rect(extent)} in {target_crs.authid()})."
            )
            return extent

        extent = QgsRectangle(PDOK_FULL_NL_EXTENT)

        feedback.pushInfo(
            f"Gebied: heel Nederland met ruime RD New extent ({format_rect(extent)} in {target_crs.authid()})."
        )
        return extent

    def style_output_layer(self, context, feedback, dest_id, field_name):
        layer = context.getMapLayer(dest_id)
        if layer is None:
            return False

        if apply_woningtype_symbology(layer, field_name):
            feedback.pushInfo(f"Symbology ingesteld op categorieen van veld '{field_name}'.")
            return True

        feedback.reportError(f"Kon symbology niet instellen: veld '{field_name}' niet gevonden.")
        return False

    def postProcessAlgorithm(self, context, feedback):
        dest_id = getattr(self, '_output_dest_id', None)
        field_name = getattr(self, '_output_field_name', "Woningtype")
        if dest_id:
            self.style_output_layer(context, feedback, dest_id, field_name)
        return {}

    def processAlgorithm(self, parameters, context, feedback):
        fetch_mode = self.parameterAsEnum(parameters, self.FETCH_MODE, context)
        tile_size = self.parameterAsInt(parameters, self.TILE_SIZE, context)
        buffer_dist = self.parameterAsDouble(parameters, self.BUFFER, context)
        roof_source = self.parameterAsEnum(parameters, self.ROOF_SOURCE, context)
        if self.ROOF_SOURCE not in parameters and self.USE_3DBAG_LOD22 in parameters:
            roof_source = (2 if self.parameterAsBool(
                parameters, self.USE_3DBAG_LOD22, context) else 1)
        use_3dbag_lod22 = roof_source == 2
        ahn_offline = self.parameterAsBool(parameters, self.AHN_OFFLINE_ONLY, context)
        ahn_refresh = self.parameterAsBool(parameters, self.AHN_REFRESH_CACHE, context)
        use_mt = self.parameterAsBool(parameters, self.USE_MT, context)
        num_cores = self.parameterAsInt(parameters, self.CORES, context)

        panden_layer = self.create_pdok_panden_layer()
        if not panden_layer.isValid():
            raise QgsProcessingException("PDOK BAG panden-laag ongeldig.")

        lod22_layer = self.create_3dbag_lod22_layer() if use_3dbag_lod22 else None
        ahn_roofs = (AhnRoofContact(feedback, offline_only=ahn_offline,
                                    refresh=ahn_refresh) if roof_source == 0 else None)
        if ahn_roofs is not None:
            feedback.pushInfo('Dakcontrole: AHN DSM (PDOK) met lokale cache, zonder 3DBAG.')
        if lod22_layer is not None:
            feedback.pushInfo(
                f"3DBAG controle actief: {BAG3D_LOD22_TYPENAME}, hoogste panddeel op basis van {BAG3D_TOP_HEIGHT_FIELD}."
            )

        input_fields = panden_layer.fields()
        fld_identificatie = resolve_field(input_fields, 'identificatie')
        fld_aantal = resolve_field(input_fields, 'aantal_verblijfsobjecten')
        fld_doel = resolve_field(input_fields, 'gebruiksdoel')
        fld_status = resolve_field(input_fields, 'status')

        output_fields = panden_layer.fields()
        output_field_name = "Woningtype"
        if output_fields.indexOf(output_field_name) >= 0:
            output_field_name = "Woningtype_calc"
        output_fields.append(QgsField(output_field_name, QVariant.String))
        output_fields.append(QgsField('Dakbron', QVariant.String))
        output_fields.append(QgsField('Dakcontacten', QVariant.Int))
        output_fields.append(QgsField('Dakverbindingen', QVariant.Int))
        output_fields.append(QgsField('DakOnzeker', QVariant.Int))
        self._output_field_name = output_field_name

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            output_fields,
            panden_layer.wkbType(),
            panden_layer.sourceCrs()
        )
        self._output_dest_id = dest_id

        if sink is None:
            raise QgsProcessingException("Kon de outputlaag niet maken.")

        layer_extent = self.parameterAsExtent(
            parameters,
            self.PROCESSING_EXTENT,
            context,
            panden_layer.sourceCrs()
        )
        if layer_extent is not None and not layer_extent.isEmpty():
            feedback.pushInfo(
                f"Gebied: expliciet opgegeven Processing-extent "
                f"({format_rect(layer_extent)} in {panden_layer.sourceCrs().authid()})."
            )
        else:
            layer_extent = self.selected_processing_extent(
                fetch_mode, panden_layer, feedback
            )
        if layer_extent.isEmpty():
            return {self.OUTPUT: dest_id}

        xmin = layer_extent.xMinimum()
        xmax = layer_extent.xMaximum()
        ymin = layer_extent.yMinimum()
        ymax = layer_extent.yMaximum()

        if xmax <= xmin or ymax <= ymin:
            return {self.OUTPUT: dest_id}

        cols = max(1, int(math.ceil((xmax - xmin) / tile_size)))
        rows = max(1, int(math.ceil((ymax - ymin) / tile_size)))
        total_tiles = cols * rows

        feedback.pushInfo(
            f"Start PDOK verwerking (Tegelgrootte: {tile_size}m, Cores: {num_cores}, Tegels: {total_tiles}) - snel"
        )

        search_buffer_size = max(50.0, buffer_dist * 2)
        tiles_processed = 0
        workers = num_cores if use_mt else 1
        futures = []

        idx_identificatie = input_fields.indexOf(fld_identificatie)
        idx_aantal = input_fields.indexOf(fld_aantal)
        idx_doel = input_fields.indexOf(fld_doel)
        idx_status = input_fields.indexOf(fld_status)

        def write_results(results):
            if not results:
                return

            feats_to_add = []
            for res in results:
                new_feat = QgsFeature()
                new_feat.setGeometry(res['geom'])
                attrs = list(res['attrs'])
                attrs.extend((res['woningtype'], res['dakbron'], res['dakcontacten'],
                              res['dakverbindingen'], res['dakonzeker']))
                new_feat.setAttributes(attrs)
                feats_to_add.append(new_feat)

            if feats_to_add:
                sink.addFeatures(feats_to_add, QgsFeatureSink.FastInsert)

        def finish_future(future):
            try:
                write_results(future.result())
            except Exception as e:
                feedback.reportError(f"Fout in tegelberekening: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for r in range(rows):
                for c in range(cols):
                    if feedback.isCanceled():
                        executor.shutdown(wait=False)
                        return {}

                    t_xmin = xmin + (c * tile_size)
                    t_ymin = ymin + (r * tile_size)
                    t_xmax = min(t_xmin + tile_size, xmax)
                    t_ymax = min(t_ymin + tile_size, ymax)

                    tile_rect = QgsRectangle(t_xmin, t_ymin, t_xmax, t_ymax)
                    search_rect = QgsRectangle(tile_rect)
                    search_rect.grow(search_buffer_size)

                    request = QgsFeatureRequest()
                    request.setFilterRect(search_rect)
                    request.setFilterExpression(
                        f"{quote_expression_field(fld_status)} NOT IN "
                        "('Niet gerealiseerd', 'Niet gerealiseerd pand', 'Pand gesloopt')"
                    )

                    tile_data = []
                    lod22_candidate_ids = set()

                    for pand in panden_layer.getFeatures(request):
                        attrs = pand.attributes()
                        if is_excluded_status(attrs[idx_status]):
                            continue

                        bag_id = normalize_bag_identification(attrs[idx_identificatie])
                        aantal = attrs[idx_aantal]
                        doel_raw = attrs[idx_doel]

                        doel = str(doel_raw).lower() if doel_raw else ""

                        has_woon = 'woonfunctie' in doel
                        aantal_safe = safe_int(aantal)
                        is_appartement = (aantal_safe > 1 and has_woon)
                        is_overig_gebouw = (aantal_safe == 1 and 'overige' in doel and 'woon' not in doel)
                        is_doel_leeg = (not doel or doel.strip() == "")
                        ignore_neighbor = is_overig_gebouw or is_doel_leeg
                        if has_woon and not is_appartement and bag_id:
                            lod22_candidate_ids.add(bag_id)

                        tile_data.append({
                            'id': pand.id(),
                            'geom': QgsGeometry(pand.geometry()),
                            'attrs': attrs,
                            'bag_id': bag_id,
                            'has_woon': has_woon,
                            'is_app': is_appartement,
                            'ignore_neighbor': ignore_neighbor,
                            'lod22_top_geoms': [],
                            'dakbron': ('AHN lokaal' if roof_source == 0 else
                                        '3DBAG' if roof_source == 2 else 'BAG alleen'),
                        })

                    if not tile_data:
                        tiles_processed += 1
                        feedback.setProgress(int((tiles_processed / total_tiles) * 100))
                        continue

                    if lod22_layer is not None and len(lod22_candidate_ids) >= 2:
                        lod22_top_geoms = self.collect_3dbag_top_geometries(
                            lod22_layer,
                            search_rect,
                            feedback,
                            lod22_candidate_ids
                        )
                        if lod22_top_geoms:
                            for item in tile_data:
                                item['lod22_top_geoms'] = lod22_top_geoms.get(item['bag_id'], [])

                    if ahn_roofs is not None:
                        ahn_roofs.populate_tile(tile_data, buffer_dist)
                        for item in tile_data:
                            tested = len(item.get('ahn_roof_links', {}))
                            uncertain = item.get('ahn_unknown_count', 0)
                            if uncertain:
                                item['dakbron'] = 'AHN deels onzeker / BAG fallback'
                            elif not tested:
                                item['dakbron'] = 'BAG (geen toetsbaar dakcontact)'
                    rect_coords = (t_xmin, t_ymin, t_xmax, t_ymax)
                    future = executor.submit(calculate_tile_worker, tile_data, rect_coords, buffer_dist)
                    futures.append(future)

                    while len(futures) >= workers * 2:
                        done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                        for f in done:
                            finish_future(f)

                            tiles_processed += 1
                            if tiles_processed % 5 == 0:
                                feedback.setProgress(int((tiles_processed / total_tiles) * 100))
                        futures = list(not_done)

            for f in concurrent.futures.as_completed(futures):
                finish_future(f)

                tiles_processed += 1
                feedback.setProgress(int((tiles_processed / total_tiles) * 100))

        self.style_output_layer(context, feedback, dest_id, output_field_name)
        return {self.OUTPUT: dest_id}
