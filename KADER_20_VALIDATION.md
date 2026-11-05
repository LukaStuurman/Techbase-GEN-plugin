# Kader 2.0 ontwerpstroom en routeherstel — v1.33.1

## Workbookbron

De gebruiker leverde **Eea-0205.K 2.0.xlsx** aan (SHA-256 `229d6343c333c98023a609e5d16fc0d98c2c1498c7c6005732e3223885efa195`).
Het werkblad **Versie beheer** meldt bij 2.0: *nieuwe tabellen voor toekomstige aansluitwaarden kleinzakelijk en grootzakelijk*. De spreadsheet bevat tevens afzonderlijke trafo-, kabel- en stijgleidingtabellen en kabelselectiviteitscontroles.

De plugin biedt nu een **extra** Kader **2.0** naast de bestaande **3.0/3.2** (3.2 is de ongewijzigde oude 3.1-keuze). De eerdere 3.x-tabellen zijn niet vervangen. Voor Kader 2.0 gebruiken de berekeningen de tabellen uit `kader_20.py`, onafhankelijk van de aanpasbare historische 3.x-matrices.

## Exact overgenomen ontwerpstroomwaarden (A per eenheid)

| Categorie | Trafo verbruik | Trafo opwek | Kabel verbruik | Kabel opwek |
|---|---:|---:|---:|---:|
| Type 1: vrijstaand, individuele warmtepomp | 9.5 | 9.5 | 10.3 | 9.8 |
| Type 1: twee-onder-een-kap | 8.0 | 7.3 | 8.8 | 7.5 |
| Type 1: rijtjes/hoek | 7.0 | 7.3 | 7.8 | 7.5 |
| Type 1: onbekend | 7.6 | 7.3 | 8.4 | 7.5 |
| Type 2: laagbouw met gas/stadsverwarming (alle typen) | 3.3 | gelijk aan Type 1 per woningtype | 4.1 | gelijk aan Type 1 |
| Type 3: appartement collectieve verwarming | 2.8 | 0 (lege Excel-cel) | 3.5 | 0 |
| Type 4: appartement individuele warmtepomp | 5.5 | 0 (lege Excel-cel) | 6.0 | 0 |
| Type 6: toekomstige zakelijke 3×25 | 8.7 | 8.7 | 8.7 | 8.7 |
| Type 6: toekomstige zakelijke 3×35–40 | 32 | 32 | 32 | 32 |
| Type 6: toekomstige zakelijke 3×50 | 44 | 44 | 44 | 44 |
| Type 6: toekomstige zakelijke 3×63–80 | 65 | 65 | 65 | 65 |
| Type 7: toekomstige grootzakelijke 3×160 | 138 | 138 | 138 | 138 |
| Type 7: toekomstige grootzakelijke 3×250 | 210 | 210 | 210 | 210 |
| Type 8: netbewust laden 3×25 | 5.8 | 0 | 6.7 | 0 |
| Type 9: straatmeubilair 3×25 | 5.8 | 0 | 5.8 | 0 |
| Type 9: straatmeubilair 3×40–50 | 22 | 0 | 22 | 0 |
| Type 9: straatmeubilair 3×63–80 | 36 | 0 | 36 | 0 |

De ontwerpstromen op trafo- en kabelniveau komen onafhankelijk uit hun eigen werkblad; `Hoogste Trafo` en `Hoogste Kabel` nemen elk het maximum van verbruik en opwek. De workbooktotalen gebruiken **aantal × A per eenheid**; omzetting naar kW gebruikt **0,23 × 3**. De originele Excel heeft lege opwekwaarden voor typen 3/4, laden en straatmeubilair. Die worden in het automatische resultaat expliciet als 0 behandeld; niet als de algemene 3.x-opwekwaarde.

## Verschillen / belangrijke aannames

