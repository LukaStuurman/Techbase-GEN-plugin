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

**Deze branch is nog geen functionele extra autoclusteroptie in QGIS.** De aparte module en tests vormen de gecontroleerde basis; de implementatie moet nog worden gekoppeld aan het bestaande-station-behoud, het reserveren van exclusieve bestaande kabeldelen, het herverdelen van vrijgegeven aansluitingen en de uiteindelijke kaart-/CSV-uitvoer. De bestaande autocluster werkt nog zoals voorheen.

Een oorspronkelijke kabelgroep ontbreekt, heeft geen fysiek continu pad, heeft conflicterende kabeltypen of heeft een niet-eenduidig aftakpunt? Dan moet de nieuwe modus **de data afkeuren en duidelijk rapporteren**, niet stilzwijgend een ander station/een andere kabel tekenen. Voor definitieve automatische ontwerpgoedkeuring zijn echte bestaande gG-richtingen en verifieerbare projectlagen nodig.

Deze tussenstand is daarom bewust **alleen een draft pull request**, niet samengevoegd met `main`, geen nieuwe QGIS-release.
