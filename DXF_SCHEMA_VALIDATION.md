# DXF-schema’s, verwijslijnen en fysieke veldkoppeling — v1.30.0

## Gebruik

Open **1.4. Voedend station uit LS-schema** in het echte dashboard. Bovenaan staat nu **Herleidingsmethode**:

- **XML + Excel van veld/rail/smelt**: de bestaande route, met LS-DXF als controle op de fysieke rails, veldnummers en K-bruggen. Een OV-DXF kan aanvullende herkomstregistratie bevestigen.
- **DXF-schema’s + geografische stationslaag**: de nieuwe route zonder schema-XML of schema-Excel. Kies de LS- en eventueel OV-schema-DXF en de oorspronkelijke geografische GEN-stationslaag in **RD New / EPSG:28992**. De aansluitingenlaag met Master Asset ID en kabelgroepen blijft nodig; de aansluitkabelbron voor wederzijdse object-ID-relaties is optioneel. De gewone GEN-import mag dus de geografische gegevens leveren, zonder een veld/rail/smelt-export te vereisen.

Een controle-CSV is in beide routes optioneel. Voorspellingen worden zonder CSV berekend; de CSV levert alleen een aparte vergelijking op exact Master Asset ID. Bronnen kunnen worden leeggemaakt. De schema-XML/Excel-keuzes zijn uitgeschakeld in de DXF-methode en worden daar niet gelezen. Voorstel, herkomst, voedingspad, kaartselectie, export, atomair toepassen en blijvend undo gebruiken dezelfde dashboardpagina. Gewijzigde stationscoördinaten blokkeren een oud DXF-voorstel.

## Uitgevoerde tekenregels

1. Kabelteksten die binnen 0,002 m op precies één getekende kabel liggen leveren een rechtstreeks tekstanker.
2. De witte verwijslijnen hebben eigen lagen `E_LV_SCHEMATIC_LABEL_BUNDLE` en `E_SL_SCHEMATIC_LABEL_BUNDLE`. Kabelkruisingen en tekstposities worden langs de verwijslijn geordend. Alleen een volledige, eenduidige reeks met dezelfde aantallen wordt gekoppeld. Ook tekstposities zonder bruikbare kabelcode tellen mee als lege plaats, zodat de rest niet opschuift. De tekst moet op het aansluitende labeldeel staan en de richting volgen. Een botsing met een rechtstreeks tekstanker wordt gemeld; geen omgekeerde of gedeeltelijke reeks geraden.
3. Verwijslijnen maken **geen elektrische verbinding**. Ook een gewone kabelkruising doet dat niet. Elektrische kabelverbindingen volgen gedeelde eindpunten en expliciete mofsymbolen. Rails blijven gescheiden zonder daadwerkelijke eindpuntaansluiting of een bevestigde gesloten brug.
4. Een herkend gevuld mes verbindt kabel naar rail. Het standaard GEN-messymbool wordt op zijn blokgeometrie herkend, onafhankelijk van de bloknaam. Een kruis met een eenduidige positieve numerieke zekeringwaarde vormt een afgaande verbinding. Lege/onbekende symbolen worden niet als gesloten verbinding aangenomen. Een K-brug moet de twee rails daadwerkelijk raken en herkende gesloten mescontacten hebben.
5. Geografische stations zijn **bronankers**, geen dichtstbijzijnde-stationkeuze voor iedere huisaansluiting. Een bronanker vereist dezelfde stationsnaam in de DXF binnen 100 m van de geografische locatie. Een kandidaat-rail moet binnen 50 m van het geografische station en 100 m van die tekst liggen en al een getekende verbinding hebben. De beste rail moet minstens 3 m duidelijker zijn dan de volgende kandidaat. Afstanden en gekozen rails worden geëxporteerd in `Stationsankers.csv`; onduidelijke ankers blijven onbehandeld. Dit blijft een geometrische aanname binnen deze schematische export, geen object-ID-bewijs.

Ondersteund is de rechte ASCII-DXF-export met de genoemde GEN-lagen, LINE/POLYLINE-geometrie en bekende symbolen. Geen zelfstandige DWG-import. Gebogen of niet-ondersteunde schema-geometrie wordt duidelijk afgewezen. Andere tekenconventies of schalen vergen nieuwe validatie. De route volgt de getekende toestand en bewijst geen actuele schakeling of elektrische vermogensstroom. Bestaande administratieve statusinformatie ontbreekt deels in DXF; zij wordt niet uit kleuren geraden.

## Oorzaak van de eerdere vier verschillen

De eerdere XML-route gebruikte de kabelcode van het **administratief bovenliggende veld** bij de smeltrol. Die relatie blijkt in vijf gevallen niet overeen te komen met het fysiek getekende veld. De railcontrole alleen ontdekte dat niet als beide velden op dezelfde rail liggen.

