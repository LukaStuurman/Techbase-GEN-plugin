# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterMatrix,
                       QgsProcessingParameterString,
                       QgsProcessingParameterBoolean,
                       QgsField,
                       QgsFeature,
                       QgsFeatureRequest,
                       QgsGeometry,
                       QgsWkbTypes,
                       QgsMessageLog,
                       Qgis)
import re
import math
from ls_netontwerp_wizard.bag_current_rules import has_residential_usage, is_bag_object

# ==============================================================================
# 1. STANDAARD CONFIGURATIE (DEFAULTS)
# ==============================================================================

DEF_WOONHUIS = [
    "hoekwoning", 5.5, "tussen/geschakeld", 5.5, "twee-onder-een-kap", 6.3, 
    "vrijstaand", 7.5, "appartement", 4.5, "onbekend", 5.9
]

DEF_WOONHUIS_2022 = [
    "hoekwoning", 5.3, "tussen/geschakeld", 5.3, "twee-onder-een-kap", 5.9, 
    "vrijstaand", 7.0, "appartement", 4.2, "onbekend", 5.6
]

DEF_WOONHUIS_KABEL = [
    "hoekwoning", 6.4, "tussen/geschakeld", 6.4, "twee-onder-een-kap", 7.1, 
    "vrijstaand", 8.1, "appartement", 5.4, "onbekend", 6.8
]

DEF_WOONHUIS_KABEL_2022 = [
    "hoekwoning", 6.3, "tussen/geschakeld", 6.3, "twee-onder-een-kap", 6.8, 
    "vrijstaand", 7.5, "appartement", 5.1, "onbekend", 6.4
]

DEF_WOONHUIS_OPWEK = [
    "hoekwoning", 5.7, "tussen/geschakeld", 5.7, "twee-onder-een-kap", 6.8, 
    "vrijstaand", 8.9, "appartement", 0, "onbekend", 5.7
]

DEF_WOONHUIS_OPWEK_KABEL = [
    "hoekwoning", 5.9, "tussen/geschakeld", 5.9, "twee-onder-een-kap", 7, 
    "vrijstaand", 9.2, "appartement", 0, "onbekend", 5.9
]

DEF_AMP_GLOBAL = [
    0, 34, 8.7, 0,
    34, 40, 32, 0,
    40, 50, 44, 0,
    50, 63, 51, 0,
    63, 80, 65, 0,
    80, 100, 85, 0,
    100, 125, 106, 0,
    125, 160, 138, 0,
    160, 200, 210, 0,
    200, 250, 210, 0,
    250, 99999, 0, 0.85
]

DEF_TYPE_CFG = [
    0, "Overig", 0.0, 1, 0, 0,
    1, "Woon", 0.0, 1, 1, 0,
    4, "Appartement", 0.0, 1, 1, 0, 
    8, "Laad", 0.0, 0, 0, 0,
    9, "Straat", 0.0, 0, 0, 1,
    10, "Zakelijk", 0.0, 1, 0, 0
]

DEF_STRAAT = [0, 35, 5.8, 40, 50, 22, 63, 80, 36]
DEF_LAAD = [0, 35, 3.7, 40, 50, 22, 63, 80, 36]
DEF_LAAD_KABEL = [0, 35, 4.8, 40, 50, 22, 63, 80, 36]

DEF_GAS_ADVIES = [
    "G10-G25", 34, 50,
    "G10-G25", 50, 80,
    "G10-G25", 80, 160,
    "G10-G25", 250, 250,
    ">G25", 250, 250
]

DEF_GAS_ADVIES_KABEL = [
    "G10-G25", 34, 50,
    "G10-G25", 50, 80,
    "G10-G25", 80, 80,
    "G10-G25", 9999, 250,
    ">G25", 80, 80,
    ">G25", 250, 250
]

DEF_REGEX = [
    r"(^|\W)(riool|fontein|putkast|pompgemaal)", 9,
    r"(^|\W)(ov[\- ]?kast|vri[\- ]?kast|parkeer|slagboom|verkeer|brug|sluis)", 9,
    r"(^|\W)(abri|bushalte|reclame|cai|telecom|telefoon|sirene|camera|flits|bord)", 9,
    r"(^|\W)(verlichting|mast|lantaarn|marktkast|kermis|feest|afval|vuil|container|toilet|urinoir)", 9,
    r"(^|\W)(bouwaansluiting)", 9
]

DEF_KEYWORDS = [
    "appartement, flat, etagewoning, etagebouw, galerijwoning, portiekwoning, maisonnette, wozoco, hoogbouw", 4,
    "ov-kast, ov kast, abri, bushalte, openbare verlichting, straatmeubilair, diversen (niet zijnde gebouwen)", 9,
    "woonhuis, woonfunctie, aansluiting, vrijstaande woning, twee onder een kap, 2-onder-1-kap, eengezinswoning, villa, woonboot, rijtjeswoning, hoekwoning, tussenwoning", 1,
    "oplaadpunt, laadpunt, laadinfrastructuur, elektrisch vervoer,  ev ", 8,
    "bijeenkomstfunctie, kantoor, winkel, school, bedrijf, horeca, kerk, sport, loods, garage", 10
]

# ==============================================================================
# 2. REKENLOGICA
# ==============================================================================

