from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsLayerTreeGroup
)
import xml.etree.ElementTree as ET
import csv
import os
import re
from osgeo import ogr

class ImportSmallworldLayersWithCSV_V45_RelationIds(QgsProcessingAlgorithm):
    INPUT_XML = 'INPUT_XML'
    INPUT_CABLE_DATA_EXCEL = 'INPUT_CABLE_DATA_EXCEL'
    SHEET_NAME_CABLE = 'SHEET_NAME_CABLE'
    SHEET_NAME_JOINT = 'SHEET_NAME_JOINT'
    SHEET_NAME_CONN_CABLE = 'SHEET_NAME_CONN_CABLE'
    PURPOSE_MAPPING_STRING = 'PURPOSE_MAPPING_STRING'
    OUTPUT_GPKG = 'OUTPUT_GPKG'
    GROUP_NAME = 'GROUP_NAME'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ImportSmallworldLayersWithCSV_V45_RelationIds()

    def name(self):
        return 'import_smallworld_xml_csv_join_v45_relation_ids'

    def displayName(self):
        return self.tr('Import GEN XML + Excel (V45 - Relatie-ID koppeling)')

    def group(self):
        return self.tr('GEN (XML) TOOLS')

    def groupId(self):
        return 'GEN (XML) TOOLS'

    def flags(self):
        return QgsProcessingAlgorithm.FlagNoThreading

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_XML,
                self.tr('Input Smallworld XML Bestand'),
                extension='xml'
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_GPKG,
                self.tr('Opslaan als GeoPackage'),
                fileFilter='GeoPackage (*.gpkg)',
                optional=False
            )
        )

        # --- Kabel Data Excel ---
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_CABLE_DATA_EXCEL,
                self.tr('Input Excel (Bevat kabel- en mofdata)'),
                behavior=QgsProcessingParameterFile.File,
                fileFilter='Excel/CSV (*.xlsx *.xls *.csv)',
                optional=True
            )
        )
        
        # --- Sheet Namen Config ---
        self.addParameter(
            QgsProcessingParameterString(
                self.SHEET_NAME_CABLE,
                self.tr('Naam Excel Tabblad Kabels (begint met...)'),
                defaultValue='LS Kabel',
                optional=False
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.SHEET_NAME_JOINT,
                self.tr('Naam Excel Tabblad Moffen (begint met...)'),
                defaultValue='LS OV Kabelmof',
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.SHEET_NAME_CONN_CABLE,
                self.tr('Naam Excel Tabblad LS Aansluitkabel (begint met...)'),
                defaultValue='LS Aansluitkabel',
                optional=False
            )
        )

        # --- Gebruiksdoel Mapping ---
        default_purpose_map = (
            "8279061393076917696=Zwembad\n"
            "9097483229694280480=Zuivere teruglevering\n"
            "8279061393076917695=Ziekenhuis\n"
            "8279061393076917694=Wozoco\n"
            "8279061393076917693=Woonhuis\n"
            "8279061393076917692=Woonboot\n"
            "8279061393076917691=Woning-bedrijf\n"
            "8279061393076917690=WKO (warmte Koude Opslag)\n"
            "8279061393076917689=Winkel\n"
            "8279061393076917688=Werkplaats\n"
            "8279061393076917687=Warmte kracht installatie\n"
            "8279061393076917686=Warenhuis\n"
            "8279061393076917685=Vuilcontainer\n"
            "8279061393076917683=VRI-kast\n"
            "8279061393076917684=Vrijstaande woning\n"
            "8279061393076917705=VRI Kast\n"
            "8279061393076917682=Villa\n"
            "8279061393076917681=Verlichting\n"
            "8279061393076917680=Verkeersbord verlichting\n"
            "8279061393076917679=Urinoir\n"
            "8279061393076917678=Twee onder een kap woning\n"
            "8279061393076917677=Tuinder\n"
            "8279061393076917676=Telefooncentrale\n"
            "8279061393076917675=Telefooncel\n"
            "8279061393076917712=Telecom Kast\n"
            "8279061393076917674=Tankstation\n"
            "8279061393076917673=Stuw\n"
            "8279061393076917672=Sportpark\n"
            "8279061393076917671=Sporthal\n"
            "8279061393076917670=Sirene\n"
            "8279061393076917669=Schuur\n"
            "8279061393076917668=School\n"
            "8279061393076917667=Scheepvaartverlichting\n"
            "8279061393076917703=Rioolkast, Rioolgemaal\n"
            "8279061393076917666=Rioolkast\n"
            "8279061393076917665=Rioolgemaal\n"
            "8279061393076917664=Reclamezuil\n"
            "8279061393076917708=Putkast\n"
            "8279061393076917713=Postbusautomaat\n"
            "8279061393076917663=Pompkelder\n"
            "8279061393076917662=Pompgemaal\n"
            "8279061393076917661=Politie\n"
            "8279061393076917660=Plattegrond\n"
            "8279061393076917659=Pinautomaat\n"
            "8279061393076917699=Parkeerautomaat, slagboom\n"
            "8279061393076917658=Parkeerautomaat\n"
            "8279061393076917657=OV-relaismast\n"
            "8279061393076917656=OV-ontsteekpunt\n"
            "8279061393076917655=OV-mast\n"
            "8279061393076917715=OV-kast tbv rijkswaterstaat\n"
            "8279061393076917716=OV-kast tbv provincie\n"
            "8279061393076917717=OV-kast tbv particulier\n"
            "8279061393076917714=OV-kast tbv gemeente\n"
            "8279061393076917654=OV-kast\n"
            "8279061393076917706=OV Kast\n"
            "9097483229694280481=Opwek\n"
            "8279061393076917653=Oplaadpunt electrisch vervoer\n"
            "8910284975564128286=Ondergrondse behuizing\n"
            "8279061393076917652=Onbekend\n"
            "8279061393076917651=Nederlandse spoorwegen\n"
            "8279061393076917650=Middelgroot bedrijf\n"
            "8279061393076917649=Medische praktijk\n"
            "8279061393076917710=Marktkast\n"
            "8279061393076917648=LS Koppeling Klantstation\n"
            "8279061393076917647=Loods\n"
            "8279061393076917646=Lift\n"
            "8279061393076917644=Klok\n"
            "8279061393076917643=Klein bedrijf\n"
            "8279061393076917642=Kermis aansluiting\n"
            "8279061393076917641=Kerk\n"
            "8279061393076917640=Kelder\n"
            "8279061393076917711=Kast Verlichting\n"
            "8279061393076917639=Informatiebord\n"
            "8279061393076917638=Horeca\n"
            "8279061393076917629=G-Station\n"
            "8279061393076917637=GSM-mast\n"
            "8279061393076917704=GSM Mast\n"
            "8279061393076917636=Groot bedrijf\n"
            "8279061393076917635=Gevoelige gebruiker\n"
            "8279061393076917634=Gevelverlichting\n"
            "8279061393076917633=Gemeentehuis\n"
            "8279061393076917632=Gemeenschapshuis / MFC\n"
            "8279061393076917631=Gemaal\n"
            "8279061393076917630=Garage\n"
            "8279061393076917628=Frituurwagen\n"
            "8279061393076917627=Fontein\n"
            "8279061393076917626=Flat\n"
            "8279061393076917625=Feestverlichting\n"
            "8279061393076917624=Evenement\n"
            "8279061393076917623=Etagewoning\n"
            "8279061393076917617=E-station\n"
            "456072561298510055=ELP kast\n"
            "8279061393076917622=Eindmof\n"
            "8279061393076917620=Eigenrichting\n"
            "8279061393076917619=Eigen installatie\n"
            "8279061393076917618=Eengezinswoning\n"
            "8279061393076917702=Diversen (niet zijnde gebouwen)\n"
            "8279061393076917616=Dierenverblijf\n"
            "8279061393076917700=Camera, flitspaal\n"
            "8279061393076917615=Camera\n"
            "8279061393076917614=CAI-KAST\n"
            "8279061393076917707=CAI Kast\n"
            "8279061393076917613=Bushalte\n"
            "8279061393076917612=Brug\n"
            "8279061393076917611=Brandweerkazerne\n"
            "8279061393076917610=Brandleiding\n"
            "8279061393076917609=Bouwkeet\n"
            "8279061393076917608=Bouwaansluiting\n"
            "8279061393076917607=Bollard Pilaar\n"
            "8279061393076917606=Boerderij\n"
            "8279061393076917605=Begraafplaats\n"
            "8279061393076917604=Bedrijfspand\n"
            "8279061393076917603=Apotheek\n"
            "8279061393076917602=Anwb\n"
            "8279061393076917601=Alg. voorz. etagebouw\n"
            "8279061393076917701=Afvaldepot, vuilcontainer\n"
            "8279061393076917698=Achterpadverlichting\n"
            "8279061393076917697=Abri, bushalte (+display), reclamezuil\n"
            "8279061393076917600=Abri\n"
            "8279061393076917599=Aardgasvulpunt\n"
            "8279061393076917598=Aansluitkast\n"
            "8279061393076917597=Aansluiting\n"
            "8279061393076917709=Aansluitbox\n"
            "8279061393076917596=Aannemer"
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.PURPOSE_MAPPING_STRING,
                self.tr('Gebruiksdoel Mapping (ID=Naam, 1 per regel)'),
                defaultValue=default_purpose_map,
                optional=True,
                multiLine=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.GROUP_NAME,
                self.tr('Naam van de Groep in QGIS'),
                defaultValue='Smallworld Import',
                optional=False
            )
        )

    def make_address_key(self, zip_c, house_n, house_add):
        z = str(zip_c).strip().replace(" ", "").lower()
        n = str(house_n).strip().replace(" ", "").lower()
        a = str(house_add).strip().replace(" ", "").lower() if house_add else ""
        if n.isdigit(): n = str(int(n))
        if not z or not n: return None
        return f"{z}_{n}" if not a else f"{z}_{n}_{a}"

    def parse_mapping_string(self, mapping_str):
        mapping = {}
        if not mapping_str: return mapping
        lines = mapping_str.split('\n')
        for line in lines:
            if '=' in line:
                parts = line.split('=', 1)
                key = parts[0].strip()
                val = parts[1].strip()
                val = val.strip('"').strip("'")
                if key and val: mapping[key] = val
        return mapping

    def read_excel_sheet(self, excel_path, sheet_prefix, join_col_name, data_cols, feedback):
        """Leest een specifieke sheet uit en returnt een dictionary op basis van de join kolom."""
        lookup_data = {}
        
        try:
            ds = ogr.Open(excel_path)
            if not ds: return {}
            
            target_sheet = None
            layer_count = ds.GetLayerCount()
            for i in range(layer_count):
                lyr_name = ds.GetLayerByIndex(i).GetName()
                if lyr_name.lower().startswith(sheet_prefix.lower()):
                    target_sheet = lyr_name
                    break
            
            if not target_sheet:
                feedback.pushInfo(f"Geen sheet gevonden beginnend met '{sheet_prefix}'.")
                return {}
            
            feedback.pushInfo(f"Sheet gevonden: '{target_sheet}'. Bezig met lezen...")
            vl = QgsVectorLayer(f"{excel_path}|layername={target_sheet}", "temp", "ogr")
            if not vl.isValid(): return {}

            fields = vl.fields()
            
            join_idx = -1
            for i, f in enumerate(fields):
                if f.name().lower().strip() == join_col_name.lower().strip():
                    join_idx = i
                    break
            
            if join_idx == -1:
                feedback.pushInfo(f"Kolom '{join_col_name}' niet gevonden in sheet '{target_sheet}'.")
                return {}

            col_indices = {}
            for col in data_cols:
                found_idx = -1
                for i, f in enumerate(fields):
                    fname = f.name().lower()
                    if col.lower() == 'kabel subgroep' and (('sub' in fname and 'groep' in fname) or ('sub' in fname and 'group' in fname) or 'parent' in fname):
                         found_idx = i
                         break
                    elif f.name().lower().strip() == col.lower().strip():
                        found_idx = i
                        break
                if found_idx != -1:
                    col_indices[col] = found_idx
            
            count = 0
            for feat in vl.getFeatures():
                attrs = feat.attributes()
                join_val = str(attrs[join_idx]).strip()
                if join_val.endswith('.0'): join_val = join_val[:-2] 
                
                if join_val:
                    row_data = {}
                    for col_name, idx in col_indices.items():
                        val = str(attrs[idx]).strip()
                        if val and val.lower() not in ['null', 'none']:
                            row_data[col_name] = val
                    
                    if row_data:
                        lookup_data[join_val] = row_data
                        count += 1
            
            feedback.pushInfo(f"{count} records geladen uit '{target_sheet}'.")
            return lookup_data

        except Exception as e:
            feedback.reportError(f"Fout bij lezen sheet prefix '{sheet_prefix}': {e}")
            return {}

    def processAlgorithm(self, parameters, context, feedback):
        xml_file = self.parameterAsFile(parameters, self.INPUT_XML, context)
        gpkg_path = self.parameterAsString(parameters, self.OUTPUT_GPKG, context)
        cable_excel = self.parameterAsFile(parameters, self.INPUT_CABLE_DATA_EXCEL, context)
        
        sheet_cable = self.parameterAsString(parameters, self.SHEET_NAME_CABLE, context)
        sheet_joint = self.parameterAsString(parameters, self.SHEET_NAME_JOINT, context)
        sheet_conn_cable = self.parameterAsString(parameters, self.SHEET_NAME_CONN_CABLE, context)
        
        raw_purpose_str = self.parameterAsString(parameters, self.PURPOSE_MAPPING_STRING, context)
        purpose_map = self.parse_mapping_string(raw_purpose_str)
        feedback.pushInfo(f"Gebruiksdoelen geladen uit instellingen: {len(purpose_map)} items.")

        # --- Aardingswijze Mapping ---
        grounding_map = {
            "352114": "Groep 1: Klant",
            "352115": "Groep 2: Klant Waterleiding",
            "352116": "Groep 3: TN-aarding",
            "352117": "Groep 4: Separaat aardnet",
            "352118": "Groep 4: (Lood)Mantelaarding",
            "352119": "Groep 4: Overig",
            "352120": "Groep 4: Nulling",
            "352121": "Groep 4: 5de ader"
        }
        
        group_name = self.parameterAsString(parameters, self.GROUP_NAME, context)
        xml_id_tag = 'master_asset_id'
        
        cable_data_lookup = {}
        joint_data_lookup = {}
        conn_cable_lookup = {}
        
        if cable_excel and os.path.exists(cable_excel):
            feedback.pushInfo(f"--- START EXCEL ANALYSE ---")
            cable_data_lookup = self.read_excel_sheet(
                cable_excel, sheet_prefix=sheet_cable, join_col_name="id", data_cols=["Type", "Kabel Subgroep"], feedback=feedback
            )
            joint_data_lookup = self.read_excel_sheet(
                cable_excel, sheet_prefix=sheet_joint, join_col_name="Master Asset Id", data_cols=["Kabelgroep"], feedback=feedback
            )
            conn_cable_lookup = self.read_excel_sheet(
                cable_excel, sheet_prefix=sheet_conn_cable, join_col_name="Master Asset Id", data_cols=["Type"], feedback=feedback
            )
            feedback.pushInfo(f"--- EINDE EXCEL ANALYSE ---")

        def strip_ns(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        def identifier_key(identifier):
            """Haalt de sleutel uit een Smallworld-relatie-identifier."""
            match = re.search(r'VkeysZ(.+?)(?:Q0)?$', identifier or '')
            return match.group(1) if match else ''

        # --- 3. XML Indexering ---
        feedback.pushInfo("Indexeren Stations, Trafo's & Gas...")
        station_lookup = {}
        transformer_lookup = {}
        ld_address_lookup = {} 
        # Relatie-Features bevatten alleen een identifier. Bewaar daarom voor
        # ieder echt XML-object de koppeling van identifier naar zijn id.
        identifier_id_lookup = {}
        context_iter_0 = ET.iterparse(xml_file, events=("end",))
        count_stations = 0
        count_trafos = 0
        
        for event, elem in context_iter_0:
            tag = strip_ns(elem.tag)
            if tag == 'Feature':
                type_name = elem.attrib.get('typeName', '')

                identifier = elem.attrib.get('identifier', '')
                referenced_id = None
                for child in elem:
                    if (strip_ns(child.tag) == 'property'
                            and child.attrib.get('typeName', '') == 'id'
                            and child.text):
                        referenced_id = child.text.strip()
                        break
                if identifier and referenced_id:
                    identifier_id_lookup[identifier] = referenced_id
                
                # Sla Station info op
                if type_name == 'e_fl_station':
                    s_attrs, s_id = {}, None
                    for child in elem:
                        child_tag = strip_ns(child.tag)
                        if child_tag == 'property':
                            p_name = child.attrib.get('typeName', '')
                            p_val = child.text
                            if p_name and p_val:
                                s_attrs[p_name] = p_val.strip()
                                if p_name == 'id': s_id = p_val.strip()
                    if s_id: 
                        station_lookup[s_id] = s_attrs
                        count_stations += 1
                
                # Sla MS/LS Trafo info op (gekoppeld aan station_id)
                elif type_name == 'e_fl_lv_transformer':
                    t_attrs, t_station_id = {}, None
                    for child in elem:
                        if strip_ns(child.tag) == 'property':
                            p_name = child.attrib.get('typeName', '')
                            p_val = child.text
                            if p_name and p_val:
                                t_attrs[p_name] = p_val.strip()
                                if p_name == 'station_id':
                                    t_station_id = p_val.strip()
                    if t_station_id:
                        transformer_lookup[t_station_id] = t_attrs
                        count_trafos += 1

                elif type_name == 'g_service_connection':
                    zc, hn, ha, pt = "", "", "", ""
                    for child in elem:
                        if strip_ns(child.tag) == 'property':
                            p_name = child.attrib.get('typeName', '')
                            p_val = child.text
                            if p_name and p_val:
                                val = p_val.strip()
                                if p_name in ['zip_code', 'postcode']: zc = val
                                elif p_name in ['house_number', 'housenumber']: hn = val
                                elif p_name == 'house_number_addition': ha = val
                                elif p_name == 'service_connection_pipe_type': pt = val
                    if zc and hn and pt:
                        key = self.make_address_key(zc, hn, ha)
                        if key: 
                            ld_address_lookup[key] = pt
                            
            if tag == 'featureMember' or tag == 'Feature': elem.clear()
        
        feedback.pushInfo(f"Indexering compleet. {count_stations} stations en {count_trafos} trafo's geïndexeerd.")

        feedback.pushInfo(f"{len(identifier_id_lookup)} XML-identifiers aan object-id's gekoppeld.")

        # --- 4. XML Verwerking ---
        feedback.pushInfo("Geometrie en datakoppeling verwerken...")
        layers_data = {}
        context_iter = ET.iterparse(xml_file, events=("end",))
        count = 0
        
        for event, elem in context_iter:
            tag = strip_ns(elem.tag)
            if tag == 'Feature':
                type_name = elem.attrib.get('typeName', 'Onbekend')
                
                # Schematische en labels overslaan, pak alleen bruikbare coördinaten
                preferred_geom_name = 'area_map' if type_name == 'e_lv_protection_pipe' else None
                best_geom_data = None 
                default_geom_data = None 
                
                for child in elem:
                    child_tag = strip_ns(child.tag)
                    if child_tag == 'boundedBy': continue
                    
                    prop_name = child.attrib.get('typeName', '')
                    if prop_name and ('schematic' in prop_name.lower() or 'label' in prop_name.lower()):
                        continue

                    coords_elem = child.find('.//{*}coordinates')
                    if coords_elem is None and child_tag == 'coordinates': coords_elem = child
                    if coords_elem is not None and coords_elem.text:
                        coords_text = coords_elem.text.strip()
                        found_g_type = 'LineString' 
                        if child_tag.lower() == 'point': found_g_type = 'Point'
                        elif child_tag.lower() == 'polygon': found_g_type = 'Polygon'
                        if child.find('.//{*}Polygon') is not None: found_g_type = 'Polygon'
                        elif child.find('.//{*}Point') is not None: found_g_type = 'Point'
                        
                        current_data = (coords_text, found_g_type)
                        if preferred_geom_name:
                            if prop_name == preferred_geom_name:
                                best_geom_data = current_data
                                break 
                            if default_geom_data is None: default_geom_data = current_data
                        else:
                            best_geom_data = current_data
                            break
                
                if best_geom_data is None and default_geom_data is not None:
                    best_geom_data = default_geom_data
                
                # --- Attributen Ophalen ---
                attrs = {}
                feature_id = None
                internal_id = None
                cur_zip, cur_hn, cur_ha = "", "", ""

                for child in elem:
                    child_tag = strip_ns(child.tag)
                    if child_tag == 'property':
                        p_name = child.attrib.get('typeName', '')
                        p_val = child.text
                        if p_name and p_val:
                            clean_val = p_val.strip()
                            attrs[p_name] = clean_val
                            
                            if p_name == 'id': internal_id = clean_val
                            if p_name == xml_id_tag: feature_id = clean_val
                            if p_name in ['zip_code', 'postcode']: cur_zip = clean_val
                            elif p_name in ['house_number', 'housenumber']: cur_hn = clean_val
                            elif p_name == 'house_number_addition': cur_ha = clean_val

                    elif (child_tag == 'geometricProperty'
                            and type_name == 'lvm_station_location'
                            and child.attrib.get('typeName', '') == 'label'):
                        # Het stationsnummer staat in de XML-labeltekst, meestal
                        # op de eerste regel, bijvoorbeeld "079.1010".
                        label_elem = child.find('.//{*}string')
                        if label_elem is not None and label_elem.text:
                            label_lines = [
                                line.strip()
                                for line in label_elem.text.splitlines()
                                if line.strip()
                            ]
                            if label_lines:
                                attrs['Station'] = label_lines[0]

                    elif child_tag == 'relationshipProperty':
                        rel_name = child.attrib.get('typeName', '')
                        nested_features = [
                            sub for sub in child if strip_ns(sub.tag) == 'Feature'
                        ]
                        relation_ids = []
                        for nested_feat in nested_features:
                            nested_identifier = nested_feat.attrib.get('identifier', '')
                            relation_id = identifier_id_lookup.get(nested_identifier)
                            # e_lv_cable_subgroup staat niet als bronlaag in elke
                            # export. De numerieke sleutel is wel onderdeel van
                            # de identifier en matcht met structure_parent_id.
                            if not relation_id and rel_name == 'cable_subgroups':
                                relation_id = identifier_key(nested_identifier)
                            if relation_id and relation_id not in relation_ids:
                                relation_ids.append(relation_id)

                            for sub_p in nested_feat:
                                if strip_ns(sub_p.tag) == 'property':
                                    sp_name = sub_p.attrib.get('typeName', '')
                                    sp_val = sub_p.text
                                    if sp_name and sp_val:
                                        col_name = f"{rel_name}_{sp_name}"
                                        attrs[col_name] = sp_val.strip()

                        if rel_name and relation_ids:
                            # Bij meerdere gekoppelde objecten blijven alle id's
                            # als kommagescheiden waarden in hetzelfde veld staan.
                            attrs[f"{rel_name}_id"] = ",".join(relation_ids)

                        if (type_name == 'e_lv_multistory_connection'
                                and rel_name == 'service_connections'):
                            connection_count = child.attrib.get('count')
                            if connection_count is None or not connection_count.strip():
                                connection_count = str(len(nested_features))
                            attrs['Totaal aantal aansluitingen'] = connection_count.strip()

                # --- 4. Relaties en Data koppelen ---
                if type_name == 'lvm_station_location':
                    lid = attrs.get('e_fl_station_id')
                    if lid:
                        # 1. Koppel algemene station info
                        if lid in station_lookup:
                            for k, v in station_lookup[lid].items(): 
                                if k not in attrs: attrs[k] = v
                        # 2. Koppel MS/LS Trafo-info aan het locatievlak. Het
                        # stationsnummer zelf komt rechtstreeks uit het XML-label.
                        if lid in transformer_lookup:
                            for k, v in transformer_lookup[lid].items():
                                t_key = f"trafo_{k}"
                                if t_key not in attrs: attrs[t_key] = v
                
                elif type_name == 'e_lv_service_connection':
                    mk = self.make_address_key(cur_zip, cur_hn, cur_ha)
                    if mk and mk in ld_address_lookup: attrs['G_Type'] = ld_address_lookup[mk]
                    
                    upid = attrs.get('user_purpose_id')
                    attrs['Gebruiksdoel'] = purpose_map.get(upid, "") if upid else ""

                    # --- Aardingswijze Toevoegen ---
                    grounding_id = attrs.get('manner_of_grounding_id')
                    attrs['Aardingswijze'] = grounding_map.get(grounding_id, "") if grounding_id else ""

                    hn_key = 'housenumber' if 'housenumber' in attrs else ('house_number' if 'house_number' in attrs else None)
                    attrs['Toevoeging'] = ""
                    if hn_key:
                        raw_val = str(attrs[hn_key]).strip()
                        match = re.match(r'^(\d+)(.*)$', raw_val)
                        if match:
                            attrs[hn_key] = match.group(1)
                            attrs['Toevoeging'] = match.group(2).strip()
                        else:
                            attrs[hn_key] = ""
                            attrs['Toevoeging'] = raw_val

                # Excel Joins
                if type_name == 'e_lv_map_cable':
                    if 'Kabel Subgroep' not in attrs: attrs['Kabel Subgroep'] = ""
                    if 'Type' not in attrs: attrs['Type'] = ""
                    if internal_id and internal_id in cable_data_lookup:
                        extra = cable_data_lookup[internal_id]
                        if 'Type' in extra: attrs['Type'] = extra['Type']
                        if 'Kabel Subgroep' in extra: attrs['Kabel Subgroep'] = extra['Kabel Subgroep']

                if type_name == 'e_lv_map_cable_joint':
                    attrs['Kabelgroep'] = ""
                    if feature_id and feature_id in joint_data_lookup:
                        extra = joint_data_lookup[feature_id]
                        if 'Kabelgroep' in extra: attrs['Kabelgroep'] = extra['Kabelgroep']

                # --- LS Aansluitkabel Excel Join ---
                if type_name == 'e_lv_connection_cable':
                    if 'Type' not in attrs: attrs['Type'] = ""
                    if feature_id and feature_id in conn_cable_lookup:
                        extra = conn_cable_lookup[feature_id]
                        if 'Type' in extra: attrs['Type'] = extra['Type']

                # --- QGIS Geometrie Maken ---
                geom = None
                if best_geom_data:
                    coords_text, found_g_type = best_geom_data
                    try:
                        parts = coords_text.replace(',', ' ').split()
                        floats = [float(x)/1000.0 for x in parts] 
                        pts = []
                        for i in range(0, len(floats)-1, 2): pts.append(QgsPointXY(floats[i], floats[i+1]))
                        if len(pts) == 1: geom = QgsGeometry.fromPointXY(pts[0])
                        elif len(pts) > 1:
                            if found_g_type == 'Polygon': geom = QgsGeometry.fromPolygonXY([pts])
                            else: geom = QgsGeometry.fromPolylineXY(pts)
                    except: pass

                if geom:
                    if type_name not in layers_data:
                        layers_data[type_name] = {"wkb_type": geom.wkbType(), "fields": set(), "features": []}
                    for k in attrs.keys(): layers_data[type_name]["fields"].add(k)
                    layers_data[type_name]["features"].append({"geom": geom, "attrs": attrs})
                    count += 1

            # Zelfsluitende relatie-Features moeten blijven bestaan totdat het
            # bovenliggende object volledig is verwerkt. featureMember wist
            # daarna het complete object en begrenst zo het geheugengebruik.
            if tag == 'featureMember': elem.clear()

        feedback.pushInfo(f"{count} objecten verwerkt.")

        # =========================================================================
        # Kabel Subgroep Propagatie
        # =========================================================================
        map_cable_subgroups = {}
        if 'e_lv_map_cable' in layers_data:
            for feat_data in layers_data['e_lv_map_cable']['features']:
                attrs = feat_data['attrs']
                parent_id = attrs.get('structure_parent_id')
                subgroep = attrs.get('Kabel Subgroep')
                if parent_id and subgroep:
                    map_cable_subgroups[parent_id] = subgroep
        
        if 'e_lv_connection_cable' in layers_data and map_cable_subgroups:
            layers_data['e_lv_connection_cable']['fields'].add('Kabel Subgroep')
            for feat_data in layers_data['e_lv_connection_cable']['features']:
                attrs = feat_data['attrs']
                subgroup_id = attrs.get('cable_subgroup_id')
                if subgroup_id and subgroup_id in map_cable_subgroups:
                    attrs['Kabel Subgroep'] = map_cable_subgroups[subgroup_id]

        # Koppel de Excel-kabelsubgroep van e_lv_map_cable rechtstreeks aan de
        # cable_subgroups-relatie van iedere LS-aansluiting.
        if 'e_lv_service_connection' in layers_data and map_cable_subgroups:
            layers_data['e_lv_service_connection']['fields'].add('Kabel Subgroep')
            for feat_data in layers_data['e_lv_service_connection']['features']:
                attrs = feat_data['attrs']
                subgroup_ids = attrs.get('cable_subgroups_id', '').split(',')
                subgroups = []
                for subgroup_id in subgroup_ids:
                    subgroup = map_cable_subgroups.get(subgroup_id.strip())
                    if subgroup and subgroup not in subgroups:
                        subgroups.append(subgroup)
                attrs['Kabel Subgroep'] = ', '.join(subgroups)

        # =========================================================================
        # Topologische trace voor e_lv_service_connection Aansluitkabel Types
        # =========================================================================
        feedback.pushInfo("Analyseren van topologie voor Aansluitkabel Types...")
        conn_cables = []
        node_to_cables = {}

        if 'e_lv_connection_cable' in layers_data and 'e_lv_service_connection' in layers_data:
            # Sla alle aansluitkabel endpoints op
            for idx, feat_data in enumerate(layers_data['e_lv_connection_cable']['features']):
                geom = feat_data['geom']
                c_type = feat_data['attrs'].get('Type', '')
                if geom and geom.type() == QgsWkbTypes.LineGeometry:
                    pts = geom.asPolyline()
                    if len(pts) >= 2:
                        p1 = (round(pts[0].x(), 3), round(pts[0].y(), 3))
                        p2 = (round(pts[-1].x(), 3), round(pts[-1].y(), 3))
                        conn_cables.append({'id': idx, 'type': c_type, 'p1': p1, 'p2': p2})
                        node_to_cables.setdefault(p1, []).append(idx)
                        node_to_cables.setdefault(p2, []).append(idx)

            # Trace vanuit elke service connection
            for feat_data in layers_data['e_lv_service_connection']['features']:
                geom = feat_data['geom']
                if not geom: continue
                
                sc_pt = None
                # Zoek een connectiepunt met de kabel (check alle vertices van de service connection)
                for v in geom.vertices():
                    v_tup = (round(v.x(), 3), round(v.y(), 3))
                    if v_tup in node_to_cables:
                        sc_pt = v_tup
                        break
                
                if not sc_pt: 
                    continue
                    
                path_types = []
                current_node = sc_pt
                visited = set()
                
                # Loop het kabelnetwerk af
                while True:
                    connected_indices = node_to_cables.get(current_node, [])
                    unvisited = [idx for idx in connected_indices if idx not in visited]
                    
                    if not unvisited:
                        break
                    
                    # Neem de eerste onbezochte verbonden kabel
                    next_cable_idx = unvisited[0]
                    visited.add(next_cable_idx)
                    
                    cable_info = conn_cables[next_cable_idx]
                    path_types.append(cable_info['type'])
                    
                    # Verplaats de pointer naar de andere kant van de kabel
                    if cable_info['p1'] == current_node:
                        current_node = cable_info['p2']
                    else:
                        current_node = cable_info['p1']
                        
                # Keer de lijst om (eerste in de lijst wordt het verst liggende kabeltype)
                path_types.reverse()
                
                # Voeg toe aan attributen
                for i, c_type in enumerate(path_types):
                    col_name = f'Aansluitkabel Type {i+1}'
                    feat_data['attrs'][col_name] = c_type
                    layers_data['e_lv_service_connection']['fields'].add(col_name)

        # =========================================================================
        # Creëer een "Station locatie" puntenlaag o.b.v. het zwaartepunt
        # =========================================================================
        if 'lvm_station_location' in layers_data:
            feedback.pushInfo(
                "Genereren van 'Station locatie' punten uit lvm_station_location..."
            )
            station_loc_data = {
                "wkb_type": QgsWkbTypes.Point,
                "fields": set(layers_data['lvm_station_location']["fields"]),
                "features": []
            }
            station_loc_data["fields"].update({'RD_X', 'RD_Y', 'Locatiebron'})
            station_points_with_name = 0

            for feat_data in layers_data['lvm_station_location']["features"]:
                source_geom = feat_data["geom"]
                attrs = dict(feat_data["attrs"])
                if source_geom:
                    try:
                        centroid_source = source_geom

                        # Smallworld levert lvm_station_location soms als een
                        # gesloten lijn. Behandel die als een vlak, zodat het
                        # stationpunt het echte vlakzwaartepunt wordt.
                        if source_geom.type() == QgsWkbTypes.LineGeometry:
                            ring = source_geom.asPolyline()
                            if (len(ring) >= 4
                                    and ring[0].x() == ring[-1].x()
                                    and ring[0].y() == ring[-1].y()):
                                centroid_source = QgsGeometry.fromPolygonXY([ring])

                        centroid_geom = centroid_source.centroid()
                        if centroid_geom and not centroid_geom.isEmpty():
                            point = centroid_geom.asPoint()
                            attrs['RD_X'] = f"{point.x():.3f}"
                            attrs['RD_Y'] = f"{point.y():.3f}"
                            attrs['Locatiebron'] = 'lvm_station_location (EPSG:28992)'
                            if attrs.get('Station'):
                                station_points_with_name += 1
                            station_loc_data["features"].append({
                                "geom": centroid_geom,
                                "attrs": attrs
                            })
                    except Exception as e:
                        feedback.reportError(
                            f"Kon stationpunt niet maken voor station-id "
                            f"{attrs.get('e_fl_station_id', '')}: {e}"
                        )

            if station_loc_data["features"]:
                layers_data['Station locatie'] = station_loc_data
                feedback.pushInfo(
                    f"{len(station_loc_data['features'])} fysieke stationpunten "
                    f"gegenereerd; {station_points_with_name} met een "
                    f"stationsnummer uit het XML-label."
                )

        # --- GPKG Write ---
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.findGroup(group_name)
        if not group: group = root.insertGroup(0, group_name)
        
        first_layer = True
        
        # Hulpfunctie voor "natuurlijk" sorteren (bijv. Type 1, Type 2, Type 10)
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

        for layer_name, data in layers_data.items():
            wkb_type = data["wkb_type"]
            
            if wkb_type == QgsWkbTypes.Point: type_str = "Point"
            elif wkb_type == QgsWkbTypes.LineString: type_str = "LineString"
            elif wkb_type == QgsWkbTypes.Polygon: type_str = "Polygon"
            else: type_str = "Point"

            vl = QgsVectorLayer(f"{type_str}?crs=epsg:28992", layer_name, "memory")
            pr = vl.dataProvider()
            qgs_fields = []
            
            # --- NIEUW: Sorteer de velden zodat ze logisch gegroepeerd staan ---
            sorted_field_names = sorted(list(data["fields"]), key=natural_sort_key)
            
            for fn in sorted_field_names: 
                qgs_fields.append(QgsField(fn, QVariant.String))
                
            pr.addAttributes(qgs_fields)
            vl.updateFields()

            qgs_feats = []
            for f_data in data["features"]:
                feat = QgsFeature()
                feat.setFields(vl.fields())
                feat.setGeometry(f_data["geom"])
                for k, v in f_data["attrs"].items(): feat.setAttribute(k, v)
                qgs_feats.append(feat)
            
            pr.addFeatures(qgs_feats)
            vl.updateExtents()
            
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            if first_layer:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
                first_layer = False
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                vl, gpkg_path, context.transformContext(), options
            )
            if result[0] != QgsVectorFileWriter.NoError:
                raise QgsProcessingException(
                    f"Laag '{layer_name}' schrijven mislukt: {result[1]}"
                )
            
        # Open readers after all GeoPackage schema changes are finished.
        for layer_name in layers_data:
            uri = f"{gpkg_path}|layername={layer_name}"
            gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")
            if gpkg_layer.isValid():
                project.addMapLayer(gpkg_layer, addToLegend=False)
                group.addLayer(gpkg_layer)

        return {self.OUTPUT_GPKG: gpkg_path}
