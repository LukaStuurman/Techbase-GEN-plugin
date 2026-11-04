# Stationsherleiding zonder controle-CSV — v1.29.0

**Vervangen door v1.30.0:** de vier verschillen hieronder zijn nu verklaard en opgelost. Vijf smeltobjecten waren administratief aan een ander veld gekoppeld dan fysiek getekend. De nieuwe fysieke veldnummercontrole met LS-DXF geeft gecombineerd 1.998 gelijke controlegevallen en 0 verschillen. Er is daarnaast een zelfstandige DXF-route met geografische stationsankers. Zie [actuele resultaten, oorzaak en beperkingen](DXF_SCHEMA_VALIDATION.md). Onderstaande cijfers blijven de historische v1.29.0-proef.

## Gebruik in het echte dashboard

Open **1.4. Voedend station uit LS-schema**. Kies de bij elkaar horende veld/rail/smelt-XML en Excel, de aansluitingenlaag en de stationslaag met SAP-nummer. Een controle-CSV is optioneel en kan met het kruisje worden leeggemaakt. Zonder CSV wordt het station volledig uit de bronregistratie berekend.

Nieuw zijn **OV-schema DXF (optioneel)** en **Aansluitkabelbron (optioneel, object-ID-relaties)**. De bron `e_lv_connection_cable` uit de GEN-import wordt herkend als zij in het project staat. Gebruik de LS-DXF voor geometriecontrole en de OV-DXF voor aanvullende kabelcoderegistratie. Bereken een voorstel, bekijk de herkomst en het voedingspad, exporteer het rapport en pas gecontroleerd toe. Bestaande afwijkende stations vervangen blijft een aparte keuze. Terugdraaien blijft na heropenen beschikbaar. Voer clustering zo nodig opnieuw uit na een gewijzigde bronlaag.

## Uitgevoerde verbeteringen

- Meerdere expliciete kabelgroepen worden afzonderlijk herleid. Alleen een volledige, overeenstemmende enkelvoudige bron geeft een stationsnaam; de eerste code wordt nooit zomaar gekozen.
- Een unieke actieve aansluitkabel kan de specifieke groep bepalen als aansluiting → kabel en kabel → aansluiting elkaar via object-ID bevestigen. Dubbele object-ID's, dubbele kabel-ID's, ontbrekende terugverwijzing en inactieve kabels geven geen voorkeur. Afwijkende broncodes moeten ieder onafhankelijk hetzelfde station opleveren.
- De OV-DXF-lezer herkent uitsluitend kabelcodelabels op `E_SL_SCHEMATIC_CABLE_LABEL`, met de bijbehorende schematische OV-lagen. Een doorsnede zoals `4x6` of zekeringwaarde wordt niet als kabelcode gelezen. De code moet op precies één actief, bruikbaar MS-stationveld in de gekoppelde XML/Excel geregistreerd staan. Reservevelden worden uitgesloten.
- OV levert hiermee **herkomstregistratie**, geen volledig getraceerd OV-schakelpad. Het voorstel, de opgeslagen auditvelden en het rapport onderscheiden dit van een LS-schakelpad. Een bestaande LS-herleiding wordt niet vervangen door een zwakkere afwijkende OV-registratie; die afwijking wordt gemeld. Meerdere OV-bronnen blijven onzeker.
- Nieuwe bronbestanden en de aansluitkabelbron vallen onder de controle op gewijzigde invoer. Er wordt geen dichtstbijzijnde station gekozen, geen referentielabel geleerd en geen origineel bronbestand aangepast.

## Onafhankelijke productieproef Den Dungen

Gebruikt: de aangeleverde veld/rail/smelt-XML en Excel, LS- en OV-schema-DXF, voorbereide GEN-import en ontwerpstroomlaag. De bron bevat 2.763 aansluitingen en 4.678 aansluitkabels. De controle-CSV bevat 1.998 unieke Master Asset ID's. Voorspellingen zijn eerst **zonder CSV** berekend; een aparte vergelijking bewijst dat stations en herkomst met CSV exact dezelfde blijven. Geen kabelcodes uit de controle-CSV als invoer.