- **Verwarmingswijze is niet hetzelfde als bouwjaar.** In Kader 2.0 worden Type 1/2 (laagbouw) en Type 3/4 (hoogbouw) op verwarmingswijze onderscheiden. De GEN-invoer kent dit niet altijd. Zonder expliciete kolom `Kader20Type` gebruikt de plugin de bestaande bouwjaargrens 2022 slechts als *planningsaanname*: jonger = individuele warmtepomp. In `KaderType` wordt deze aanname vermeld. Vul `Kader20Type` met `Type 1`, `Type 2`, `Type 3` of `Type 4` om deze te overschrijven. De eerdere veldwaarde `OntwerpstroomType` uit Kader 3.x is opzettelijk **geen** Kader 2.0-type.
- **Toekomstige aansluitwaarde is niet automatisch gelijk aan huidige.** Voor zakelijke aansluitingen kan de invoerkolom `Kader20ToekomstigeAansluitwaarde` (bv. `3 x 160 A`) worden toegevoegd. Die krijgt voorrang op het huidige doorlaatveld. Ontbreekt deze, dan krijgt de zakelijke aansluiting **0 A met waarschuwing** tot de toekomstige waarde via de ontwerpstroomcorrectie is vastgelegd; de huidige waarde wordt nooit als toekomst aangenomen.
- **Type 7 ‘overig’ is leeg in Excel.** Voor 3×100, 3×125, 3×200, hogere of onbekende zakelijke toekomstige aansluitwaarden bestaat geen vaste Kader 2.0-waarde in deze bron. De plugin verzint geen waarde en valt ook niet stilzwijgend terug naar Kader 3.x: de berekening levert **0 A met waarschuwing** op. Herstel deze via de bestaande nulwaarden-/handmatige ontwerpstroomcorrectie vóór clusteren.
- **Type 5 aanvullende warmtecomponenten** vereist aantal × elektrisch vermogen × gelijktijdigheidsfactor. De aangeleverde workbook bevat geen volledige gelijktijdigheidsfactortabel. `kader_20.type5_surcharge_a` is beschikbaar voor expliciet aangeleverde getallen; de plugin voegt zonder invoer **geen** toeslag toe.
- **Stijgleiding is een afzonderlijke berekening**, niet te mengen met trafo/kabel. De exacte Type 3 = 1,7 A en Type 4 = 4,3 A per appartement en Type 6 zakelijke staffel zijn beschikbaar als `kader_20.riser_current`. Zij zijn niet automatisch een extra veld op LS-aansluitpunten, omdat één stijgleiding meerdere aansluitingen kan omvatten.
- De bladen `Controle_kabel_evenredig`, `Controle_kabel_laatste_helft` en `max lengte OVL kabels` zijn kabel-/zekeringcontroles; ze zijn bewust niet als aansluitingontwerpstroom gebruikt.

## Vorige regressiecorrecties inbegrepen

- Bij automatisch stationsaantal direct de kabelverbonden Voronoi-fallback gebruiken, zonder de trage voorafgaande MILP-stationskeuze. Handmatig exact stationaantal behoudt de solver.
- Bestaande stations eerst uit expliciete KVA/Max_A of anders Status lezen (niet inventeren).
- Per-station routes volgen de **originele sleufsegmenten**, niet de afgeronde 0,1 m grafknopen. Nieuwe stations op een hoofdkabel krijgen geen numerieke snaplijn van ~0,1 m naast de sleuf.

## Testdekking en resterende controle

`test_kader_20.py` controleert alle bovengenoemde vaste tarieven, verbruik/opwek, bouwjaar/aangepast verwarmingssysteem, hoogbouw onder generiek GEN-gebruik, onbekende toekomstige waarden, stijgleiding en de Type-5-formule. Hij draait zonder QGIS in de pull-request- en release-workflow. `test_direct_voronoi_trench_routes.py` controleert bestaande stations en echte geometrie en vereist een QGIS-Pythoninstallatie.

Een volledige echte herberekening van het project met **station 044.529** is niet bij deze release uitgevoerd. De originele projectlagen zijn niet meegeleverd. Daarom is nog geen bewijs dat deze specifieke stationstoedeling en alle kaartlijnen in dat project helemaal correct zijn. Ook de snelheidswinst en end-to-end kantoorwerkwijze zijn niet met een volledig productieproject gemeten.

Installeer de versie-ZIP, herstart QGIS, kies **Kader 2.0** in het hoofdscherm en controleer de `KaderVersie`, `KaderType` en nulwaardenaansluitingen vóór het starten van de clustering.

## Belangrijk verschil met Excel 3.2

De meegeleverde 3.2-Excel bevat óók kleinzakelijk en grootverbruik, maar rekent daar met **huidige aansluitwaarde + gascategorie**, anders dan de **toekomstige** waarde van 2.0. De pluginkeuze Kader 3.2 is de oorspronkelijke **3.1-methode met uitsluitend een nieuwe naam**: geen bestaande waarde is gewijzigd. De volledige vergelijking en invoer via de correctiepagina staan in [KADER_20_VS_32.md](KADER_20_VS_32.md).