def clean_text(s):
    if not s: return ""
    return str(s).lower().strip()

def parse_doorlaat(s):
    if not s: return (0, 0.0)
    s_lower = s.lower()
    
    m = re.search(r"^\s*(\d)\s*[x×]\s*(\d{1,3})", s_lower)
    if m: return (int(m.group(1)), float(m.group(2)))
    
    m = re.search(r"(\d)\s*fase.*?(\d{1,3})", s_lower)
    if m: return (int(m.group(1)), float(m.group(2)))
    
    m = re.search(r"(\d{1,3})\s*a\b", s_lower)
    if m: return (3, float(m.group(1)))
    
    return (0, 0.0)

def normalize_gas(gas_str):
    t = str(gas_str).upper().strip()
    if not t or t in ["ONBEKEND", "NVT", "N.V.T.", "N/A", "GEEN", "NULL", "NONE"]: 
        return "G4/G6/Geen"
    t = t.replace("&GT;", ">").replace("&LT;", "<").replace(" ", "").replace("TM", "T/M")
    
    if "GEEN" in t: return "G4/G6/Geen"
    if ">G25" in t or "G>25" in t or ">=G25" in t or "=>G25" in t or ">25" in t: return ">G25"
    if "G10" in t: return "G10-G25"
    
    m = re.search(r"G(\d+)", t)
    if m:
        n = int(m.group(1))
        if n <= 25 and n >= 10: return "G10-G25"
        if n > 25: return ">G25"
    return "G4/G6/Geen"

def get_gas_advies(gas_cat, el_amp, gas_config):
    for row in gas_config:
        if row['cat'] == gas_cat:
            if el_amp <= row['max_el']: 
                return row['advies']
    return -1

def map_gebruiksdoel(gebruiksdoel, type_woning, config):
    g = clean_text(gebruiksdoel)
    tw = clean_text(type_woning)
    if not g or g in ["onbekend", "n.v.t.", "nvt", "null"]:
        if tw and tw not in ["onbekend", "null", ""]: return 1 
        
    for pattern, type_id in config['REGEX_MAP']:
        try:
            if re.search(pattern, g): return type_id
        except: pass
        
    for keywords_list, type_id in config['GEBRUIKS_MAP']:
        for kw in keywords_list:
            if kw in g: return type_id
            
    return 10 

def woonhuis_ontwerp(type_woning, wh_table):
    t = clean_text(type_woning)
    if "hoekwoning" in t: return wh_table.get("hoekwoning", 7.0)
    if "tussen" in t or "geschakeld" in t: return wh_table.get("tussen/geschakeld", 7.0)
    if "twee-onder-een-kap" in t or "2-onder-1-kap" in t: return wh_table.get("twee-onder-een-kap", 8.0)
    if "vrijstaand" in t: return wh_table.get("vrijstaand", 9.5)
    if "appartement" in t: return wh_table.get("appartement", 5.5)
    return wh_table.get("onbekend", 7.6)

def amp_to_ontwerp(amp, amp_table):
    for row in amp_table:
        if row['min'] < amp <= row['max']:
            if row['fac'] > 0: return round(amp * row['fac'], 1)
            else: return row['fix']
        elif row['min'] == 0 and amp <= row['max']:
             if row['fac'] > 0: return round(amp * row['fac'], 1)
             else: return row['fix']
    return 0.0

def parse_bouwjaar(val):
    try:
        if val is None: return 0
        return int(float(val))
    except: 
        return 0