| Methode | Gelijk aan controle-CSV | Afwijkend | Niet herleid binnen controlelijst |
| --- | ---: | ---: | ---: |
| v1.28.0 LS-model | 1.926 | 4 | 68 |
| LS met meervoudige kabelcodes | 1.928 | 4 | 66 |
| Plus OV-registratie | 1.993 | 4 | 1 |
| Plus wederzijdse aansluitkabelrelatie | **1.994** | **4** | **0** |

Dat is 99,8% overeenkomst over alle 1.998 controlegevallen. Dit bewijst geen 100% juistheid zonder controlebron. Alle 68 eerder onbekende controlegevallen krijgen nu een herkomst, maar vier andere gevallen blijven afwijken.

De meeste eerdere onbekenden waren woningen: 58 van 68, dus niet uitsluitend straatmeubilair. Kabelgroepen SMG1981, SMG1982 en SMG3199 komen in de OV-tekening voor en hebben een unieke stationregistratie. Zij verklaren 65 extra controlegevallen. Twee gevallen hebben meerdere subgroepen van dezelfde groep; bij één geval selecteert de wederzijdse kabelrelatie de specifieke groep uit twee verschillende groepen.

Van de **volledige bronlaag** worden **2.723 van 2.763** aansluitingen herleid. Er blijven **40** zonder stationsnaam: 24 missen een volledige herleiding en 16 hebben geen eenduidige MS-naar-stationsnaamvertaling in de gekozen stationslaag. Deze blijven expliciet onbehandeld. De benchmark dekt die 765 extra bronpunten niet.

De vier verschillen betreffen SMG3272 (drie aansluitingen) en SMG1346 (één aansluiting). De bronherleiding voert via MS-010945 naar **044.522**; de controle-CSV noemt **044.536**. De wederzijdse aansluitkabelregistratie bevestigt de gebruikte kabelgroepen. Dit verschil wordt niet via een CSV-geleerde uitzondering weggewerkt. Met gekozen controle-CSV worden deze vier regels uitgesloten. Zonder CSV blijven zij als modeluitkomst 044.522 gelden: externe bevestiging van de actuele registratie is nog nodig.

## Toepassen, undo en UI-controle

Op een lokale kopie van de productie-GeoPackage zijn zonder CSV 2.723 koppelingen toegepast en na heropenen teruggedraaid. Alle oorspronkelijke attributen en geometrieblobs zijn exact hersteld. Daarna zijn met CSV-bescherming 1.994 koppelingen toegepast; de vier afwijkingen blijven ongewijzigd. Opnieuw is volledig herstel na heropenen gecontroleerd.

Het echte gekleurde dashboard is geopend, knop 1.4 aangeklikt en de achtergrondtaak met productiegegevens uitgevoerd. OV-bestandskeuze, automatische aansluitkabelbron, herkomstkolom, vier afwijkende tabelregels en export zijn gecontroleerd. Schermafbeeldingen zijn lokaal bewaard; er staan geen productiegegevens in deze repository.

Regressies: `test_schema_ov.py`, `test_schema_linking.py`, `test_station_presentation.py`, `test_uniform_ui.py`, `test_unknown_station_capacity.py` en `test_plugin_headless.py`. De nieuwe OV-test dekt unieke/meervoudige bronnen, LS-prioriteit, reservevelden, exacte labels, verkeerde DXF, kabelcodeconsensus, wederzijdse en dubbele objectrelaties, CSV-loze toepassing en onafhankelijke vergelijking. De bestaande schematest controleert ook rollback, gewijzigde invoer, blijvend undo en kaartselectie.

Uitvoering met QGIS 4.2.3/PyQGIS en echte Qt-widgets met offscreen-rendering. Geen QGIS 3-uitvoering, volledige handmatige QGIS Desktop-schakelproef of zelfstandig elektrisch OV-netwerkmodel. De actuele fysieke schakeling en stroomrichting zijn niet gemeten.
