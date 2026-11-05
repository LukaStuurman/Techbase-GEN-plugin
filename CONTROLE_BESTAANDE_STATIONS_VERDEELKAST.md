# Controlebestand – behoud bestaande stations en verdeelkast-richtingen

**Status:** Implementatie gekoppeld op de conceptbranch; Python-/elektrische regressies uitgevoerd via GitHub Actions. **Geen volledige QGIS-praktijkvalidatie** op het project van de gebruiker, daarom geen merge of release.

**Rapportbron:** Reproduceerbare synthetische RD-tests (`ls_netontwerp_wizard/test_existing_station_retention.py`, `test_existing_group_trace.py`, `test_existing_cabinet_feeders.py`, `test_locked_original_autocluster.py`). Het automatisch gegenereerde uitvoerpakket uit GitHub Actions bevat deze vier CSV's: `controle_stations.csv`, `controle_richtingen.csv`, `controle_kabeldelen.csv`, `controle_aansluitingen.csv` plus `controle_bestaande_stations_verdeelkasten.md`.

[Automatische controle en controlebestanden](https://github.com/LukaStuurman/Techbase-GEN-plugin/actions/workflows/plugin-python-syntax.yml)

## 1. Afzonderlijke verdeelkast-uitgang

Synthetisch oorspronkelijk station **044.529**, verdeelkastlabel **LS-024709**. Een onafhankelijke groep **B99-00** begint bij de kast, heeft geen directe stationsuitgang en wordt door een andere groep **S07-00** gevoed. **B99-01** is de aftakking van B99-00. **S03-00** is daarnaast een eigen, directe stationsrichting, bestaande uit 150Al en 120Al-kabeldelen.

| Oorspronkelijke richting | Exacte rol | Belasting (A) | Eigen fysiek kabeltracé (m) | Indirecte belastingen |
|---|---|---:|---:|---|
| S07-00 | Station → verdeelkast LS-024709 | 50 | 50 | B99-00 en B99-01, samen eenmaal |
| B99-00 | Zelfstandige verdeelkast-hoofdgroep | 50 | 50 | Eigen 20 A + B99-01 30 A |
| B99-01 | Zelfstandige aftakking achter kast | 30 | 20 | Alleen de eigen aansluiting |
| S03-00 | Afzonderlijke bestaande stationsrichting | 25 | 60 | Geen kastafnemers |
| **Station 044.529** | **Trafo-totaal** | **75** | n.v.t. | 50 A via kast + 25 A direct |

Het synthetische station heeft een opgegeven transformatorgrens van **217 A**. De basisproef behoudt **drie oorspronkelijke aansluitingen** en neemt geen aansluiting over van een ander bestaand station. Op ieder werkelijk kabeldeel wordt de stroom van alléén zijn achterliggende aansluitingen berekend. Hoofdroute- en aftakkingslengtes worden niet opgeteld tot één fictief kabelpad.

## 2. Extra afzekeringsproef: afzonderlijk afschalen

Bij een kunstmatig ingestelde **63 A gG** voor uitsluitend kastgroep **B99-01** bedraagt de toegestane ontwerpstroom **57 A**, terwijl de aftakking **60 A** vraagt. Resultaat: de oorspronkelijke aansluiting `cab-branch` wordt vrijgegeven. `cab-main` en `station-main` blijven bij station 044.529. Een andere bestaande stationsrichting krijgt geen nieuwe aansluiting cadeau. Nieuwe stations krijgen alleen de fysiek overgebleven, elektrisch te scheiden aansluitingen.

Dit is een **testwaarde voor de afzekering**. Voor het werkelijke werkgebied zijn de geïnstalleerde gG-waarden nog niet bevestigd; zonder die data levert de kabelchecker een **berekend maximaal gG-advies**, geen bewijs dat de bestaande zekeringen voldoen.

## 3. Onafhankelijke regressiecontroles

- **Geslaagd:** dezelfde `-00`-, `-01`-, `-02`- en `-03`-codes blijven per volledig kabelgroepnummer gescheiden; de hoofdroute draagt alle relevante downstream ontwerpstromen.
- **Geslaagd:** een verdeelkast wordt rechtstreeks vanuit `S07-00` of via de werkelijke `S07-01` gevoed; de kast-uitgang `B99-00` en eigen aftakking `B99-01` worden afzonderlijk gecontroleerd. Bovenliggende stationskabeldelen tellen de belasting elk eenmaal.
- **Geslaagd:** het feit dat een kast binnen de 15 meter stations-snapstraal valt, maakt haar uitgang niet automatisch een directe stationsrichting.
- **Geslaagd:** een kastpolygoon met verschillende in-/uitgaande kabeleinden is alleen toegestaan wanneer een **bestaande nul-rekenmeterverbinding** door het daadwerkelijke kastobject in de QGIS-kabelgraph aanwezig is. Ontbreekt deze verbinding, dan faalt de behoudcontrole bewust.
- **Geslaagd:** afzonderlijk trafoverbruik/opwek en kabelverbruik/opwek, verschillende kabeltypen en lengtes, vaste trafo-capaciteitsgrens, gG en maximale route.
- **Geslaagd:** dezelfde groepscodes bij verschillende stations worden niet samengevoegd; een onduidelijke of dubbele kastvoeding wordt afgewezen.
- **Geslaagd:** de eigenlijke nieuwe-stations-Voronoi mag uitsluitend vrijgegeven/nieuwe aansluitingen krijgen; oorspronkelijke behouden kabeldelen blijven gereserveerd en mogen niet worden toegewezen aan een nieuw station.
- **Geslaagd:** een overbelast bestaand station kan alle oude aansluitingen afstaan. In die situatie wordt geen fictief gereserveerd kabeltracé aangemaakt.
- **Afgeschermd:** een handmatig vastgezet nieuw station wordt niet per ongeluk als een bestaand station aangemerkt; de behoudmodus geeft hiervoor een expliciete foutmelding. Vervallen oorspronkelijke stations worden buiten de oude stationsinventaris gelaten.

## 4. Nog te controleren met echte brondata

1. Aansluitingen: oorspronkelijke `Station` en volledige `Kabel Subgroep`, inclusief de juiste `-00/-01/-02`-relaties en het unieke aansluitings-ID.
2. Werkelijke lijnlagen `e_lv_map_cable` en `e_lv_connection_cable`: volledige fysieke geometrie, `Kabel Subgroep`, kabelmateriaal en doorsnede per stuk.
3. Verdeelkastenlaag `e_lv_distribution_box`: juiste `Nummer`, geometrie en echte interne bestaande kastverbindingen. Bij een ambigu kastpunt wordt geen toevoerrichting geraden.
4. Geïnstalleerde gG per oorspronkelijke stationrichting en, indien aanwezig, de zekeringen per verdeelkast-uitgang.
5. Volledige QGIS-end-to-end-berekening met station 044.529, overige oorspronkelijke stations, originele routing, nieuw-stationclusters en definitieve kaart-/GeoPackage-uitvoer.
6. Vervallen stations, handmatig geplaatste nieuwe stations en verbindingen die zonder fysieke kabelscheiding niet aan een nieuw station kunnen worden toegewezen.

**Conclusie:** het softwarematige **synthetische** controlebestand toont de juiste scheiding van oorspronkelijke station-/verdeelkasthoofd- en aftakgroepen en het afschalen bij een afzonderlijke kabelfout. De werkelijke netontwerpconformiteit en alle gG-afzekeringen in het gebruikersproject kunnen zonder de projectdata nog niet bevestigd worden. Deze branch blijft daarom een **concept-PR** en is niet als productierelease gepubliceerd.