def calculate_ontwerpstroom(doorlaat, gebruiksdoel, type_woning, bouwjaar_raw, ld_gas_type, config, fid, feedback, use_1fase_exc, default_appartement_zonder_doorlaat=True):
    fases, el_amp = parse_doorlaat(doorlaat)
    g_type = map_gebruiksdoel(gebruiksdoel, type_woning, config)
    type_cfg = config['TYPES'].get(g_type, config['TYPES'][0])
    bouwjaar = parse_bouwjaar(bouwjaar_raw)
    grens_jaar = config['DEFAULTS'].get('bouwjaar_grens', 2022)
    is_nieuwbouw = (bouwjaar >= grens_jaar)

    if is_bag_object(doorlaat):
        if not has_residential_usage(gebruiksdoel) or not clean_text(type_woning) or clean_text(type_woning) == "null":
            return 0.0
        table = config.get('WOONHUIS_2022') if is_nieuwbouw else None
        return float(woonhuis_ontwerp(type_woning, table or config['WOONHUIS']))

    if fases == 0 and g_type == 9:
        # Zonder doorlaatwaarde krijgt straatmeubilair de standaard 3x25A-rij.
        for row in config.get('STRAAT', []):
            if row['min'] <= 25 <= row['max']:
                return float(row['val'])
        if type_cfg.get('use_straat'):
            return float(config['DEFAULTS'].get('straat_fallback', 5.8))

    if fases == 0:
        woning_text = clean_text(type_woning)
        gebruik_text = clean_text(gebruiksdoel)
        is_appartement = (
            g_type == 4
            or "appartement" in woning_text
            or any(
                keyword in gebruik_text
                for keyword in (
                    "flat", "etagewoning", "etagebouw", "galerijwoning",
                    "portiekwoning", "maisonnette", "wozoco", "hoogbouw"
                )
            )
        )
        if default_appartement_zonder_doorlaat and is_appartement:
            table_to_use = config['WOONHUIS']
            if is_nieuwbouw and config.get('WOONHUIS_2022'):
                table_to_use = config['WOONHUIS_2022']
            return float(table_to_use.get("appartement", 5.5))
        return 0.0

    limit_fase = config['DEFAULTS'].get('limit_fase', 3)
    limit_amp = config['DEFAULTS'].get('limit_amp', 40)

    # Boven de ampèregrens wordt een huishoudelijke aansluiting zakelijk gerekend.
    # Voor deze grens tellen 1- en 2-fase als 3-fase; precies 40A blijft huishoudelijk.
    is_heavy_woon = (fases > 0 and el_amp > limit_amp)

    val = 0.0
    
    # 1. Fixed
    if type_cfg['fixed'] > 0: 
        val = type_cfg['fixed']
        
    # 2. Woon/Appartement
    elif g_type in [1, 4]: 
        if is_heavy_woon:
            if type_cfg['use_amp']: 
                val = amp_to_ontwerp(el_amp, config['AMP_GLOBAL'])
        else:
            in_band = (fases >= limit_fase and el_amp <= limit_amp) or (fases > 0 and fases < limit_fase)
            if (g_type == 4) or in_band:
                if type_cfg['use_woon']: 
                    table_to_use = config['WOONHUIS']
                    if is_nieuwbouw and 'WOONHUIS_2022' in config and config['WOONHUIS_2022']:
                        table_to_use = config['WOONHUIS_2022']
                    val = woonhuis_ontwerp(type_woning, table_to_use)
                    
    # 3. Laad
    elif g_type == 8: 
        found_in_laad = False
        for row in config.get('LAAD', []):
             if row['min'] <= el_amp <= row['max']:
                 val = row['val']
                 found_in_laad = True
                 break
        if not found_in_laad:
            if type_cfg['use_amp']: val = amp_to_ontwerp(el_amp, config['AMP_GLOBAL'])
            else: val = config['DEFAULTS']['laad_fallback']
            
    # 4. Straat
    elif g_type == 9: 
        found_in_straat = False
        if type_cfg['use_straat']:
            for row in config['STRAAT']:
                if row['min'] <= el_amp <= row['max']:
                    val = row['val']
                    found_in_straat = True
                    break
        if not found_in_straat and el_amp > 0: 
            val = amp_to_ontwerp(el_amp, config['AMP_GLOBAL'])
            
    # 5. Zakelijk / Overig
    else: 
        if type_cfg['use_amp']: 
            val = amp_to_ontwerp(el_amp, config['AMP_GLOBAL'])
        
    # --- GAS CORRECTIE ---
    val_gas = 0.0
    gas_cat = normalize_gas(ld_gas_type)
    
    # Gas is not applicable to public charging points or street furniture.
    # Also ignore it for light single-phase residential connections when the
    # corresponding exception is enabled.
    ignore_gas = (g_type in [8, 9]) or (
        use_1fase_exc and g_type in [1, 4] and fases < limit_fase and el_amp <= limit_amp
    )
    
    if not ignore_gas:
        if el_amp > 0:
            trafo_amp = get_gas_advies(gas_cat, el_amp, config['GAS_ADVIES'])
            if trafo_amp > 0: 
                val_gas = amp_to_ontwerp(trafo_amp, config['AMP_GLOBAL'])
        gas_is_heavy = (gas_cat in [">G25", "G10-G25"])
    else:
        gas_is_heavy = False
    
    # Combineer gas en reguliere ontwerpstroom
    final_val = 0.0
    if val > 0:
        if gas_is_heavy and val_gas > val: final_val = val_gas
        else: final_val = val
    else:
        unknown_ok = (fases >= limit_fase and el_amp <= limit_amp) or (fases > 0 and fases < limit_fase)
        table_fallback = config['WOONHUIS']
        if is_nieuwbouw and 'WOONHUIS_2022' in config and config['WOONHUIS_2022']:
            table_fallback = config['WOONHUIS_2022']
            
        val_fallback = woonhuis_ontwerp(type_woning, table_fallback) if unknown_ok else 0.0
        
        if val_fallback > 0:
             if gas_is_heavy and val_gas > val_fallback: final_val = val_gas
             else: final_val = val_fallback
        else: 
            final_val = val_gas if val_gas > 0 else 0.0
            
    return final_val