Bij **LS-028375** staat het mes fysiek bij **veld 4 / SMG3176**, terwijl het smeltobject administratief aan **veld 1 / SMG3271** hangt. Veld 1 is in de DXF niet gesloten getekend. De eerdere herleiding gebruikte daardoor SMG3271 en kwam op **044.522**. Het werkelijke getekende pad loopt via SMG3176 vanuit **044.536** naar veld 4, vervolgens over de rail naar veld 2 / SMG1346 en veld 3 / SMG3272. Dit verklaart alle vier eerdere verschillen. De eerdere open conclusie over schema versus CSV wordt hiermee vervangen door een concrete fout in de keuze van de veldrelatie.

De gecombineerde route controleert nu veldnummerteksten via hun vaste lokale tekenoffset `(1,52 × teksthoogte, −1,14 × teksthoogte)`. Alleen als het teruggerekende anker binnen 0,002 m op precies één werkelijk veldsymbool ligt én één actief veld met dat nummer in dezelfde installatie bestaat, wordt de smeltrol naar dat fysieke veld overgezet. Verplaatste teksten en onduidelijke nummers leveren geen correctie. Correcties staan in `Veldcorrecties.csv`. Er worden geen stationsnamen uit de CSV overgenomen en de XML/Excel-bronnen worden niet aangepast.

## Onafhankelijke Den Dungen-proef

Gebruikt: aangeleverde LS- en OV-DXF, geografische GEN-stationslaag, 2.763 aansluitingen en de aansluitkabelbron. Voor de gecombineerde proef daarnaast de aangeleverde veld/rail/smelt-XML en Excel. De vergelijking betreft 1.998 unieke Master Asset ID's. De voorspelling is eerst zonder CSV gemaakt; stations en herkomst zijn met CSV exact gelijk gebleven.

| Methode | Gelijk aan 1.998 controlegevallen | Afwijkend | Niet herleid binnen controlelijst | Herleid uit volledige bron van 2.763 |
| --- | ---: | ---: | ---: | ---: |
| v1.29.0 gecombineerd, administratieve veldrelatie | 1.994 | 4 | 0 | 2.723 |
| Nieuw: DXF + geografische stationsankers | **1.867** | **0** | **131** | **2.421** |
| Nieuw: XML/Excel + LS/OV-DXF + fysieke veldcontrole | **1.998** | **0** | **0** | **2.725** |

De DXF-route verwerkt 117 volledige verwijslijnreeksen en gebruikt 392 labelposities uit die reeksen; twee reeksen botsen met rechtstreeks aangehechte kabelteksten en worden uitgesloten. Van de vier eerdere afwijkingen herleidt DXF zelfstandig de drie SMG3272-aansluitingen naar 044.536. **SMG1346 staat niet als kabelcodetekst in de aangeleverde LS- of OV-DXF**, waardoor die aansluiting zelfstandig onbehandeld blijft. De gecombineerde route kent die code uit Excel en herleidt na veldcorrectie alle vier naar 044.536.

Niet alle oorspronkelijke bronpunten hebben externe controle: 765 bronpunten staan buiten de controlelijst. DXF laat over de hele bron 342 punten onbehandeld. Gecombineerd blijven 38 zonder stationsnaam: 22 missen een volledige herleiding, 16 missen een eenduidige MS-naar-stationsnaamvertaling. De volledige overeenkomst binnen de controlelijst is geen algemene 100%-garantie voor andere datasets of actuele schakelingen.

## Toepassen, undo en UI

Op nieuwe lokale GeoPackage-kopieën zijn DXF-koppelingen zonder CSV (2.421) en met CSV-bescherming (1.867) toegepast. Na heropenen en undo zijn alle oorspronkelijke attributen en geometrieblobs exact hersteld. Het echte dashboard heeft de DXF-achtergrondtaak met **lege schema-XML/Excel-velden** uitgevoerd. Toepassen en undo zijn ook via de echte knoppen uitgevoerd. Op een stationskopie is een coördinaat gewijzigd; het oude voorstel is geweigerd voordat de aansluitingen werden aangepast.

De gecombineerde route is afzonderlijk toegepast zonder CSV (2.725) en met CSV-bescherming (1.998), met hetzelfde exacte herstel na heropenen. Oorspronkelijke productiegegevens zijn niet gewijzigd.

Regressies: `test_schema_dxf.py`, `test_schema_linking.py`, `test_schema_ov.py`, `test_station_presentation.py`, `test_uniform_ui.py`, `test_unknown_station_capacity.py`, `test_plugin_headless.py`. De nieuwe tests dekken volledige/ontbrekende/omgekeerde verwijslijnreeksen, rechtstreeks verankerde teksten, gescheiden rails, open velden, onduidelijke stationsankers, annuleren, verkeerd coördinatenstelsel, fysieke veldcorrectie en afwijzing van verschoven veldnummerteksten. De echte productietest controleert daarnaast de gesloten mes-/K-symbolen en geografische wijzigingsbeveiliging.

Uitgevoerd met QGIS 4.2.3/PyQGIS en echte Qt-dashboardwidgets met offscreen-rendering. Geen volledige handmatige QGIS Desktop-proef, QGIS 3-uitvoering of live schakelstandcontrole. De nieuwe lezer gebruikt uitsluitend standaard Python en de reeds gebruikte Shapely 2; geen nieuwe ezdxf-installatie vereist.
