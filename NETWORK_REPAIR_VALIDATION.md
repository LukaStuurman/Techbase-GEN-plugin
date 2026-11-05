# Plangebiedroutes en eenvoudige correctie — v1.31.0

## Wijzigingen

- Nieuwe automatische berekeningen gebruiken standaard **geen kabels buiten het plangebied**. Dit geldt voor het dashboard, 3a-opties, de workflow en Processing. Een eerder expliciet opgeslagen keuze blijft behouden. Zonder plangebied is er geen gebiedsgrens. De keuze voor buitenroutes blijft beschikbaar.
- Bij een mislukte clustering staan **Zoom naar kabelknelpunt** en **Ontbrekende verbinding tekenen** bij de foutuitleg. Zoom gebruikt het opgeslagen netwerkcontrolerapport en doorloopt de kabeldelen zonder bestaand station; als die ontbreken worden de beschikbare controlegeometrieën getoond. Dit zijn inspectiepunten, geen bewijs dat ieder getoond deel de oorzaak is. Bij ontbreken van gelokaliseerde diagnostiek volgt duidelijke uitleg en blijft het controleproject beschikbaar.
- Een getekende verbindingssleuf moet volledig binnen het plangebied vallen en beide uiteinden moeten binnen de ingestelde knooptolerantie op het bestaande kabelnet eindigen. Zij wordt apart als GeoPackage opgeslagen en bij een volgende automatische berekening met de kabelbron samengevoegd. De oorspronkelijke XML/Excel/kabelbestanden veranderen niet. Alleen een werkelijk bestaande of bewust ontworpen verbinding tekenen. Daarna **Automatische clustering** opnieuw starten; er wordt geen ongeldige berekening stilzwijgend goedgekeurd.
- Nogmaals op **Ontbrekende verbinding tekenen** klikken annuleert een actieve tekenronde. Een mislukte geometriecontrole slaat de lijn niet op. Eerdere verbindingssleuven blijven in het werkproject gekoppeld via het workflowbestand en worden bij een volgende getekende sleuf behouden. De sleuven worden bij de herberekening opnieuw genood. Er is geen algemene garantie dat één lijn alle netwerk- of capaciteitsproblemen oplost.
- In het gekleurde dashboard staat de normale correctie onder **4a. Aansluitingen herverdelen**. De overige 4b–4i-knoppen zitten achter **Geavanceerde clusterbewerkingen**. Ze blijven beschikbaar.
- In de correctiepagina: **Hele cluster: klik bronstation op kaart** selecteert alle aansluitingen van dat cluster en schakelt door naar de doelstationkeuze. Voor een deelverplaatsing selecteer je aansluitingen op de kaart en klik je het doelstation. De bestaande controle/toepassen-stap blijft staan; een kaartklik voert niet meteen een wijziging uit. Extra instellingen blijven achter **Geavanceerde instellingen en veiligheidscontroles**.

## Bestaande stations en nieuwe kandidaten

Bij vier onbenutte stations in de aangeleverde nieuwste Den Dungen-clustering bleek het interne stationpunt-omtreklijntje door numerieke projectie niet echt met de omtrek verbonden. Het station zat op een los netwerkstukje van twee knopen. De interne verbinding gebruikt nu een bestaande vertex van de eigen gelijknamige stationsomtrek. De interne rekenlengte blijft nul; de knooptolerantie wordt niet vergroot en er wordt geen willekeurige nabijgelegen hoofdkabel aangekoppeld.

Op het opgeslagen productienet is na heropbouw binnen 850 m bereikbaarheid aangetoond voor 044.532 (174 aansluitingen), 044.505 (152), 044.535 (897) en 044.524 (1.376). Dit zijn bereikbare punten, geen uiteindelijke clustergroottes. De handmatige volledige overzetting van N-08 naar 044.507 slaagt met alle controles; belasting wordt 569,9 A bij 579,71 A capaciteit.

Een nieuwe eindcontrole bij automatisch stationsaantal probeert een volledig nieuw kabelgebied door een bestaand station te laten overnemen. Overname vereist voldoende capaciteit en bereikbaarheid van alle betrokken aansluitingen via uitsluitend de twee betrokken kabelgebieden, binnen de maximale route. Derde kabelgebieden worden niet gebruikt. Deze stap bewijst geen wereldwijd minimaal stationsaantal en verdeelt niet willekeurig losse punten over meerdere stations. Vaste handmatig gevraagde aantallen worden hiermee niet gewijzigd.

## Tests en grenzen

Uitgevoerd in QGIS 4.2.3/PyQGIS met echte Qt-widgets:

- `test_external_plan_routes.py`: nieuwe standaard uit, expliciet aan/uit, opgeslagen keuze, echte omweg en volledige routelengte, plangebiedfilter en correctie/herberekening.
- `test_network_repair.py`: geldige verbinding, afwijzen van buitenplanlijn, los uiteinde en nulgeometrie; samenvoegen van blijvende aanvullingen zonder bronwijziging; echte tekenlaag met featureAdded-verwerking, GeoPackage-opslag en workflowherstel.
- `test_guided_cluster_editing.py`: daadwerkelijke bronstationklik → clusteraansluitingen → doelstationselectie met QGIS-selectiesignalen; bestaande zoek-, samenvoeg-, veiligheids-, kaartselectie- en workercontroles.
- `test_uniform_ui.py`: eenvoudige dashboardweergave en bereikbaarheid van de oude acties na aanvinken van Geavanceerd.
- `test_clustering_recovery.py`: foutverslag/controleproject, terugval, uitvoerbehoud en stroomcorrectie/undo.
- `test_station_enclosure_connection.py`: schuin getekende omtrek, exact gedeelde vertex, netwerkbereikbaarheid; overname van 519 + 51 A binnen 580 A, afwijzen bij overbelasting of onderbreking.
- Eerdere gerichte productieproeven voor de vier stations en N-08 zijn lokaal uitgevoerd zonder de oorspronkelijke productie-GeoPackage te overschrijven.

**Beperking:** de volledige Den Dungen-herberekening was bij voorbereiding van deze release nog niet afgerond. De release claimt daarvoor geen geslaagd nieuw totaalontwerp, definitief stationsaantal of complete route-/gebiedsvalidatie. Geen volledige handmatige Desktop-muistest of QGIS 3-uitvoering. De geautomatiseerde tekentest gebruikt echte QGIS-lagen en signalen met een nagebootste interface, geen fysieke muisbediening.