def calculate_opwek_ontwerpstroom(doorlaat, gebruiksdoel, type_woning, ld_gas_type, opwek_table, config, normal_val, use_1fase_exc):
    if is_bag_object(doorlaat):
        if not has_residential_usage(gebruiksdoel) or not clean_text(type_woning) or clean_text(type_woning) == "null":
            return 0.0
        usage = "appartement" if "appartement" in clean_text(type_woning) else "woonhuis"
        return calculate_opwek_ontwerpstroom(None, usage, type_woning, "", opwek_table, config, normal_val, use_1fase_exc)
    fases, el_amp = parse_doorlaat(doorlaat)
    g_type = map_gebruiksdoel(gebruiksdoel, type_woning, config)
    
    zero_ids = config.get('OPWEK_RULES', {}).get('zero_ids', [4, 8, 9])
    zero_text = config.get('OPWEK_RULES', {}).get('zero_text', 'appartement')
    
    limit_fase = config['DEFAULTS'].get('limit_fase', 3)
    limit_amp = config['DEFAULTS'].get('limit_amp', 40)
    
    is_heavy_woon = (fases > 0 and el_amp > limit_amp)
    
    # Eea-0205.K 3.2: zware woon/appartement-aansluitingen worden via de
    # ampere-/zakelijke tabel berekend. Opwek volgt daar dezelfde waarde als
    # verbruik en mag niet eerst door de appartement/hoogbouw-nulregel vallen.
    if g_type in [1, 4] and is_heavy_woon:
        return normal_val
    
    # 0-regels gelden alleen voor reguliere categorieen waarvoor het kader
    # expliciet geen opwek-ontwerpstroom voorschrijft.
    if g_type in zero_ids: 
        return 0.0
    if zero_text and zero_text in clean_text(type_woning) and g_type == 1: 
        return 0.0
    
    # Specifieke Woonhuis Opwek Logica
    if g_type == 1:
        val_opwek = woonhuis_ontwerp(type_woning, opwek_table)
        
        # Gas correctie berekenen voor opwek
        val_gas = 0.0
        gas_cat = normalize_gas(ld_gas_type)
        ignore_gas = (
            use_1fase_exc and g_type == 1 and fases < limit_fase and el_amp <= limit_amp
        )
        
        if not ignore_gas:
            if el_amp > 0:
                trafo_amp = get_gas_advies(gas_cat, el_amp, config['GAS_ADVIES'])
                if trafo_amp > 0: 
                    val_gas = amp_to_ontwerp(trafo_amp, config['AMP_GLOBAL'])
            gas_is_heavy = (gas_cat in [">G25", "G10-G25"])
        else:
            gas_is_heavy = False
        
        if gas_is_heavy and val_gas > val_opwek: 
            return val_gas
        else: 
            return val_opwek
            
    return normal_val

# ==============================================================================
# 3. QGIS SPATIAL PLUGIN ALGORITHM
# ==============================================================================

