# Ontwerp: oorspronkelijke kabelrichtingen behouden (nog geen actieve autoclusteroptie)

## Brongegevens die de gebruiker heeft bevestigd

- Iedere bestaande LS-aansluiting heeft de oorspronkelijke **stationsnaam** (uit de stations-CSV / Lovion) én **`Kabel Subgroep`**.
- De **volledige** `Kabel Subgroep`-waarde is bepalend. Bijvoorbeeld `K01-00` is de hoofdroute, `K01-01`, `K01-02` en `K01-03` zijn afzonderlijke aftakkingen. Niet samenvoegen tot `K01` of tot één doorlopende lange kabel.
- De GEN-kabellijnen bevatten per fysiek deel **kabeltype**, **geometrie** (lengte) en bijbehorende `Kabel Subgroep`.
- Een aansluiting op `-02` belast haar eigen fysieke kabeldeel en alle hoofdroute-kabeldelen **tot aan haar aftakpunt**, maar niet de stukken van `-00` achter haar aftakpunt of de andere aftakkingen.
- Voor een hoofdroute wordt de ontwerpstroom **van alle downstream-aansluitingen** uit `-00`, `-01`, `-02`, `-03`, enzovoort meegenomen. Het station telt iedere aansluiting maar één keer.

## Voorbeeld

| Oorspronkelijke groep | Trafo/kabelontwerpstroom in vereenvoudigd voorbeeld |
|---|---:|
| `K01-00` rechtstreeks | 20 A |
| `K01-01` aftakking | 15 A |
| `K01-02` aftakking | 30 A |
| `K01-03` aftakking | 25 A |
| **Totaal hoofdroute bij station** | **90 A** |

Fysieke hoofdroute: station → aftakking 01 → aftakking 03 → aftakking 02 → laatste directe aansluiting.

- Op de eerste hoofdkabel: 90 A.
- Na aftakking 01: 75 A.
- Na aftakking 03: 50 A.
- Na aftakking 02: 20 A.
- Aftakkingen zelf: respectievelijk 15, 30 en 25 A.

Voor de werkelijke berekening worden **verbruik en opwek onafhankelijk opgeteld** en geldt per niveau het hoogste van die twee. Trafo gebruikt de trafowaarden, kabel gebruikt de kabelwaarden. De getallen hierboven zijn een simulatie met alleen verbruik.

De lengte- en impedantiecontrole volgt elk afzonderlijk kabelpad, met de opeenvolgende werkelijke kabeltypen en gesplitste lengtes volgens `AutoCAD-Enexis-kabels-checker`. Parallelle aftakkingen worden niet fictief achter elkaar als één lange kabel geplaatst. Zonder bevestigde bestaande gG-waarde kan alleen de maximaal toelaatbare gG-klasse worden voorgesteld; geen oorspronkelijke zekering worden verzonnen.

## Technisch op deze conceptbranch

- `existing_station_retention.py`: onafhankelijke route-, capaciteit- en kabelcheckercontrole; herkent `-00` als hoofdgroep; belast upstream alle aftakkingen; per fysiek kabeldeel `deel_belasting_a`; behoudt uitsluitend oorspronkelijk aangesloten aansluitingen.
- `existing_group_trace.py`: leest `Station` en `Kabel Subgroep` van aansluitingen, zoekt op echte GEN-kabelgeometrie de afzonderlijke routes, bochtpunten, kabeltypen en bevestigde aftakpunten. Niet op toevallige nabijheid een andere richting kiezen.
- `test_existing_station_retention.py`: test de waarde van 90 A en per-kabeldeellasten met -00/-01/-02/-03, gG- en transformatorgrenzen.
- `test_existing_group_trace.py`: gebruikt gesimuleerde RD-lijngeometrieën met -00/-01/-02/-03 en verifieert de oorspronkelijke fysieke routes en stroomopbouw.
- De gewone clusteroutput behoudt nu ook de kolom `Kabel Subgroep`.

