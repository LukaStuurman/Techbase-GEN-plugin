from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProviderRegistry,
    QgsVectorFileWriter,
    QgsVariantUtils,
)


def _parse_localized_number(value):
    """Parse numeric or text values with Dutch or international decimals."""
    if value is None:
        raise ValueError("lege waarde")
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        raise ValueError("lege waarde")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # Dutch notation, for example 1.234,5.
            text = text.replace(".", "").replace(",", ".")
        else:
            # International notation, for example 1,234.5.
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


class LaagspanningClusteringAlgorithm(QgsProcessingAlgorithm):
    """Kabelverbonden, aaneengesloten LS-clusters met nieuwe stations."""

    AANSLUITINGEN = "AANSLUITINGEN"
    ONTWERPSTROOM_VELD = "ONTWERPSTROOM_VELD"
    MULTISTORY_VELD = "MULTISTORY_VELD"
    FLATKASTEN = "FLATKASTEN"
    FLATKAST_ID_VELD = "FLATKAST_ID_VELD"
    BAG_API_URL = "BAG_API_URL"
    KABELS = "KABELS"
    LS_FUNCTION_VELD = "LS_FUNCTION_VELD"
    LS_FUNCTION_WOORDEN = "LS_FUNCTION_WOORDEN"
    AANSLUITKABELS = "AANSLUITKABELS"
    AANSLUIT_FUNCTION_VELD = "AANSLUIT_FUNCTION_VELD"
    AANSLUIT_FUNCTION_WOORDEN = "AANSLUIT_FUNCTION_WOORDEN"
    SLEUVEN_NODEN = "SLEUVEN_NODEN"
    KNOOP_TOLERANTIE_M = "KNOOP_TOLERANTIE_M"
    REKEN_THREADS = "REKEN_THREADS"
    STATIONS = "STATIONS"
    STATION_NAAM_VELD = "STATION_NAAM_VELD"
    STATION_CAPACITEIT_VELD = "STATION_CAPACITEIT_VELD"
    STATIONOMTREKKEN = "STATIONOMTREKKEN"
    STATIONOMTREK_NAAM_VELD = "STATIONOMTREK_NAAM_VELD"
    VERDEELKASTEN = "VERDEELKASTEN"
    PLANGEBIED = "PLANGEBIED"
    ALLEEN_BINNEN_PLANGEBIED = "ALLEEN_BINNEN_PLANGEBIED"
    AUTOMATISCH_AANTAL = "AUTOMATISCH_AANTAL"
    AANTAL_NIEUWE = "AANTAL_NIEUWE"
    NIEUW_KVA = "NIEUW_KVA"
    VOORKEUR_BENUTTING = "VOORKEUR_BENUTTING"
    MAX_ROUTE_M = "MAX_ROUTE_M"
    SCHRIJF_SHAPEFILES = "SCHRIJF_SHAPEFILES"
    UITVOERMAP = "UITVOERMAP"

    AANSLUITINGEN_UIT = "AANSLUITINGEN_UIT"
    STATIONS_UIT = "STATIONS_UIT"
    GEBIEDEN_UIT = "GEBIEDEN_UIT"
    KABELROUTES_UIT = "KABELROUTES_UIT"
    SLEUVEN_GENOOD_UIT = "SLEUVEN_GENOOD_UIT"
    PLANGEBIED_UIT = "PLANGEBIED_UIT"
    OVERZICHT_CSV = "OVERZICHT_CSV"
    GEOPACKAGE = "GEOPACKAGE"
    CONTROLEKAART = "CONTROLEKAART"
    CONTROLEKAART_PDF = "CONTROLEKAART_PDF"
    QGIS_PROJECT = "QGIS_PROJECT"
    LAYOUT_TEMPLATE = "LAYOUT_TEMPLATE"

    def tr(self, text):
        return QCoreApplication.translate("LaagspanningClustering", text)

    def createInstance(self):
        return LaagspanningClusteringAlgorithm()

    def name(self):
        return "laagspanning_clustering_kabelverbonden"

    def displayName(self):
        return self.tr("Laagspanning clustering (kabelverbonden)")

    def group(self):
        return self.tr("Netontwerp")

    def groupId(self):
        return "netontwerp"

    def shortHelpString(self):
        return self.tr(
            """
Maakt aaneengesloten laagspanningsclusters die uitsluitend via hun eigen
kabelsubnet met het toegewezen station verbonden zijn. Kabels van een ander
cluster mogen dus niet nodig zijn om een aansluiting te bereiken.

Kies bij 'Ontwerpstroomkolom' het numerieke veld of tekstveld dat voor de
berekening moet worden gebruikt. Tekstwaarden met een decimale komma of punt
worden beide ondersteund en intern naar een getal omgezet. Als de keuze leeg
blijft, herkent de tool automatisch het
exacte veld 'Ontwerpstroom' of de shapefile-afkorting 'Ontwerpstro'/'Ontwerpstr'.
Bij automatische herkenning worden andere velden zoals Ontwerpstro_1 t/m
Ontwerpstro_5 genegeerd. De maximale stroom van een station is KVA / 0,23 / 3.
In het status-/KVA-veld is de laatste
KVA-waarde leidend; bij bijvoorbeeld '250 (630)' wordt 630 KVA gebruikt. De
benutting wordt bij voorkeur zo dicht mogelijk bij het ingestelde percentage
gebracht. Dit is een voorkeur en geen harde grens.

Voor appartementen kan optioneel een puntenlaag met flatkasten worden gekozen.
Kies daarbij het koppelveld in de aansluitingen (standaard `multistory`) en het
ID-veld in de flatkasten (standaard `id`). Aansluitingen en flatkast met dezelfde
waarde worden met een inpandige sleuf verbonden, mits de BAG OGC API bevestigt
dat zij bij hetzelfde BAG-pand horen. Ontbreekt een bruikbare flatkastkoppeling,
dan wordt de aansluiting eerst verbonden met de dichtstbijzijnde kabel binnen
hetzelfde BAG-pand en pas daarna met de dichtstbijzijnde kabel daarbuiten. De
inpandige sleuven worden wel als echte netwerklijnen opgeslagen en genood, maar
tellen met 0 meter mee voor de maximale station-aansluitingroute. De BAG API-URL
is instelbaar; standaard wordt de actuele PDOK BAG OGC API v2 gebruikt.

Bij 'Trafo-capaciteitskolom' kan het vermogensveld van de bestaande stations
expliciet worden gekozen. Leeg laten gebruikt automatische herkenning van
Status, KVA of Vermogen. Zowel kale numerieke waarden zoals `630`, waarden met
een komma of punt, als teksten zoals `250 (630)` of `630 kVA` worden ondersteund.
De tekst KVA is niet verplicht; het laatste getal blijft leidend. Stations met
NULL, een lege capaciteitswaarde of een waarde zonder getal worden genegeerd en
in het uitvoerlog vermeld.

De stationsnaamkolom van de bestaande stations kan expliciet worden gekozen.
Een optionele lijn- of polygoonlaag met stationomtrekken kan vierkanten rond de
stationpunten aan het kabelnet koppelen. Kies voor die laag de kolom met dezelfde
stationsnaam. Het stationpunt wordt intern met zijn omtrek verbonden en kabels
die de omtrek raken worden gezamenlijk als hetzelfde stationsknooppunt gebruikt.
Een optionele verdeelkastenlaag mag punten, lijnen of polygonen bevatten. Alle
kabels die dezelfde verdeelkast raken, of binnen de knooptolerantie eindigen,
worden door de verdeelkast met elkaar verbonden. Interne station-/kastverbindingen
hebben 0 meter rekenlengte maar blijven zichtbaar in het genode sleuvennet.

Het aantal nieuwe stations wordt standaard automatisch gekozen. De tool neemt
het kleinste capaciteitsgeldige alternatief waarvan de totale gemiddelde
benutting het dichtst bij het voorkeurspercentage ligt. Als dat aantal geen
geldige ruimtelijke stationsselectie oplevert, probeert de tool automatisch het
volgende kandidaat-aantal. Het handmatige aantal wordt alleen gebruikt wanneer
automatische keuze wordt uitgezet en geldt dan als exact aantal.

De maximale kabelroute is wel een harde grens. Iedere aansluiting moet vanaf
het eigen station bereikbaar zijn via maximaal deze lengte aan exclusieve
clusterkabel; een route mag nooit door het kabelgebied van een ander cluster.
Een gewone LS-aansluiting die de aangeleverde kabelgeometrie niet werkelijk
raakt, krijgt eerst een expliciete lijn naar de dichtstbijzijnde reguliere kabel.
Deze aangevulde aansluitkabel wordt genood, telt volledig mee in de maximale
route en dwingt het clustergebied de echte verbinding te volgen. Alleen de
afzonderlijk beschreven inpandige appartementverbindingen hebben 0 m rekenlengte.

Kies bij 'Laagspanningskabels' de hoofdnetlaag en optioneel een aparte laag
'Aansluitkabels'. Per laag kan de Function-kolom worden gekozen. In het
woordenveld staan één of meer woorden die in Function moeten voorkomen;
standaard is dit `LS`. Scheid meerdere woorden met een komma of puntkomma. Als
geen Function-kolom bestaat, wordt de volledige laag gebruikt. De gefilterde
lijnen van beide lagen worden samengevoegd voordat het kabelnet wordt gemaakt.

Met 'Sleuven automatisch knippen/noden' worden kruisingen en T-aftakkingen
eerst echte netwerkknooppunten. Kleine openingen bij een doodlopend lijnuiteinde
worden binnen de ingestelde knooptolerantie gesloten. Ook op de dichtstbijzijnde
kabelpositie van iedere LS-aansluiting en bestaand station wordt een knoop
ingevoegd. Bij twee kabellagen wordt dit gezamenlijk uitgevoerd, zodat ook
kruisingen en T-aansluitingen tussen de laagspannings- en aansluitkabels worden
geknipt. Dit gebeurt alleen intern; de gekozen bronlagen worden niet aangepast.

Als het veld GebiedLabel bruikbare labels in de vorm 'Trafo 1', 'Trafo 2',
enzovoort bevat, gebruikt de tool die als kandidaatlocaties. Zonder zulke labels
maakt de tool zelf kandidaatlocaties op het kabelnet. Een optioneel plangebied
kan worden opgegeven om de sleuven en uiteindelijke clustergebieden exact te
begrenzen. Aansluitingen buiten dit plangebied worden geweigerd. Het gekozen
plangebied wordt als blijvende resultaatlaag overgenomen.
Met 'Alleen objecten binnen plangebied gebruiken' worden aansluitingen en
bestaande stations buiten de grens genegeerd en worden de gebruikte kabels op
de grens afgeknipt. De ontwerpstroomsom en capaciteit worden dan uitsluitend
met de overblijvende objecten berekend. Als deze optie uitstaat, blijft een
aansluiting buiten het plangebied een foutmelding.

De uitvoer bevat geclusterde aansluitingen, stations, clustergebieden,
exclusieve kabelroutes, het volledige intern geknipte/genode sleuvennet, het
plangebied indien opgegeven, een
CSV-overzicht, controlekaart in PNG/PDF, een QGIS-project met alle
resultaatlagen en een losse QPT-layouttemplate. Het QGIS-project bevat de
bewerkbare A3 Print Layout `Clustering overzicht`; daarmee kunnen later opnieuw
PNG- en PDF-bestanden worden geexporteerd. De resultaatlagen verwijzen naar het
blijvende GeoPackage in dezelfde map en zijn dus geen tijdelijke lagen. Als
geen uitvoermap wordt gekozen, maakt de tool automatisch een gedateerde,
blijvende resultaatmap naast de LS-aansluitingen in plaats van in de
Windows-tempmap. Het QGIS-project en beide controlekaarten gebruiken
OpenStreetMap als achtergrond. De legenda staat in een apart zijpaneel buiten
het kaartvlak, zodat die nooit het plangebied of de routes afdekt. De kaart
heeft geen boventitel. In het zijpaneel staan een gecentreerde stationstabel en
een compacte, dikke noordpijl links van de legenda, waarbij beide exact op
dezelfde verticale middellijn staan. De tabel bevat onder meer
de maximale ontwerpstroom in ampere. Een rustige zwart-witte
zebra-coordinatenrand gebruikt een automatisch passend interval met ronde RD
New-waarden. Iedere interne zebra-overgang heeft hetzelfde coordinaatlabel en
een korte donkergrijze tick die exact vanaf de binnenrand van de zebra begint,
zonder in de zebra door te steken. De ticks staan onder de zebra in de
tekenvolgorde en zijn aan alle vier zijden fysiek even lang. Alleen donkergrijze plusjes markeren de
bijbehorende coordinatenkruisingen; er worden geen rasterlijnen getekend. In de
stationstabel en resultaatlagen staan eerst alle bestaande stations op nummer,
gevolgd door alle nieuwe stations op nummer. Elk gebied is een enkel aaneengesloten
polygoon zonder exclaves; de eigen kabelroute blijft volledig binnen het eigen
gebied.

Alle blijvende vectorresultaten staan standaard uitsluitend in GeoPackages.
De optionele instelling `Ook losse shapefiles schrijven` staat standaard uit
en is alleen bedoeld voor uitwisseling met oudere software.

De twee oorspronkelijke kabellagen worden daarnaast ongewijzigd in het
resultaat-GeoPackage en QGIS-project opgenomen. Ze krijgen categorie-symboliek
op de gekozen Function-kolom en staan standaard uitgevinkt, zodat ze alleen op
verzoek zichtbaar worden.
"""
        ).strip()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AANSLUITINGEN,
                self.tr("LS-aansluitingen"),
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.ONTWERPSTROOM_VELD,
                self.tr("Ontwerpstroomkolom, getal of tekst (leeg = automatisch)"),
                parentLayerParameterName=self.AANSLUITINGEN,
                defaultValue="Ontwerpstroom",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.MULTISTORY_VELD,
                self.tr("Appartement-/multistory-koppelkolom (leeg = multistory)"),
                parentLayerParameterName=self.AANSLUITINGEN,
                defaultValue="multistory_connection_id",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.FLATKASTEN,
                self.tr("Flatkasten (optionele puntenlaag)"),
                [QgsProcessing.TypeVectorPoint],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FLATKAST_ID_VELD,
                self.tr("Flatkast-ID-kolom (leeg = id)"),
                parentLayerParameterName=self.FLATKASTEN,
                defaultValue="id",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.BAG_API_URL,
                self.tr("BAG OGC API basis-URL"),
                defaultValue="https://api.pdok.nl/kadaster/bag/ogc/v2",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.KABELS,
                self.tr("Laagspanningskabels / sleuven"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LS_FUNCTION_VELD,
                self.tr("Function-kolom laagspanningskabels (leeg = automatisch)"),
                parentLayerParameterName=self.KABELS,
                defaultValue="function",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.LS_FUNCTION_WOORDEN,
                self.tr("Woorden in Function laagspanningskabels"),
                defaultValue="LS",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AANSLUITKABELS,
                self.tr("Aansluitkabels (optioneel aparte lijnlaag)"),
                [QgsProcessing.TypeVectorLine],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.AANSLUIT_FUNCTION_VELD,
                self.tr("Function-kolom aansluitkabels (leeg = automatisch)"),
                parentLayerParameterName=self.AANSLUITKABELS,
                defaultValue="function",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.AANSLUIT_FUNCTION_WOORDEN,
                self.tr("Woorden in Function aansluitkabels"),
                defaultValue="LS",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SLEUVEN_NODEN,
                self.tr(
                    "Sleuven automatisch knippen/noden op kruisingen, "
                    "T-aansluitingen en aansluitpunten"
                ),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KNOOP_TOLERANTIE_M,
                self.tr("Knooptolerantie voor bijna rakende lijnuiteinden (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.0,
                maxValue=25.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.REKEN_THREADS,
                self.tr("Aantal CPU-threads (0 = automatisch)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
                maxValue=64,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SCHRIJF_SHAPEFILES,
                self.tr("Ook losse shapefiles schrijven"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.STATIONS,
                self.tr("Bestaande stations"),
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.STATION_NAAM_VELD,
                self.tr("Stationsnaamkolom (leeg = automatisch)"),
                parentLayerParameterName=self.STATIONS,
                defaultValue="Station",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.STATION_CAPACITEIT_VELD,
                self.tr("Trafo-capaciteitskolom (leeg = Status/KVA automatisch)"),
                parentLayerParameterName=self.STATIONS,
                defaultValue="trafo_power",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.STATIONOMTREKKEN,
                self.tr("Stationomtrekken/vierkanten (optioneel)"),
                [QgsProcessing.TypeVectorLine, QgsProcessing.TypeVectorPolygon],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.STATIONOMTREK_NAAM_VELD,
                self.tr("Stationsnaamkolom van stationomtrekken"),
                parentLayerParameterName=self.STATIONOMTREKKEN,
                defaultValue="Station",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.VERDEELKASTEN,
                self.tr("Verdeelkasten als punt, lijn of polygoon (optioneel)"),
                [
                    QgsProcessing.TypeVectorPoint,
                    QgsProcessing.TypeVectorLine,
                    QgsProcessing.TypeVectorPolygon,
                ],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.PLANGEBIED,
                self.tr("Plangebied (optioneel)"),
                [QgsProcessing.TypeVectorPolygon],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLEEN_BINNEN_PLANGEBIED,
                self.tr("Alleen kabels, aansluitingen en stations binnen plangebied gebruiken"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.AUTOMATISCH_AANTAL,
                self.tr("Aantal nieuwe stations automatisch bepalen"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.AANTAL_NIEUWE,
                self.tr("Handmatig aantal nieuwe stations (alleen indien automatisch uit)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
                maxValue=50,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.NIEUW_KVA,
                self.tr("Vermogen per nieuw station (KVA)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=630.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.VOORKEUR_BENUTTING,
                self.tr("Voorkeursbenutting per station (%)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=90.0,
                minValue=1.0,
                maxValue=100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_ROUTE_M,
                self.tr("Maximale kabelroute station-aansluiting (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=850.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.UITVOERMAP,
                self.tr("Uitvoermap"),
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            )
        )

        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.AANSLUITINGEN_UIT, self.tr("Aansluitingen geclusterd")
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.STATIONS_UIT, self.tr("Stations ontwerp")
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.GEBIEDEN_UIT, self.tr("Aaneengesloten clustergebieden")
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.KABELROUTES_UIT,
                self.tr("Berekende exclusieve kabelroutes (uitvoer)"),
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.SLEUVEN_GENOOD_UIT,
                self.tr("Alle geknipte/genode sleufdelen"),
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.PLANGEBIED_UIT,
                self.tr("Plangebied (indien opgegeven)"),
            )
        )
        self.addOutput(
            QgsProcessingOutputFile(self.OVERZICHT_CSV, self.tr("Clusteroverzicht CSV"))
        )
        self.addOutput(
            QgsProcessingOutputFile(self.GEOPACKAGE, self.tr("Resultaat GeoPackage"))
        )
        self.addOutput(
            QgsProcessingOutputFile(self.CONTROLEKAART, self.tr("Controlekaart PNG"))
        )
        self.addOutput(
            QgsProcessingOutputFile(
                self.CONTROLEKAART_PDF, self.tr("Controlekaart PDF")
            )
        )
        self.addOutput(
            QgsProcessingOutputFile(
                self.QGIS_PROJECT,
                self.tr("QGIS-project met alle lagen en OpenStreetMap"),
            )
        )
        self.addOutput(
            QgsProcessingOutputFile(
                self.LAYOUT_TEMPLATE,
                self.tr("QGIS Print Layout-template"),
            )
        )

    @staticmethod
    def _automatic_field_index(
        source,
        exact_names,
        description,
        numeric=False,
        optional=False,
        prefix_names=(),
    ):
        fields = source.fields()
        indices = []
        for expected in exact_names:
            indices = [
                index
                for index, field in enumerate(fields)
                if field.name().casefold() == expected.casefold()
            ]
            if indices:
                break
        if not indices and prefix_names:
            indices = [
                index
                for index, field in enumerate(fields)
                if any(
                    field.name().casefold().startswith(prefix.casefold())
                    for prefix in prefix_names
                )
            ]
        if not indices:
            if optional:
                return None
            raise QgsProcessingException(
                f"Geen veld voor {description} gevonden. Verwacht: "
                + ", ".join(exact_names)
            )

        if numeric and len(indices) > 1:
            best_index = indices[0]
            best_count = -1
            for index in indices:
                count = 0
                for feature in source.getFeatures():
                    value = feature.attribute(index)
                    try:
                        _parse_localized_number(value)
                        count += 1
                    except (TypeError, ValueError):
                        pass
                if count > best_count:
                    best_index = index
                    best_count = count
            return best_index
        return indices[0]

    @staticmethod
    def _unique_field_name(name, used_names):
        base = name or "veld"
        candidate = base
        suffix = 2
        while candidate.casefold() in used_names:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used_names.add(candidate.casefold())
        return candidate

    def _function_field_index(self, source, selected_name, layer_description):
        """Resolve a chosen Function field, or detect a common spelling."""
        selected_name = str(selected_name or "").strip()
        if selected_name:
            index = source.fields().indexFromName(selected_name)
            if index < 0:
                index = next(
                    (
                        field_index
                        for field_index, field in enumerate(source.fields())
                        if field.name().casefold() == selected_name.casefold()
                    ),
                    -1,
                )
            if index < 0:
                raise QgsProcessingException(
                    f"De gekozen Function-kolom '{selected_name}' bestaat niet "
                    f"in {layer_description}."
                )
            return index
        return self._automatic_field_index(
            source,
            ("Function", "Functie", "Functiecode", "Func"),
            f"Function in {layer_description}",
            optional=True,
            prefix_names=("Function", "Functie"),
        )

    @staticmethod
    def _function_terms(raw_text):
        """Parse comma, semicolon or newline separated Function search words."""
        normalized = str(raw_text or "").replace("\r", "\n")
        for separator in (",", ";"):
            normalized = normalized.replace(separator, "\n")
        terms = []
        seen = set()
        for value in normalized.split("\n"):
            value = value.strip()
            folded = value.casefold()
            if value and folded not in seen:
                terms.append(value)
                seen.add(folded)
        return terms

    def _write_clean_source(
        self,
        source,
        path,
        layer_name,
        canonical_fields,
        context,
        feedback,
        progress_start,
        progress_end,
        drop_prefixes=(),
    ):
        """Write a source to one-layer GPKG with canonical calculation fields."""
        output_fields = QgsFields()
        attribute_indices = []
        selected_indices = {
            index for _, index, _ in canonical_fields if index is not None
        }
        reserved_names = {name.casefold() for name, _, _ in canonical_fields}
        used_names = set()

        for index, source_field in enumerate(source.fields()):
            folded_name = source_field.name().casefold()
            if (
                index in selected_indices
                or folded_name in reserved_names
                or any(folded_name.startswith(prefix.casefold()) for prefix in drop_prefixes)
            ):
                continue
            copied = QgsField(source_field)
            copied.setName(self._unique_field_name(copied.name(), used_names))
            output_fields.append(copied)
            attribute_indices.append(index)

        for name, _index, value_type in canonical_fields:
            output_fields.append(QgsField(name, value_type))
            used_names.add(name.casefold())

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        writer = QgsVectorFileWriter.create(
            str(path),
            output_fields,
            source.wkbType(),
            source.sourceCrs(),
            context.transformContext(),
            options,
        )
        if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
            message = "onbekende schrijffout" if writer is None else writer.errorMessage()
            raise QgsProcessingException(f"Kan tijdelijke laag niet schrijven: {message}")

        count = max(1, int(source.featureCount()))
        try:
            for row, feature in enumerate(source.getFeatures()):
                if feedback.isCanceled():
                    raise QgsProcessingException("Berekening geannuleerd.")
                output_feature = QgsFeature(output_fields)
                output_feature.setGeometry(feature.geometry())
                values = [feature.attribute(index) for index in attribute_indices]
                for _name, index, value_type in canonical_fields:
                    value = None if index is None else feature.attribute(index)
                    if value_type == QVariant.Double:
                        try:
                            value = _parse_localized_number(value)
                        except (TypeError, ValueError):
                            value = None
                    elif QgsVariantUtils.isNull(value):
                        value = ""
                    else:
                        value = str(value)
                    values.append(value)
                output_feature.setAttributes(values)
                if not writer.addFeature(output_feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(
                        f"Schrijven van {layer_name} is mislukt: {writer.lastError()}"
                    )
                if row % 250 == 0:
                    fraction = min(1.0, (row + 1) / count)
                    feedback.setProgress(
                        progress_start + fraction * (progress_end - progress_start)
                    )
        finally:
            del writer

    @staticmethod
    def _load_engine():
        engine_path = (
            Path(__file__).resolve().parent
            / "laagspanning_clustering_lib"
            / "maak_clustering_engine.py"
        )
        if not engine_path.exists():
            raise QgsProcessingException(
                f"De rekenkern ontbreekt naast de Processing-tool: {engine_path}"
            )
        module_name = "_laagspanning_clustering_engine"
        spec = importlib.util.spec_from_file_location(module_name, engine_path)
        if spec is None or spec.loader is None:
            raise QgsProcessingException("De rekenkern kan niet worden geladen.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _qgis_python_command():
        executable = Path(sys.executable)
        if "python" in executable.stem.casefold():
            return [str(executable)]
        candidates = []
        osgeo_root = os.environ.get("OSGEO4W_ROOT")
        if osgeo_root:
            candidates.append(Path(osgeo_root) / "bin" / "python-qgis.bat")
        prefix = Path(QgsApplication.prefixPath())
        if len(prefix.parents) >= 2:
            candidates.append(prefix.parents[1] / "bin" / "python-qgis.bat")
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]
        raise QgsProcessingException(
            "De aparte QGIS-Pythonomgeving voor het project is niet gevonden."
        )

    @staticmethod
    def _project_artifacts_valid(project_path, layout_path):
        """Verify both artifacts instead of trusting the worker exit code."""
        try:
            if project_path.stat().st_size < 512 or layout_path.stat().st_size < 512:
                return False
            with zipfile.ZipFile(project_path, "r") as archive:
                if archive.testzip() is not None:
                    return False
                project_members = [
                    name for name in archive.namelist() if name.casefold().endswith(".qgs")
                ]
                if len(project_members) != 1:
                    return False
                project_xml = archive.read(project_members[0])
                if b"clustering_ontwerp.gpkg" not in project_xml:
                    return False
            ET.parse(layout_path)
            return True
        except (OSError, ET.ParseError, zipfile.BadZipFile, KeyError):
            return False

    def _create_qgis_project_with_retries(
        self, project_runner, output_dir, copied_gpkg, feedback
    ):
        """Create and verify the QGIS artifacts, retrying QGIS 4.2 crashes."""
        project_path = output_dir / "clustering_ontwerp.qgz"
        layout_path = output_dir / "clustering_overzicht.qpt"
        # Never accept files left by an older run in a reused output folder.
        for artifact in (project_path, layout_path):
            try:
                artifact.unlink(missing_ok=True)
            except OSError as exc:
                raise QgsProcessingException(
                    f"Oud projectbestand kan niet worden vervangen: {artifact}. {exc}"
                ) from exc

        attempt_details = []
        process_log = output_dir / "qgis_project_creation.log"
        process_log.write_text("QGIS-project en printlayout maken\n", encoding="utf-8")
        for attempt in range(1, 4):
            if attempt > 1:
                feedback.pushInfo(
                    "QGIS 4.2-projectproces stopte onverwacht; automatische "
                    f"herstelpoging {attempt - 1} van 2..."
                )
                for artifact in (project_path, layout_path):
                    try:
                        artifact.unlink(missing_ok=True)
                    except OSError:
                        pass
            project_process = subprocess.run(
                [
                    *self._qgis_python_command(),
                    "-u",
                    str(project_runner),
                    str(output_dir),
                    str(copied_gpkg),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            for line in project_process.stdout.splitlines():
                feedback.pushInfo(line)
            with process_log.open("a", encoding="utf-8") as handle:
                handle.write(f"\nPoging {attempt}: code {project_process.returncode}\n")
                handle.write(project_process.stdout + "\n" + project_process.stderr + "\n")
            project_valid = self._project_artifacts_valid(project_path, layout_path)
            code_text = (
                str(project_process.returncode)
                if 0 <= project_process.returncode <= 255
                else (
                    f"{project_process.returncode} "
                    f"(0x{project_process.returncode & 0xFFFFFFFF:08X})"
                )
            )
            error_lines = [
                line.strip()
                for line in project_process.stderr.splitlines()
                if line.strip()
            ]
            error_lines.extend(line.strip() for line in project_process.stdout.splitlines() if "Waarschuwing:" in line)
            attempt_details.append(
                error_lines[-1]
                if error_lines
                else f"projectproces eindigde met code {code_text}"
            )
            if project_valid:
                if project_process.returncode != 0:
                    feedback.pushInfo(
                        "QGIS 4.2 meldde een afsluitfout, maar het QGIS-project "
                        "en de layout zijn volledig en geldig geschreven."
                    )
                return project_path, layout_path
        raise QgsProcessingException(
            "De clustering is berekend, maar het QGIS-project kon niet worden "
            "gemaakt na drie pogingen: "
            f"{attempt_details[-1]}\nProceslog: {process_log}"
        )

    def processAlgorithm(self, parameters, context, feedback):
        points = self.parameterAsSource(parameters, self.AANSLUITINGEN, context)
        cables = self.parameterAsSource(parameters, self.KABELS, context)
        connection_cables = self.parameterAsSource(
            parameters, self.AANSLUITKABELS, context
        )
        flat_cabinets = self.parameterAsSource(parameters, self.FLATKASTEN, context)
        stations = self.parameterAsSource(parameters, self.STATIONS, context)
        station_enclosures = self.parameterAsSource(
            parameters, self.STATIONOMTREKKEN, context
        )
        distribution_cabinets = self.parameterAsSource(
            parameters, self.VERDEELKASTEN, context
        )
        plan_area = self.parameterAsSource(parameters, self.PLANGEBIED, context)
        if points is None or cables is None or stations is None:
            raise QgsProcessingException("Een of meer invoerlagen konden niet worden geopend.")
        sources_with_crs = [points, cables, stations]
        if connection_cables is not None:
            sources_with_crs.append(connection_cables)
        if flat_cabinets is not None:
            sources_with_crs.append(flat_cabinets)
        if station_enclosures is not None:
            sources_with_crs.append(station_enclosures)
        if distribution_cabinets is not None:
            sources_with_crs.append(distribution_cabinets)
        if plan_area is not None:
            sources_with_crs.append(plan_area)
        if any(not source.sourceCrs().isValid() for source in sources_with_crs):
            raise QgsProcessingException("Alle invoerlagen moeten een geldige CRS hebben.")

        selected_design_name = self.parameterAsString(
            parameters, self.ONTWERPSTROOM_VELD, context
        ).strip()
        if selected_design_name:
            design_index = points.fields().indexFromName(selected_design_name)
            if design_index < 0:
                design_index = next(
                    (
                        index
                        for index, field in enumerate(points.fields())
                        if field.name().casefold() == selected_design_name.casefold()
                    ),
                    -1,
                )
            if design_index < 0:
                raise QgsProcessingException(
                    f"De gekozen ontwerpstroomkolom '{selected_design_name}' "
                    "bestaat niet in de LS-aansluitingenlaag."
                )
            design_field_mode = "handmatig gekozen"
        else:
            design_index = self._automatic_field_index(
                points,
                ("Ontwerpstroom", "Ontwerpstro", "Ontwerpstr"),
                "ontwerpstroom",
                numeric=True,
                prefix_names=("Ontwerpstro", "Ontwerpstr"),
            )
            design_field_mode = "automatisch gevonden"
        multistory_index = None
        flat_cabinet_id_index = None
        if flat_cabinets is not None:
            selected_multistory_name = self.parameterAsString(
                parameters, self.MULTISTORY_VELD, context
            ).strip()
            if selected_multistory_name:
                multistory_index = points.fields().indexFromName(
                    selected_multistory_name
                )
                if multistory_index < 0:
                    multistory_index = next(
                        (
                            index
                            for index, field in enumerate(points.fields())
                            if field.name().casefold()
                            == selected_multistory_name.casefold()
                        ),
                        -1,
                    )
            else:
                multistory_index = self._automatic_field_index(
                    points,
                    ("multistory", "multi_story", "flatkast_id", "flatkastid"),
                    "appartement-/multistory-koppeling",
                    optional=True,
                    prefix_names=("multistory", "multi_stor", "flatkast"),
                )
            if multistory_index is None or multistory_index < 0:
                raise QgsProcessingException(
                    "Er is een flatkastenlaag gekozen, maar geen bruikbare "
                    "multistory-koppelkolom in de LS-aansluitingen. Kies deze "
                    "kolom expliciet."
                )

            selected_flat_id_name = self.parameterAsString(
                parameters, self.FLATKAST_ID_VELD, context
            ).strip()
            if selected_flat_id_name:
                flat_cabinet_id_index = flat_cabinets.fields().indexFromName(
                    selected_flat_id_name
                )
                if flat_cabinet_id_index < 0:
                    flat_cabinet_id_index = next(
                        (
                            index
                            for index, field in enumerate(flat_cabinets.fields())
                            if field.name().casefold()
                            == selected_flat_id_name.casefold()
                        ),
                        -1,
                    )
            else:
                flat_cabinet_id_index = self._automatic_field_index(
                    flat_cabinets,
                    ("id", "flatkast_id", "flatkastid"),
                    "flatkast-ID",
                    optional=True,
                    prefix_names=("flatkast",),
                )
            if flat_cabinet_id_index is None or flat_cabinet_id_index < 0:
                raise QgsProcessingException(
                    "Er is een flatkastenlaag gekozen, maar geen bruikbaar "
                    "ID-veld gevonden. Kies het flatkast-ID-veld expliciet."
                )
            feedback.pushInfo(
                "Appartementkoppeling: LS-veld "
                f"'{points.fields()[multistory_index].name()}' naar flatkastveld "
                f"'{flat_cabinets.fields()[flat_cabinet_id_index].name()}'."
            )
        label_index = self._automatic_field_index(
            points,
            ("GebiedLabel",),
            "kandidaatlabels",
            optional=True,
        )
        label_has_values = label_index is not None and any(
            str(feature.attribute(label_index) or "").strip()
            for feature in points.getFeatures()
        )
        label_uses_station = False
        station_assignment_index = self._automatic_field_index(
            points, ("Station",), "bestaand voedend station", optional=True
        )
        if not label_has_values:
            if station_assignment_index is not None and any(
                str(feature.attribute(station_assignment_index) or "").strip()
                for feature in points.getFeatures()
            ):
                label_index = station_assignment_index
                label_has_values = True
                label_uses_station = True
        selected_station_name = self.parameterAsString(
            parameters, self.STATION_NAAM_VELD, context
        ).strip()
        if selected_station_name:
            station_name_index = stations.fields().indexFromName(
                selected_station_name
            )
            if station_name_index < 0:
                station_name_index = next(
                    (
                        index
                        for index, field in enumerate(stations.fields())
                        if field.name().casefold() == selected_station_name.casefold()
                    ),
                    -1,
                )
            if station_name_index < 0:
                raise QgsProcessingException(
                    f"De gekozen stationsnaamkolom '{selected_station_name}' "
                    "bestaat niet in de stationslaag."
                )
        else:
            station_name_index = self._automatic_field_index(
                stations,
                ("Stationsnaam", "Stationsnaa", "Station", "Naam"),
                "stationsnaam",
                prefix_names=("Stationsnaam", "Stationsnaa"),
            )
        station_enclosure_name_index = None
        if station_enclosures is not None:
            selected_enclosure_name = self.parameterAsString(
                parameters, self.STATIONOMTREK_NAAM_VELD, context
            ).strip()
            if selected_enclosure_name:
                station_enclosure_name_index = (
                    station_enclosures.fields().indexFromName(selected_enclosure_name)
                )
                if station_enclosure_name_index < 0:
                    station_enclosure_name_index = next(
                        (
                            index
                            for index, field in enumerate(station_enclosures.fields())
                            if field.name().casefold()
                            == selected_enclosure_name.casefold()
                        ),
                        -1,
                    )
            else:
                station_enclosure_name_index = self._automatic_field_index(
                    station_enclosures,
                    ("Stationsnaam", "Stationsnaa", "Station", "Naam"),
                    "stationsnaam van stationomtrekken",
                    optional=True,
                    prefix_names=("Stationsnaam", "Stationsnaa"),
                )
            if station_enclosure_name_index is None or station_enclosure_name_index < 0:
                raise QgsProcessingException(
                    "Er is een stationomtrekkenlaag gekozen, maar geen "
                    "stationsnaamkolom gevonden. Kies deze kolom expliciet."
                )
            feedback.pushInfo(
                "Stationomtrekken worden gekoppeld via veld "
                f"'{station_enclosures.fields()[station_enclosure_name_index].name()}'."
            )
        selected_capacity_name = self.parameterAsString(
            parameters, self.STATION_CAPACITEIT_VELD, context
        ).strip()
        if selected_capacity_name:
            status_index = stations.fields().indexFromName(selected_capacity_name)
            if status_index < 0:
                status_index = next(
                    (
                        index
                        for index, field in enumerate(stations.fields())
                        if field.name().casefold()
                        == selected_capacity_name.casefold()
                    ),
                    -1,
                )
            if status_index < 0:
                raise QgsProcessingException(
                    f"De gekozen trafo-capaciteitskolom "
                    f"'{selected_capacity_name}' bestaat niet in de stationslaag."
                )
            capacity_field_mode = "handmatig gekozen"
        else:
            status_index = self._automatic_field_index(
                stations,
                ("Status", "KVA", "Vermogen"),
                "status/KVA",
            )
            capacity_field_mode = "automatisch gevonden"
        feedback.pushInfo(
            f"Trafo-capaciteit {capacity_field_mode}: "
            f"'{stations.fields()[status_index].name()}'."
        )
        ls_function_index = self._function_field_index(
            cables,
            self.parameterAsString(parameters, self.LS_FUNCTION_VELD, context),
            "de laagspanningskabellaag",
        )
        ls_function_terms = self._function_terms(
            self.parameterAsString(parameters, self.LS_FUNCTION_WOORDEN, context)
        )
        connection_function_index = None
        connection_function_terms = []
        if connection_cables is not None:
            connection_function_index = self._function_field_index(
                connection_cables,
                self.parameterAsString(
                    parameters, self.AANSLUIT_FUNCTION_VELD, context
                ),
                "de aansluitkabellaag",
            )
            connection_function_terms = self._function_terms(
                self.parameterAsString(
                    parameters, self.AANSLUIT_FUNCTION_WOORDEN, context
                )
            )

        def describe_function_filter(layer_label, source, field_index, terms):
            if field_index is None:
                feedback.pushInfo(
                    f"{layer_label}: geen Function-kolom gevonden; alle lijnen "
                    "worden voor de clustering gebruikt."
                )
            elif terms:
                feedback.pushInfo(
                    f"{layer_label}: veld '{source.fields()[field_index].name()}', "
                    "Function bevat: " + ", ".join(terms)
                )
            else:
                feedback.pushInfo(
                    f"{layer_label}: woordenveld is leeg; alle Function-waarden "
                    "worden gebruikt."
                )

        describe_function_filter(
            "Laagspanningskabels",
            cables,
            ls_function_index,
            ls_function_terms,
        )
        if connection_cables is not None:
            describe_function_filter(
                "Aansluitkabels",
                connection_cables,
                connection_function_index,
                connection_function_terms,
            )

        total_current = 0.0
        populated = 0
        for feature in points.getFeatures():
            try:
                total_current += _parse_localized_number(
                    feature.attribute(design_index)
                )
                populated += 1
            except (TypeError, ValueError):
                pass
        if populated == 0:
            raise QgsProcessingException(
                f"De ontwerpstroomkolom '{points.fields()[design_index].name()}' "
                "bevat geen bruikbare numerieke waarden."
            )
        feedback.pushInfo(
            f"Ontwerpstroom {design_field_mode}: "
            f"'{points.fields()[design_index].name()}' (veldindex {design_index}), "
            f"{populated} waarden, "
            f"totaal {total_current:.1f} A."
        )
        if label_uses_station:
            feedback.pushInfo(
                "GebiedLabel is leeg; bestaand veld 'Station' wordt als "
                "topologische indelingshint gebruikt."
            )
        elif label_index is None:
            feedback.pushInfo(
                "Geen GebiedLabel gevonden; kandidaatlocaties worden automatisch gemaakt."
            )
        elif not label_has_values:
            feedback.pushInfo(
                "GebiedLabel is leeg; kandidaatlocaties worden automatisch gemaakt."
            )

        automatic_count = self.parameterAsBool(
            parameters, self.AUTOMATISCH_AANTAL, context
        )
        n_new = self.parameterAsInt(parameters, self.AANTAL_NIEUWE, context)
        new_kva = self.parameterAsDouble(parameters, self.NIEUW_KVA, context)
        target_utilization = (
            self.parameterAsDouble(parameters, self.VOORKEUR_BENUTTING, context)
            / 100.0
        )
        max_route_m = self.parameterAsDouble(parameters, self.MAX_ROUTE_M, context)
        write_shapefiles = self.parameterAsBool(
            parameters, self.SCHRIJF_SHAPEFILES, context
        )
        node_cables = self.parameterAsBool(parameters, self.SLEUVEN_NODEN, context)
        node_tolerance_m = self.parameterAsDouble(
            parameters, self.KNOOP_TOLERANTIE_M, context
        )
        requested_threads = self.parameterAsInt(
            parameters, self.REKEN_THREADS, context
        )
        logical_threads = max(1, os.cpu_count() or 1)
        calculation_threads = (
            max(1, logical_threads - 1)
            if requested_threads <= 0
            else max(1, min(requested_threads, logical_threads, 64))
        )
        os.environ["LS_NETONTWERP_THREADS"] = str(calculation_threads)
        os.environ["OMP_NUM_THREADS"] = str(calculation_threads)
        os.environ["OPENBLAS_NUM_THREADS"] = str(calculation_threads)
        os.environ["MKL_NUM_THREADS"] = str(calculation_threads)
        feedback.pushInfo(
            f"CPU-versnelling clustering: {calculation_threads} van "
            f"{logical_threads} logische processors."
        )
        only_within_plan = self.parameterAsBool(
            parameters, self.ALLEEN_BINNEN_PLANGEBIED, context
        )
        output_text = self.parameterAsString(parameters, self.UITVOERMAP, context)
        output_path = Path(output_text).resolve() if output_text else None
        system_temp = Path(tempfile.gettempdir()).resolve()
        output_is_temporary = (
            not output_text
            or output_text == QgsProcessing.TEMPORARY_OUTPUT
            or (
                output_path is not None
                and (
                    output_path == system_temp
                    or system_temp in output_path.parents
                )
            )
        )
        if output_is_temporary:
            input_layer = self.parameterAsVectorLayer(
                parameters, self.AANSLUITINGEN, context
            )
            input_directory = None
            if input_layer is not None and input_layer.isValid():
                decoded_uri = QgsProviderRegistry.instance().decodeUri(
                    input_layer.providerType(),
                    input_layer.dataProvider().dataSourceUri(),
                )
                source_path = decoded_uri.get("path")
                if source_path:
                    input_directory = Path(source_path).resolve().parent
            if input_directory is None:
                input_directory = Path.home() / "Documents"
            output_dir = input_directory / (
                "resultaat_clustering_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            feedback.pushInfo(
                "Geen blijvende uitvoermap gekozen; resultaten worden niet in "
                f"de Windows-tempmap geplaatst maar in: {output_dir}"
            )
        else:
            output_dir = output_path
            output_dir.mkdir(parents=True, exist_ok=True)

        work_dir = Path(tempfile.mkdtemp(prefix="ls_clustering_invoer_"))
        run_output = work_dir / "resultaat"
        try:
            feedback.pushInfo("Invoerlagen voorbereiden...")
            points_path = work_dir / "aansluitingen.gpkg"
            cables_path = work_dir / "ls_kabels.gpkg"
            connection_cables_path = work_dir / "aansluitkabels.gpkg"
            flat_cabinets_path = work_dir / "flatkasten.gpkg"
            stations_path = work_dir / "stations.gpkg"
            station_enclosures_path = work_dir / "stationomtrekken.gpkg"
            distribution_cabinets_path = work_dir / "verdeelkasten.gpkg"
            plan_path = work_dir / "plangebied.gpkg"
            self._write_clean_source(
                points,
                points_path,
                "aansluitingen",
                [
                    ("Ontwerpstroom", design_index, QVariant.Double),
                    ("GebiedLabel", label_index, QVariant.String),
                    ("Station", station_assignment_index, QVariant.String),
                    ("Multistory", multistory_index, QVariant.String),
                ],
                context,
                feedback,
                0,
                7,
                drop_prefixes=("Ontwerpstro",),
            )
            self._write_clean_source(
                cables,
                cables_path,
                "ls_kabels",
                [("Function", ls_function_index, QVariant.String)],
                context,
                feedback,
                7,
                13,
            )
            if connection_cables is not None:
                self._write_clean_source(
                    connection_cables,
                    connection_cables_path,
                    "aansluitkabels",
                    [
                        (
                            "Function",
                            connection_function_index,
                            QVariant.String,
                        )
                    ],
                    context,
                    feedback,
                    13,
                    17,
                )
            if flat_cabinets is not None:
                self._write_clean_source(
                    flat_cabinets,
                    flat_cabinets_path,
                    "flatkasten",
                    [("Flatkast_ID", flat_cabinet_id_index, QVariant.String)],
                    context,
                    feedback,
                    17,
                    18,
                )
            self._write_clean_source(
                stations,
                stations_path,
                "stations",
                [
                    ("Stationsnaa", station_name_index, QVariant.String),
                    ("Status", status_index, QVariant.String),
                ],
                context,
                feedback,
                17,
                19,
            )
            if station_enclosures is not None:
                self._write_clean_source(
                    station_enclosures,
                    station_enclosures_path,
                    "stationomtrekken",
                    [
                        (
                            "Stationsnaa",
                            station_enclosure_name_index,
                            QVariant.String,
                        )
                    ],
                    context,
                    feedback,
                    18,
                    19,
                )
            if distribution_cabinets is not None:
                self._write_clean_source(
                    distribution_cabinets,
                    distribution_cabinets_path,
                    "verdeelkasten",
                    [],
                    context,
                    feedback,
                    18,
                    19,
                )
            if plan_area is not None:
                self._write_clean_source(
                    plan_area,
                    plan_path,
                    "plangebied",
                    [],
                    context,
                    feedback,
                    19,
                    20,
                )

            feedback.setProgress(20)
            feedback.pushInfo("Kabelverbonden clustering berekenen...")
            engine = self._load_engine()
            engine.POINTS_PATH = points_path
            engine.CABLES_PATH = cables_path
            engine.CONNECTION_CABLES_PATH = (
                connection_cables_path if connection_cables is not None else None
            )
            engine.FLAT_CABINETS_PATH = (
                flat_cabinets_path if flat_cabinets is not None else None
            )
            engine.BAG_API_BASE_URL = (
                self.parameterAsString(parameters, self.BAG_API_URL, context).strip()
                or "https://api.pdok.nl/kadaster/bag/ogc/v2"
            )
            engine.LS_FUNCTION_TERMS = tuple(ls_function_terms)
            engine.LS_FUNCTION_FILTER_ENABLED = ls_function_index is not None
            engine.CONNECTION_FUNCTION_TERMS = tuple(connection_function_terms)
            engine.CONNECTION_FUNCTION_FILTER_ENABLED = (
                connection_cables is not None
                and connection_function_index is not None
            )
            engine.STATIONS_PATH = stations_path
            engine.STATION_ENCLOSURES_PATH = (
                station_enclosures_path if station_enclosures is not None else None
            )
            engine.DISTRIBUTION_CABINETS_PATH = (
                distribution_cabinets_path
                if distribution_cabinets is not None
                else None
            )
            engine.PLANGEBIED_PATH = plan_path if plan_area is not None else None
            engine.ONLY_WITHIN_PLAN_AREA = bool(only_within_plan)
            engine.OUT = run_output
            engine.N_NEW = n_new
            engine.NEW_KVA = new_kva
            engine.AUTO_NEW_STATIONS = automatic_count
            engine.TARGET_UTILIZATION = target_utilization
            engine.MAX_ROUTE_M = max_route_m
            engine.WRITE_SHAPEFILES = bool(write_shapefiles)
            engine.AUTO_NODE_CABLES = node_cables
            engine.NODE_TOLERANCE_M = node_tolerance_m
            engine.CPU_THREADS = calculation_threads
            engine.CREATE_QGIS_PROJECT = False

            def qgis_log(message):
                if feedback.isCanceled():
                    raise QgsProcessingException("Berekening geannuleerd.")
                feedback.pushInfo(str(message))

            engine.log = qgis_log
            engine.main()
            feedback.setProgress(95)

            shutil.copytree(run_output, output_dir, dirs_exist_ok=True)
            copied_gpkg = output_dir / "clustering_ontwerp.gpkg"
            # Keep every existing station available for the current-situation
            # layout, including stations not used in the final design.
            scope_stations = output_dir / "scope_stations_bron.gpkg"
            shutil.copy2(stations_path, scope_stations)
            scope_source = self.parameterAsVectorLayer(parameters, self.AANSLUITINGEN, context)
            try:
                station_colors = json.loads(str(scope_source.customProperty("LSNetontwerp/station_colors", "{}"))) if scope_source is not None else {}
            except (ValueError, TypeError):
                station_colors = {}
            (output_dir / "scope_invoer.json").write_text(json.dumps({
                "stations_uri": f"{scope_stations}|layername=stations",
                "station_field": "Stationsnaa",
                "station_colors": station_colors,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            feedback.pushInfo(
                "QGIS-project met resultaatlagen en OpenStreetMap maken..."
            )
            project_runner = (
                Path(__file__).resolve().parent
                / "laagspanning_clustering_lib"
                / "qgis_project_runner.py"
            )
            if not project_runner.exists():
                raise QgsProcessingException(
                    f"De QGIS-projectgenerator ontbreekt: {project_runner}"
                )
            self._create_qgis_project_with_retries(
                project_runner, output_dir, copied_gpkg, feedback
            )
            feedback.setProgress(100)
        except QgsProcessingException:
            raise
        except Exception as exc:
            raise QgsProcessingException(f"Clustering is mislukt: {exc}") from exc
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        gpkg = output_dir / "clustering_ontwerp.gpkg"
        if not gpkg.exists():
            raise QgsProcessingException("De rekenkern heeft geen resultaat-GeoPackage gemaakt.")

        feedback.pushInfo(f"Gereed. Resultaten staan in: {output_dir}")
        result = {
            self.UITVOERMAP: str(output_dir),
            self.AANSLUITINGEN_UIT: f"{gpkg}|layername=aansluitingen_geclusterd",
            self.STATIONS_UIT: f"{gpkg}|layername=stations_ontwerp",
            self.GEBIEDEN_UIT: f"{gpkg}|layername=clustergebieden",
            self.KABELROUTES_UIT: f"{gpkg}|layername=cluster_kabelroutes",
            self.SLEUVEN_GENOOD_UIT: f"{gpkg}|layername=sleuven_genood",
            self.OVERZICHT_CSV: str(output_dir / "cluster_overzicht.csv"),
            self.GEOPACKAGE: str(gpkg),
            self.CONTROLEKAART: str(output_dir / "clustering_overzicht.png"),
            self.CONTROLEKAART_PDF: str(output_dir / "clustering_overzicht.pdf"),
            self.QGIS_PROJECT: str(output_dir / "clustering_ontwerp.qgz"),
            self.LAYOUT_TEMPLATE: str(output_dir / "clustering_overzicht.qpt"),
        }
        if plan_area is not None:
            result[self.PLANGEBIED_UIT] = f"{gpkg}|layername=plangebied"
        return result