class OntwerpstroomSpatial(QgsProcessingAlgorithm):
    INPUT_LAYER = 'INPUT_LAYER'
    INPUT_PANDEN = 'INPUT_PANDEN'
    FLD_DOORLAAT = 'FLD_DOORLAAT' 
    FLD_GEBRUIK = 'FLD_GEBRUIK'   
    FLD_GAS = 'FLD_GAS'           
    FLD_WONINGTYPE = 'FLD_WONINGTYPE' 
    FLD_BOUWJAAR = 'FLD_BOUWJAAR' 
    
    VAL_BOUWJAAR_GRENS = 'VAL_BOUWJAAR_GRENS' 
    VAL_LIMIT_FASE = 'VAL_LIMIT_FASE'
    VAL_LIMIT_AMP = 'VAL_LIMIT_AMP'
    VAL_1FASE_EXCEPTION = 'VAL_1FASE_EXCEPTION'
    VAL_APPARTEMENT_ZONDER_DOORLAAT = 'VAL_APPARTEMENT_ZONDER_DOORLAAT'
    
    MAT_WOONHUIS = 'MAT_WOONHUIS'
    MAT_WOONHUIS_2022 = 'MAT_WOONHUIS_2022' 
    MAT_WOONHUIS_KABEL = 'MAT_WOONHUIS_KABEL' 
    MAT_WOONHUIS_KABEL_2022 = 'MAT_WOONHUIS_KABEL_2022' 
    MAT_WOONHUIS_OPWEK = 'MAT_WOONHUIS_OPWEK'
    MAT_WOONHUIS_OPWEK_KABEL = 'MAT_WOONHUIS_OPWEK_KABEL'
    
    VAL_OPWEK_ZERO_IDS = 'VAL_OPWEK_ZERO_IDS'
    VAL_OPWEK_ZERO_TEXT = 'VAL_OPWEK_ZERO_TEXT'
    
    MAT_AMP = 'MAT_AMP'
    MAT_TYPE = 'MAT_TYPE'
    MAT_STRAAT = 'MAT_STRAAT'
    MAT_LAAD = 'MAT_LAAD'
    MAT_LAAD_KABEL = 'MAT_LAAD_KABEL' 
    MAT_GAS = 'MAT_GAS'
    MAT_GAS_KABEL = 'MAT_GAS_KABEL' 
    MAT_REGEX = 'MAT_REGEX'
    MAT_KEYWORDS = 'MAT_KEYWORDS'
    VAL_FALLBACK_LAAD = 'VAL_FALLBACK_LAAD'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return OntwerpstroomSpatial()

    def name(self):
        return 'Ontwerpstroom Tool TRAFO, KABEL & OPWEK KADER 2026 V5'

    def displayName(self):
        return self.tr('Ontwerpstroom Tool TRAFO, KABEL & OPWEK KADER 2026 V5')

    def group(self):
        return self.tr('GEN (XML) TOOLS')

    def groupId(self):
        return 'GEN (XML) TOOLS'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT_LAYER, self.tr('Input Layer'), [QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT_PANDEN, self.tr('Panden/Woning Laag'), [QgsProcessing.TypeVectorPolygon]))
        
        self.addParameter(QgsProcessingParameterField(self.FLD_DOORLAAT, self.tr('Veld: Doorlaat'), parentLayerParameterName=self.INPUT_LAYER, defaultValue='service_connection_type_type'))
        self.addParameter(QgsProcessingParameterField(self.FLD_GEBRUIK, self.tr('Veld: Gebruik'), parentLayerParameterName=self.INPUT_LAYER, defaultValue='Gebruiksdoel'))
        self.addParameter(QgsProcessingParameterField(self.FLD_GAS, self.tr('Veld: Gas'), parentLayerParameterName=self.INPUT_LAYER, defaultValue='G_Type'))
        
        self.addParameter(QgsProcessingParameterField(self.FLD_WONINGTYPE, self.tr('Veld: Woningtype (Panden)'), parentLayerParameterName=self.INPUT_PANDEN, defaultValue='Woningtype'))
        self.addParameter(QgsProcessingParameterField(self.FLD_BOUWJAAR, self.tr('Veld: Bouwjaar (Panden)'), parentLayerParameterName=self.INPUT_PANDEN, defaultValue='bouwjaar'))
        
        # Nieuwe Uitzondering Toggle
        self.addParameter(QgsProcessingParameterBoolean(self.VAL_1FASE_EXCEPTION, self.tr('Uitzondering 1-fase/2-fase woonhuizen (altijd tabelwaarde)'), defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.VAL_APPARTEMENT_ZONDER_DOORLAAT,
            self.tr('Appartement zonder doorlaatwaarde: gebruik standaard appartementwaarde'),
            defaultValue=True
        ))
        
        self.addParameter(QgsProcessingParameterNumber(self.VAL_BOUWJAAR_GRENS, self.tr('Grens Bouwjaar Nieuwbouw (>=)'), type=QgsProcessingParameterNumber.Integer, defaultValue=2022))
        
        # Grenswaarden Configuratie
        self.addParameter(QgsProcessingParameterNumber(self.VAL_LIMIT_FASE, self.tr('Grens Fase (Woonhuis -> Zakelijk)'), type=QgsProcessingParameterNumber.Integer, defaultValue=3))
        self.addParameter(QgsProcessingParameterNumber(self.VAL_LIMIT_AMP, self.tr('Grens Ampère (> Woonhuis = Zakelijk)'), type=QgsProcessingParameterNumber.Integer, defaultValue=40))

        # Matrices Woonhuis
        p_woon = QgsProcessingParameterMatrix(self.MAT_WOONHUIS, self.tr('Config: Woonhuis (Oud / < Grens)'))
        p_woon.setHeaders(['Type', 'Amp'])
        p_woon.setDefaultValue(DEF_WOONHUIS)
        self.addParameter(p_woon)

        p_woon_2022 = QgsProcessingParameterMatrix(self.MAT_WOONHUIS_2022, self.tr('Config: Woonhuis (Nieuw / >= Grens)'))
        p_woon_2022.setHeaders(['Type', 'Amp'])
        p_woon_2022.setDefaultValue(DEF_WOONHUIS_2022)
        self.addParameter(p_woon_2022)

        p_woon_kabel = QgsProcessingParameterMatrix(self.MAT_WOONHUIS_KABEL, self.tr('Config: Woonhuis Kabel (Oud / < Grens)'))
        p_woon_kabel.setHeaders(['Type', 'Amp'])
        p_woon_kabel.setDefaultValue(DEF_WOONHUIS_KABEL)
        self.addParameter(p_woon_kabel)

        p_woon_kabel_2022 = QgsProcessingParameterMatrix(self.MAT_WOONHUIS_KABEL_2022, self.tr('Config: Woonhuis Kabel (Nieuw / >= Grens)'))
        p_woon_kabel_2022.setHeaders(['Type', 'Amp'])
        p_woon_kabel_2022.setDefaultValue(DEF_WOONHUIS_KABEL_2022)
        self.addParameter(p_woon_kabel_2022)
        
        # Matrices Opwek
        p_woon_opwek = QgsProcessingParameterMatrix(self.MAT_WOONHUIS_OPWEK, self.tr('Config: Opwek Woonhuis (Trafo)'))
        p_woon_opwek.setHeaders(['Type', 'Amp'])
        p_woon_opwek.setDefaultValue(DEF_WOONHUIS_OPWEK)
        self.addParameter(p_woon_opwek)

        p_woon_opwek_kabel = QgsProcessingParameterMatrix(self.MAT_WOONHUIS_OPWEK_KABEL, self.tr('Config: Opwek Woonhuis (Kabel)'))
        p_woon_opwek_kabel.setHeaders(['Type', 'Amp'])
        p_woon_opwek_kabel.setDefaultValue(DEF_WOONHUIS_OPWEK_KABEL)
        self.addParameter(p_woon_opwek_kabel)

        self.addParameter(QgsProcessingParameterString(self.VAL_OPWEK_ZERO_IDS, self.tr('Opwek Regels: Type ID\'s die 0 worden (komma gescheiden)'), defaultValue='4, 8, 9'))
        self.addParameter(QgsProcessingParameterString(self.VAL_OPWEK_ZERO_TEXT, self.tr('Opwek Regels: Woningtype tekst filter (0 indien aanwezig in Woonfunctie)'), defaultValue='appartement', optional=True))
        
        # Matrices Overige Parameters
        p_amp = QgsProcessingParameterMatrix(self.MAT_AMP, self.tr('Config: Ampère'))
        p_amp.setHeaders(['Min', 'Max', 'Fix', 'Fac'])
        p_amp.setDefaultValue(DEF_AMP_GLOBAL)
        self.addParameter(p_amp)
        
        p_type = QgsProcessingParameterMatrix(self.MAT_TYPE, self.tr('Config: Types'))
        p_type.setHeaders(['ID', 'Naam', 'Fix', 'UseAmp', 'UseWoon', 'UseStraat'])
        p_type.setDefaultValue(DEF_TYPE_CFG)
        self.addParameter(p_type)
        
        p_straat = QgsProcessingParameterMatrix(self.MAT_STRAAT, self.tr('Config: Straat'))
        p_straat.setHeaders(['Min', 'Max', 'Val'])
        p_straat.setDefaultValue(DEF_STRAAT)
        self.addParameter(p_straat)

        p_laad = QgsProcessingParameterMatrix(self.MAT_LAAD, self.tr('Config: Laadpunten (Standaard)'))
        p_laad.setHeaders(['Min', 'Max', 'Val'])
        p_laad.setDefaultValue(DEF_LAAD)
        self.addParameter(p_laad)

        p_laad_kabel = QgsProcessingParameterMatrix(self.MAT_LAAD_KABEL, self.tr('Config: Laadpunten (Kabel)'))
        p_laad_kabel.setHeaders(['Min', 'Max', 'Val'])
        p_laad_kabel.setDefaultValue(DEF_LAAD_KABEL)
        self.addParameter(p_laad_kabel)

        p_gas = QgsProcessingParameterMatrix(self.MAT_GAS, self.tr('Config: Gas Advies (Standaard)'))
        p_gas.setHeaders(['Gas Categorie', 'Max Huidige El (A)', 'Advies (A, -1=eigen)'])
        p_gas.setDefaultValue(DEF_GAS_ADVIES)
        self.addParameter(p_gas)

        p_gas_kabel = QgsProcessingParameterMatrix(self.MAT_GAS_KABEL, self.tr('Config: Gas Advies (Kabel)'))
        p_gas_kabel.setHeaders(['Gas Categorie', 'Max Huidige El (A)', 'Advies (A, -1=eigen)'])
        p_gas_kabel.setDefaultValue(DEF_GAS_ADVIES_KABEL)
        self.addParameter(p_gas_kabel)

        p_regex = QgsProcessingParameterMatrix(self.MAT_REGEX, self.tr('Config: Regex'))
        p_regex.setHeaders(['Patroon', 'Type ID'])
        p_regex.setDefaultValue(DEF_REGEX)
        self.addParameter(p_regex)

        p_kw = QgsProcessingParameterMatrix(self.MAT_KEYWORDS, self.tr('Config: Trefwoorden'))
        p_kw.setHeaders(['Trefwoorden', 'Type ID'])
        p_kw.setDefaultValue(DEF_KEYWORDS)
        self.addParameter(p_kw)
        
        self.addParameter(QgsProcessingParameterNumber(self.VAL_FALLBACK_LAAD, self.tr('Fallback Laad'), type=QgsProcessingParameterNumber.Double, defaultValue=3.7))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr('Output Layer')))

    def processAlgorithm(self, parameters, context, feedback):
        def parse_woon(mat_name):
            raw = self.parameterAsMatrix(parameters, mat_name, context)
            cfg = {}
            for i in range(0, len(raw), 2):
                try: 
                    cfg[str(raw[i]).lower()] = float(raw[i+1])
                except: 
                    pass
            return cfg

        use_1fase_exc = self.parameterAsBool(parameters, self.VAL_1FASE_EXCEPTION, context)
        default_appartement_zonder_doorlaat = self.parameterAsBool(
            parameters, self.VAL_APPARTEMENT_ZONDER_DOORLAAT, context
        )
        
        cfg_woon = parse_woon(self.MAT_WOONHUIS)
        cfg_woon_2022 = parse_woon(self.MAT_WOONHUIS_2022) 
        cfg_woon_kabel = parse_woon(self.MAT_WOONHUIS_KABEL)
        cfg_woon_kabel_2022 = parse_woon(self.MAT_WOONHUIS_KABEL_2022) 
        
        cfg_woon_opwek = parse_woon(self.MAT_WOONHUIS_OPWEK)
        cfg_woon_opwek_kabel = parse_woon(self.MAT_WOONHUIS_OPWEK_KABEL)
        
        opwek_zero_ids_str = self.parameterAsString(parameters, self.VAL_OPWEK_ZERO_IDS, context)
        opwek_zero_ids = [int(x) for x in opwek_zero_ids_str.split(',') if x.strip().isdigit()]
        
        opwek_zero_text = self.parameterAsString(parameters, self.VAL_OPWEK_ZERO_TEXT, context).lower().strip()

        limit_fase = self.parameterAsInt(parameters, self.VAL_LIMIT_FASE, context)
        limit_amp = self.parameterAsInt(parameters, self.VAL_LIMIT_AMP, context)

        raw_amp = self.parameterAsMatrix(parameters, self.MAT_AMP, context)
        cfg_amp = []
        for i in range(0, len(raw_amp), 4):
            try: 
                cfg_amp.append({'min': float(raw_amp[i]), 'max': float(raw_amp[i+1]), 'fix': float(raw_amp[i+2]), 'fac': float(raw_amp[i+3])})
            except: pass
            
        raw_type = self.parameterAsMatrix(parameters, self.MAT_TYPE, context)
        cfg_types = {}
        for i in range(0, len(raw_type), 6):
            try: 
                cfg_types[int(float(raw_type[i]))] = {'fixed': float(raw_type[i+2]), 'use_amp': bool(float(raw_type[i+3])), 'use_woon': bool(float(raw_type[i+4])), 'use_straat': bool(float(raw_type[i+5]))}
            except: pass
            
        def parse_triplet(mat_name):
            raw = self.parameterAsMatrix(parameters, mat_name, context)
            cfg = []
            for i in range(0, len(raw), 3):
                try: 
                    cfg.append({'min': float(raw[i]), 'max': float(raw[i+1]), 'val': float(raw[i+2])})
                except: pass
            return cfg

        cfg_straat = parse_triplet(self.MAT_STRAAT)
        cfg_laad = parse_triplet(self.MAT_LAAD)
        cfg_laad_k = parse_triplet(self.MAT_LAAD_KABEL)

        def parse_gas(mat_name):
            raw = self.parameterAsMatrix(parameters, mat_name, context)
            cfg = []
            for i in range(0, len(raw), 3):
                try: 
                    cfg.append({'cat': str(raw[i]), 'max_el': float(raw[i+1]), 'advies': float(raw[i+2])})
                except: pass
            cfg.sort(key=lambda x: x['max_el']) 
            return cfg
            
        cfg_gas = parse_gas(self.MAT_GAS)
        cfg_gas_k = parse_gas(self.MAT_GAS_KABEL)

        raw_regex = self.parameterAsMatrix(parameters, self.MAT_REGEX, context)
        cfg_regex = []
        for i in range(0, len(raw_regex), 2):
            try: 
                cfg_regex.append((str(raw_regex[i]), int(float(raw_regex[i+1]))))
            except: pass

        raw_kw = self.parameterAsMatrix(parameters, self.MAT_KEYWORDS, context)
        cfg_kw = []
        for i in range(0, len(raw_kw), 2):
            try:
                kw_list = [k.strip().lower() for k in str(raw_kw[i]).split(',') if k.strip()]
                cfg_kw.append((kw_list, int(float(raw_kw[i+1]))))
            except: pass
            
        full_config_std = {
            'WOONHUIS': cfg_woon, 
            'WOONHUIS_2022': cfg_woon_2022, 
            'AMP_GLOBAL': cfg_amp, 
            'TYPES': cfg_types, 
            'STRAAT': cfg_straat, 
            'LAAD': cfg_laad,
            'GAS_ADVIES': cfg_gas, 
            'REGEX_MAP': cfg_regex, 
            'GEBRUIKS_MAP': cfg_kw,
            'OPWEK_RULES': {
                'zero_ids': opwek_zero_ids,
                'zero_text': opwek_zero_text
            },
            'DEFAULTS': {
                'laad_fallback': self.parameterAsDouble(parameters, self.VAL_FALLBACK_LAAD, context),
                'bouwjaar_grens': self.parameterAsInt(parameters, self.VAL_BOUWJAAR_GRENS, context),
                'limit_fase': limit_fase,
                'limit_amp': limit_amp
            }
        }
        
        full_config_kabel = full_config_std.copy()
        full_config_kabel['WOONHUIS'] = cfg_woon_kabel
        full_config_kabel['WOONHUIS_2022'] = cfg_woon_kabel_2022 
        full_config_kabel['LAAD'] = cfg_laad_k
        full_config_kabel['GAS_ADVIES'] = cfg_gas_k 

        source_points = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        source_panden = self.parameterAsSource(parameters, self.INPUT_PANDEN, context)
        
        name_door = self.parameterAsString(parameters, self.FLD_DOORLAAT, context)
        name_gebr = self.parameterAsString(parameters, self.FLD_GEBRUIK, context)
        name_gas = self.parameterAsString(parameters, self.FLD_GAS, context)
        name_woning = self.parameterAsString(parameters, self.FLD_WONINGTYPE, context)
        name_bouwjaar = self.parameterAsString(parameters, self.FLD_BOUWJAAR, context)
        
        fields = source_points.fields()
        numeric_output_fields = [
            "Ontwerpstroom", "Ontwerpstroom kabel", 
            "Opwek ontwerpstroom", "Kabel opwek ontwerpstroom", 
            "Hoogste Trafo", "Hoogste Kabel"
        ]
        text_output_fields = [
            "Gevonden_Woningtype", "Gevonden_Bouwjaar"
        ]
        
        for f in numeric_output_fields:
            if fields.lookupField(f) < 0:
                fields.append(QgsField(f, QVariant.Double))
        for f in text_output_fields:
            if fields.lookupField(f) < 0:
                fields.append(QgsField(f, QVariant.String))
            
        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT, context, fields, source_points.wkbType(), source_points.sourceCrs())
        
        idx_door = fields.indexOf(name_door)
        idx_gebr = fields.indexOf(name_gebr)
        idx_gas = fields.indexOf(name_gas)
        
        total = source_points.featureCount()
        count = 0
        
        req_panden = QgsFeatureRequest()
        req_panden.setSubsetOfAttributes([name_woning, name_bouwjaar], source_panden.fields())
        
        for feat in source_points.getFeatures():
            if feedback.isCanceled(): 
                break
                
            attrs = feat.attributes()
            val_door = str(attrs[idx_door]) if idx_door >= 0 and attrs[idx_door] is not None else ""
            val_gebr = str(attrs[idx_gebr]) if idx_gebr >= 0 and attrs[idx_gebr] is not None else ""
            val_gas = str(attrs[idx_gas]) if idx_gas >= 0 and attrs[idx_gas] is not None else ""
            
            geom = feat.geometry()
            val_woning = ""
            val_bouwjaar = 0
            
            if geom:
                req_panden.setFilterRect(geom.boundingBox())
                found_pand = False
                
                for pand in source_panden.getFeatures(req_panden):
                    if pand.geometry().intersects(geom):
                        try: 
                            val_woning = str(pand[name_woning])
                        except: pass
                        try: 
                            raw_bj = pand[name_bouwjaar]
                            if raw_bj: val_bouwjaar = int(float(raw_bj))
                        except: pass
                        found_pand = True
                        break 
                
                if not found_pand:
                    geom_buf = geom.buffer(1.0, 5) 
                    req_panden.setFilterRect(geom_buf.boundingBox())
                    
                    for pand in source_panden.getFeatures(req_panden):
                        if pand.geometry().intersects(geom_buf):
                            try: 
                                val_woning = str(pand[name_woning])
                            except: pass
                            try: 
                                raw_bj = pand[name_bouwjaar]
                                if raw_bj: val_bouwjaar = int(float(raw_bj))
                            except: pass
                            break 
            
            if is_bag_object(val_door) and has_residential_usage(val_gebr) and clean_text(val_woning) in ("", "null", "none"):
                # A type explicitly chosen in the review page remains available
                # when there is no matching pand with a known housing type.
                type_index = feat.fields().lookupField("Gevonden_Woningtype")
                year_index = feat.fields().lookupField("Gevonden_Bouwjaar")
                if type_index >= 0 and clean_text(feat[type_index]) not in ("", "null", "none"):
                    val_woning = str(feat[type_index])
                    if not val_bouwjaar and year_index >= 0:
                        val_bouwjaar = parse_bouwjaar(feat[year_index])

            res_std = calculate_ontwerpstroom(val_door, val_gebr, val_woning, val_bouwjaar, val_gas, full_config_std, feat.id(), feedback, use_1fase_exc, default_appartement_zonder_doorlaat)
            res_kabel = calculate_ontwerpstroom(val_door, val_gebr, val_woning, val_bouwjaar, val_gas, full_config_kabel, feat.id(), feedback, use_1fase_exc, default_appartement_zonder_doorlaat)
            
            res_opwek_std = calculate_opwek_ontwerpstroom(val_door, val_gebr, val_woning, val_gas, cfg_woon_opwek, full_config_std, res_std, use_1fase_exc)
            res_opwek_kabel = calculate_opwek_ontwerpstroom(val_door, val_gebr, val_woning, val_gas, cfg_woon_opwek_kabel, full_config_kabel, res_kabel, use_1fase_exc)

            # Explicit BAG choices survive a general recalculation. A residential
            # table choice still follows the current pand unless manually overridden.
            if is_bag_object(val_door):
                def saved_text(name):
                    index = feat.fields().lookupField(name)
                    return str(feat[index]).strip() if index >= 0 else ""
                keep_choice = saved_text("HerstelHandmatig") == "1" or (
                    not has_residential_usage(val_gebr) and saved_text("HerstelCat") in
                    ("Huishoudelijk", "Zakelijk", "Oplaadpunt", "Straatmeubilair")
                )
                if keep_choice:
                    try:
                        saved = [float(feat[name]) for name in numeric_output_fields[:4]]
                        if all(math.isfinite(value) and value >= 0 for value in saved):
                            res_std, res_kabel, res_opwek_std, res_opwek_kabel = saved
                    except (KeyError, ValueError, TypeError):
                        pass
            
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(feat.geometry())
            new_attrs = list(attrs)
            new_attrs.extend([None] * (len(fields) - len(new_attrs)))
            new_feat.setAttributes(new_attrs)
            calculated = [
                float(res_std), 
                float(res_kabel), 
                float(res_opwek_std), 
                float(res_opwek_kabel), 
                float(max(res_std, res_opwek_std)), 
                float(max(res_kabel, res_opwek_kabel)), 
                val_woning, 
                str(val_bouwjaar)
            ]
            for name, value in zip(numeric_output_fields + text_output_fields, calculated):
                new_feat[name] = value
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)
            
            count += 1
            if count % 200 == 0:
                 feedback.setProgress(int(100 * count / total))
                 
        return {self.OUTPUT: dest_id}