## Status en veiligheidsgrenzen

**De modus is nu aangesloten op de QGIS-autocluster en is uitsluitend optioneel.** Kies in de instellingen **"Behoud originele bestaande stations en kabelrichtingen (-00/-01/-02/...)"**. Standaard staat deze uit en verandert de oude clustering niet. De wizard en de losse Processing-tool geven de keuze door aan de engine.

1. QGIS exporteert de vier afzonderlijke ontwerpstroomcomponenten (**trafo verbruik/opwek, kabel verbruik/opwek**) als expliciete invoervelden. De clusterbelasting gebruikt apart **Hoogste Trafo**; de historische kabelberekening mag deze MAX-waarde nooit verwarren met verbruik op kabelniveau.
2. De bronvelden `Station` en `Kabel Subgroep` koppelen iedere bestaande aansluiting aan een origineel station en de volledige richtingcode. De code kan bij meer stations herhaald worden: de geometrie wordt per **station én groep** fysiek opgesplitst.
3. `existing_group_trace.py` volgt de exacte getypeerde kabeldelen vanaf station via `-00` en eventuele `-01/-02/-03`-aftakkingen. `retain_original` controleert trafovermogen, de Enexis-kabelchecker op ieder pad, per segment de werkelijke belasting en de maximale route. Een te zware aansluiting wordt uitsluitend **uit** het oorspronkelijke station vrijgegeven.
4. `existing_locked_clustering.py` reserveert de oude fysieke routes en wortelknopen; daarna rekent de **werkelijke kabelverbonden Voronoi** alleen op het resterende kabelnet, met **uitsluitend nieuwe stations als bronnen**. Een nieuwe route mag geen gereserveerd oud kabeldeel hergebruiken of een behouden aansluiting overnemen. Als een vrijgegeven aansluiting op hetzelfde ongescheiden fysieke kabeldeel ligt, wordt gestopt met een duidelijke controlefout; er wordt geen fictieve netscheiding getekend.
5. Resultaten: `aansluitingen_geclusterd` bevat **`Oud_besluit`**, `Oud_kabelgroep` en de huidige `Kabel Subgroep`; `stations_ontwerp` bevat de aantallen **`Orig_behouden`** en **`Orig_vrijgegeven`**. `bestaande_stations_kabelgroepen_controle.csv` bevat de afzonderlijke beslissingen en redenen. De richtingcontroles staan als `bestaande_richtingen_controle` in het GeoPackage (of bij GDAL-appenderproblemen als aparte GPKG) met lengte, gG, impedantie, segmenttype en belastbaarheid.
6. De kaarttekens van de oude stations gebruiken de **exacte oorspronkelijke kabelgeometrie** uit de source, geen afgeronde nearest-neighbour-route.

**Nog geen volledige QGIS-praktijktest:** alleen AST-/Python-regressies met gesimuleerde RD-gegevens, de echte Voronoi-kern en Enexis-checkertarieven. De oorspronkelijke GEN-projectdata van de gebruiker is niet beschikbaar; een volledig geopackage, kaartpolygonen, QGIS-project en station 044.529 zijn daarom niet integraal gecontroleerd. De PR blijft concept; er is geen productie-release zolang deze verificatie ontbreekt.

Een oorspronkelijke kabelgroep ontbreekt, heeft geen fysiek continu pad, heeft conflicterende kabeltypen of heeft een niet-eenduidig aftakpunt? Dan moet de nieuwe modus **de data afkeuren en duidelijk rapporteren**, niet stilzwijgend een ander station/een andere kabel tekenen. Voor definitieve automatische ontwerpgoedkeuring zijn echte bestaande gG-richtingen en verifieerbare projectlagen nodig.

De code is beschikbaar in een **draft pull request**, nog niet samengevoegd met `main` of als QGIS-productieversie vrijgegeven. De knop is geïntegreerd in de branch, maar de volledige QGIS-run met projectlagen moet nog worden gevalideerd.
