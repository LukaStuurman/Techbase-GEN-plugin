# Testrelease 1.33.3-rc.1 — behoud bestaande stations en kabelgroepen

Datum: 5 november 2026. Concept-PR #29; geen merge naar main. Dit is een prerelease voor lokaal testen, geen goedgekeurd Den Dungen-netontwerp.

## Hersteld

- QGIS 4.2.3 gebruikt hier Shapely 2.1.2 en GEOS 3.14.1. Bij het samenvoegen van opeenvolgende rechte kabelstukken kon de grens tussen twee kabeltypen verdwijnen. De trace herstelt nu alle oorspronkelijke kabeleindpunten vóór het bepalen van type en lengte per deel. De verdeelkastproef met opeenvolgend 150Al en 120Al slaagt; conflicterende typen blijven afgewezen.
- De productiesolver-regressie neemt uitgestelde type-annotaties over bij het afzonderlijk laden van de solver.
- De pluginlaadtest selecteert de huidige Kader 3.2-keuze. De rekenregels zijn hierdoor niet aangepast.

## Uitgevoerde controles

Alle Python-bronnen zijn syntactisch gecontroleerd. Elf gerichte regressies slagen in de geïnstalleerde QGIS 4.2.3-Pythonomgeving: Kader 2.0, vergelijking 2.0/3.2, bestaande stationsretentie, originele groepsgeometrie, vergrendelde oude/uitsluitend nieuwe stations, afzonderlijke verdeelkastvoedingen, stationomtrekken, onbekende stationscapaciteit, buitenroutes, netwerkherstel en pluginladen.

De synthetische controle geeft 75 A voor teststation 044.529: 50 A via S07-00 naar B99-00/B99-01 en 25 A via S03-00. De aparte B99-01-beveiligingsproef geeft de overbelaste aansluiting vrij bij een ingestelde 63 A gG. De controle betreft synthetische geometrie en testwaarden, geen werkelijke meting aan station 044.529.

## Echte Den Dungen-proef

Rechtstreeks via PyQGIS/WorkflowRunner, zonder computerbediening, op aparte kopieën van de voorbereide netwerkbestanden van 5 november 2026, 11:45:06. De bronprojecten zijn niet overschreven.

- 2.763 aansluitingen in de bronlaag; 1.928 binnen het gebruikte plangebied, totaal 13.874,4 A voor het gekozen ontwerpstroomveld.
- 1.158 LS-hoofdkabels en 3.070 LS-aansluitkabels geselecteerd vóór de verdere gebiedsverwerking.
- 15 geldige bestaande stations na gebieds-/capaciteitsfilter. Stations 044.532 en 044.052 hebben geen bruikbare trafocapaciteit en zijn niet als capaciteit ingevuld.
- 31 verdeelkastobjecten verwerkt; het kabelnet is werkelijk genood.
- De run stopt vervolgens met: **Geen LS-aansluitingen met zowel een bestaand Station als een geldige volledige Kabel Subgroep gevonden. Controleer de Lovion/CSV-koppeling vóór deze behoudmodus.**
- De oorspronkelijke Station-koppeling ontbreekt in de nieuwste voorbereide aansluitingenlaag. In een oudere voorbereide laag met Station-kolom zijn alle 2.763 waarden NULL. Daarmee is oorspronkelijke stationsretentie op deze bestanden niet aantoonbaar.
- Het bestaande foutafhandelingspad heeft een blijvend QGIS-controleproject, invoerkopieën en diagnose gemaakt. Dat is een controle-uitvoer bij een geblokkeerde berekening, geen geslaagd clusterontwerp.

**Genuine GEN/XML/Excel/GeoPackage-data zijn aanwezig.** De ontbrekende gegevens zijn de betrouwbare oorspronkelijke stationskoppeling per aansluiting en de bevestigde geïnstalleerde richting-/verdeelkastzekeringen en actuele schakelingen. Deze release claimt geen geslaagde volledige praktijkvalidatie, geen actuele Lovion-validatie en geen test op QGIS 3.

## Installeren en testen

1. Installeer `ls_netontwerp_wizard-1.33.3-rc.1.zip` via QGIS → Plugins → Plugins beheren en installeren → Installeren vanuit ZIP. Herstart QGIS volledig; de reeds geopende sessie blijft anders oude code gebruiken.
2. Open een kopie van het voorbereide Den Dungen-werkproject op de Techbase-netwerkschijf. Gebruik de bijbehorende bronlagen, niet de reeds toegewezen nieuwe ontwerpclusters als historische waarheid.
3. Vul/verifieer de oorspronkelijke `Station` per aansluiting via de bestaande Lovion-/CSV- of gecontroleerde schemafunctie. Controleer volledige `Kabel Subgroep`, unieke aansluitings-ID's, kabeltypen/-geometrieën, trafovermogen en verdeelkasten. Leid de oorspronkelijke stationsnaam niet af uit nabijheid.
4. Kies **3a. Automatische clustering** en vink **Bestaande stations en kabelgroepen exact behouden** aan. De optie staat standaard uit. Gebruik een nieuwe uitvoermap.
5. Controleer de tabel `bestaande_stations_kabelgroepen_controle.csv`, de bestaande-richtingencontrolelaag en de behouden/vrijgegeven aansluitingen. Oude stations mogen uitsluitend hun eigen oorspronkelijke aansluitingen behouden; vrijgegeven/nieuwe aansluitingen mogen alleen naar nieuwe stations. Een ontbrekende fysieke scheiding of onduidelijke voeding mag geen geslaagd resultaat geven.
6. Zonder bevestigde geïnstalleerde gG is de berekende gG een adviesgrens. Vergelijk dit afzonderlijk met de werkelijke zekeringen en actuele schakelingen voordat het ontwerp wordt goedgekeurd.

De openbare release bevat uitsluitend software en deze samenvatting; geen Den Dungen-bronlagen of persoons-/adresgegevens. Lokale technische rapporten en het controleproject blijven bij het testpakket op de computer/netwerkschijf.
