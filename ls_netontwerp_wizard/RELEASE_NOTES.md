# LS Netontwerp Wizard v1.31.2

## Leesbare uitgeklapte clusterknoppen

De kaart **Clustering aanpassen** en het dashboard groeien nu mee wanneer **Geavanceerde clusterbewerkingen** wordt aangevinkt. De inhoud krijgt zijn vereiste minimumhoogte en blijft binnen het scrollbare dashboard. Daardoor worden de negen knoppen niet in een te kleine kaart samengedrukt of over elkaar getekend.

Getest met het echte QGIS/Qt-dashboard op 1180×740 en 1440×960, herhaald uit-/inklappen, alle negen afzonderlijke knoprechthoeken, passende tekstbreedte en bereikbaarheid van het klikpunt via de scrollbalk. `test_dashboard_expansion.py` en de bestaande uniforme-UI-regressie slagen in QGIS 4.2.3. Geen QGIS 3-uitvoering.

**Berekeningsstatus:** de experimentele nieuwe knooppuntplaatsing is nog niet volledig doorgerekend en zit niet in deze UI-herstelrelease. De productierun heeft negen kandidaten geselecteerd, waaronder zes nieuwe knooppuntlocaties, maar definitieve toedeling en route-/gebiedsvalidatie zijn nog niet afgerond. Dit wordt niet als geslaagd totaalontwerp voorgesteld.

Installeer de ZIP en herstart QGIS.

## Behouden uit v1.31.1

## Kleiner optimalisatiemodel zonder versoepelde controles

Stationskeuze en definitieve clustertoedeling verwijderen nu exact de variabelen die door de bestaande routevoorwaarden al verplicht nul zijn. Na berekening wordt de volledige indeling hersteld. De definitieve toedeling slaat bovendien benuttingsniveaus over die rekenkundig onmogelijk zijn op basis van totale of per station bereikbare belasting. Capaciteit, maximale routes, integrale toewijzing en latere netwerk-/gebiedscontroles blijven behouden.

Den Dungen-productiemeting: **61.744 → 27.155 variabelen, 56% minder** in het eerste stationskeuzemodel. Twaalf aparte tests vergelijken het oorspronkelijke en compacte model en vinden exact dezelfde optimale doelwaarden; gerichte reken-, herstel- en pluginregressies slagen in QGIS 4.2.3. **De volledige nieuwe productieherberekening is nog niet afgerond; een totale versnelfactor is nog niet aangetoond.** [Meetwijze en beperkingen](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/CLUSTER_SPEED_VALIDATION.md).

Installeer de ZIP en herstart QGIS. De versnelling werkt automatisch bij een nieuwe clustering.

## Behouden uit v1.31.0

## Routes binnen het plangebied, herstel en eenvoudiger clustercorrectie

- Buitenroutes staan standaard **uit** voor nieuwe instellingen. Een eerder opgeslagen keuze blijft behouden; optioneel inschakelen blijft mogelijk.
- Bij een mislukte clustering kun je naar kabelcontroledelen zoomen en een ontbrekende verbindingssleuf tekenen. De lijn moet geheel binnen het plangebied liggen en met beide uiteinden aansluiten. De aanvulling wordt apart opgeslagen en bij opnieuw clusteren meegenomen, zonder bronkabels te wijzigen. Geen gelokaliseerd rapport beschikbaar? Dan volgt uitleg en blijft het controleproject beschikbaar. Een getoond los deel is een inspectiepunt, niet automatisch de foutoorzaak.
- De normale correctie blijft direct onder 4a. Overige correctieknoppen zijn bereikbaar via **Geavanceerde clusterbewerkingen**. Kies voor een hele cluster het bronstation op de kaart, daarna het doelstation. Voor losse aansluitingen selecteer je punten en daarna het doelstation. Controle en toepassen blijven vereist; extra instellingen blijven onder Geavanceerd.
- Interne verbindingen naar stationsomtrekken gebruiken een echte gedeelde vertex. Dit herstelt de aangetoonde afkoppeling van 044.532, 044.505, 044.535 en 044.524 in de nieuwste aangeleverde Den Dungen-clustering. Automatische eindcontrole laat een volledig nieuw kabelgebied overnemen door een bestaand station als capaciteit en exclusieve routes dit toelaten.

Gerichte geometrie-, opslag-, kaartselectie-, dashboard- en hersteltaken slagen in QGIS 4.2.3. De handmatige overzetting N-08 → 044.507 slaagt ook op productiedata. **De volledige Den Dungen-herberekening is nog niet afgerond; deze release claimt daarvoor geen geslaagd totaalontwerp.** Geen QGIS 3-test of volledige fysieke Desktop-muistest. [Gebruik, bewijs en beperkingen](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/NETWORK_REPAIR_VALIDATION.md).

Installeer de ZIP en herstart QGIS. Controleer bij bestaande projecten de opgeslagen buitenroutekeuze; die wordt niet stilzwijgend gewijzigd.

## Behouden uit v1.30.0

## DXF-schema’s met geografische stationsankers

Op dashboardpagina **1.4. Voedend station uit LS-schema** kun je bovenaan de **Herleidingsmethode** kiezen. Nieuw: **DXF-schema’s + geografische stationslaag**, zonder schema-XML of schema-Excel. Kies de LS- en eventueel OV-DXF, de geografische GEN-stationslaag in RD New en de aansluitingenlaag met kabelcodes. De controle-CSV blijft optioneel.

- Kabelcodes worden gekoppeld via exacte tekstankers en complete, geordende reeksen langs de witte verwijslijnen. Onvolledige of tegenstrijdige reeksen worden uitgesloten. Verwijslijnen en gewone kruisingen maken geen elektrische verbinding.
- Getekende eindpunten, mofsymbolen, herkende messen, numerieke zekeringen en gesloten K-bruggen bepalen het voedingspad. Geografische stationsankers vereisen ook een passende stationsnaam in de DXF en duidelijke afstandsmarges. Afstanden en contactcoördinaten zijn controleerbaar in het rapport.
- Voorstel, herkomst, kaartselectie, export, atomair toepassen en blijvend undo zitten in de echte dashboardpagina. Veranderde stationscoördinaten blokkeren een oud voorstel. Er is geen nieuwe ezdxf-afhankelijkheid.

## Vier eerdere verschillen opgelost door fysieke veldnummers

De eerdere XML-route gebruikte bij de smeltrol de administratieve bovenliggende veldcode. In vijf gevallen wijkt die af van het fysiek getekende veld. De LS-DXF controleert nu expliciete veldnummerteksten op hun werkelijke symboolpositie. Bij LS-028375 staat het mes bij **veld 4 / SMG3176**, terwijl het administratief aan **veld 1 / SMG3271** hangt. Het getekende pad voedt vanuit **044.536**. Dit verklaart en herstelt de vier eerdere afwijkingen; de CSV wordt niet als voorspeller gebruikt. Correcties worden apart gerapporteerd en wijzigen de oorspronkelijke XML/Excel niet.

**Den Dungen, onafhankelijk op 1.998 Master Asset ID’s:** DXF + geografische stations geeft **1.867 gelijk, 0 afwijkend, 131 onbekend**. XML/Excel + LS/OV-DXF met fysieke veldcontrole geeft **1.998 gelijk, 0 afwijkend, 0 onbekend**. Over alle 2.763 bronpunten worden respectievelijk 2.421 en 2.725 herleid. De overige 342 respectievelijk 38 blijven expliciet onbehandeld; 765 bronpunten hebben geen externe controle. Dit is geen algemene garantie voor andere tekeningen of actuele schakelingen.

Toepassen zonder CSV en met CSV-bescherming is voor beide routes op productiekopieën getest, inclusief exact herstel van oorspronkelijke attributen en geometrieën na heropenen. De DXF-taak is met lege schema-XML/Excel-velden via het echte dashboard uitgevoerd; ook toepassen/undo via de knoppen en het blokkeren van gewijzigde stationscoördinaten zijn gecontroleerd. Zeven regressies slagen in QGIS 4.2.3. Geen QGIS 3-uitvoering of volledige handmatige Desktop-/live-schakelproef. [Volledige validatie](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/DXF_SCHEMA_VALIDATION.md).

Installeer de ZIP, herstart QGIS en kies de methode op pagina 1.4.

## Behouden uit v1.29.0

## Stationsherleiding zonder controle-CSV, met OV-registratie

Op **1.4. Voedend station uit LS-schema** zijn **OV-schema DXF** en **Aansluitkabelbron** toegevoegd. De controle-CSV is optioneel en levert uitsluitend een onafhankelijke vergelijking op Master Asset ID.

- Kabelcodelabels uit het OV-schema kunnen een unieke actieve stationveldregistratie bevestigen. Dit is zichtbaar als afzonderlijke herkomst, met de beperking dat de actuele OV-schakeling niet is vastgesteld. Afwijkende OV-registratie vervangt geen bestaand LS-schakelpad.
- Meerdere kabelgroepen moeten allemaal naar dezelfde bron wijzen. Een specifieke aansluitkabel kan worden gekozen via een unieke wederzijdse object-ID-relatie, met status- en duplicaatcontroles. Geen afstandskeuze of CSV-geleerde koppeling.
- Tabel, voedingspad, rapport en opgeslagen auditvelden tonen de gebruikte herkomst. De nieuwe bronnen worden op wijzigingen gecontroleerd. Atomair toepassen en beschermd undo na heropenen blijven beschikbaar.

**Den Dungen:** 1.994 van 1.998 controlegevallen gelijk, vier verschillen en nul zonder herleiding. Alle eerder 68 onbekende controlegevallen krijgen nu een herkomst. De meeste daarvan waren woningen, niet uitsluitend straatmeubilair. Over de hele bronlaag worden 2.723 van 2.763 punten herleid; 40 blijven zonder stationsnaam. Voorspellingen zijn met en zonder controle-CSV exact gelijk. De vier verschillen blijven schema 044.522 tegenover controlelijst 044.536; ze worden met CSV niet toegepast en zonder CSV niet stilzwijgend gecorrigeerd.

Werkelijk toepassen zonder CSV (2.723) en met CSV-bescherming (1.994) is op een productiekopie gecontroleerd, inclusief exact herstel van oorspronkelijke attributen en geometrieën na heropenen en undo. De echte dashboardtaak en nieuwe invoervelden zijn met productiegegevens uitgevoerd. Regressies voor schema/OV, dashboard, stationspresentatie, onbekende capaciteit en plugin slagen in QGIS 4.2.3. Geen QGIS 3-uitvoering of volledige handmatige Desktop-test; zelfstandig OV-schakelpad en actuele stroomrichting worden niet geleverd. [Volledig verslag](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/LS_OV_LINK_VALIDATION.md).

Installeer de ZIP en herstart QGIS. Kies op pagina 1.4 de OV-DXF en de aansluitkabelbron uit de GEN-import. Laat Controle-CSV leeg voor zelfstandig gebruik.

## Behouden uit v1.28.1

## Bestaande stations met NULL-vermogen blijven zichtbaar

Station **044.532** stond al in de Den Dungen-import met `trafo_power = NULL` en `Max_A = NULL`. De kaartstijl tekende alleen stations met positieve capaciteit en verborg daardoor zowel het symbool als het label. Dit filter is hersteld.

- Een benoemd station met onbekende capaciteit krijgt een oranje vierkant met zijn stationsnaam en **Capaciteit onbekend**. Stations zonder naam én zonder capaciteit blijven als grijs controlepunt zichtbaar. De rode bekende en gele geplande stations met geldige capaciteit behouden hun weergave.
- Nieuwe ontwerpstroomresultaten gebruiken de nieuwe stijl. Bestaande gegenereerde werkprojecten krijgen de stijlherstelstap bij openen; voor een al geïmporteerde 044.532 is geen nieuwe XML/Excel-import nodig.
- NULL blijft NULL. Er wordt geen vermogen of maximale stroom verzonnen. De bestaande capaciteitsvoorwaarden voor automatische clustering blijven actief. Vul een gecontroleerde capaciteit in via **2c. Stations aanpassen** als dit station aan de berekening moet meedoen.

Gecontroleerd met de echte Den Dungen-GeoPackage en native QGIS-rendering: 044.532 is zichtbaar én gelabeld terwijl beide capaciteitsvelden NULL blijven. Tests voor onbekende/geldige/geplande/nul/ongeldige capaciteit, opslag/heropenen, oude projectstijl, stationspresentatie, schemaherleiding en dashboard slagen in QGIS 4.2.3. Geen QGIS 3-uitvoering. [Volledig verslag](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/UNKNOWN_STATION_CAPACITY_VALIDATION.md).

Installeer de ZIP, herstart QGIS en open het werkproject opnieuw.

## Behouden uit v1.28.0

## Voedend station rechtstreeks uit het LS-schema

Nieuw in het echte dashboard: **1.4. Voedend station uit LS-schema**. De functie leest de XML en Excel van veld, railsectie en smeltveiligheid en volgt de kabelgroep van iedere aansluiting via de verdeelkasten naar een station. Daarvoor hoeft geen LOVION-netwerkanalyse per station te worden opgehaald. De bestaande stationslaag vertaalt de MS-functieplaats naar de stationsnaam.

- De fysieke schematische smeltpositie bepaalt de rail. Administratieve bovenliggende assets worden niet zonder controle als elektrische verbinding gebruikt. Volgens de gebruikersregel voedt een mes zijn rail, voert een numeriek afgezekerd veld af en koppelt een actief K-veld de twee bedoelde rails.
- Optionele ASCII-DXF-controle op railgeometrie, smeltposities en K-bruggen. Een zelfstandige DXF-import zonder de XML-objectkoppelingen wordt niet geleverd. XML/Excel alleen werkt wel en behaalt in deze proef dezelfde uitkomst.
- Een optionele controle-CSV wordt uitsluitend op **Master Asset ID** vergeleken. De CSV voedt de voorspelling niet. Voorstel en tabel tonen bestaand, voorgesteld en referentiestation, afwijkingen en het herleidingspad. Tabelselecties kunnen op de kaart worden bekeken; rapporten zijn exporteerbaar.
- Toepassen wijzigt de bron-/ontwerpstroomlaag in één GeoPackage-transactie, met herkomstkolommen en blijvend undo na heropenen. CSV-afwijkingen, dubbele ID's en onzekere toewijzingen worden niet toegepast. Met CSV staan alleen overeenkomende koppelingen standaard aan; bestaande stationsnamen vervangen is een aparte keuze. Gewijzigde bronbestanden, laaginhoud en stationsgegevens vereisen een nieuw voorstel.
- Een bestaand clusterresultaat wordt niet rechtstreeks aangepast; voer clustering zo nodig opnieuw uit na een wijziging van de bronlaag.

**Den Dungen:** alle **1.998** unieke Master Asset ID's uit het controlebestand zijn exact in de 2.763 bronpunten teruggevonden. XML/Excel en XML/Excel plus DXF leveren ieder **1.926 gelijk, 4 afwijkend en 68 niet herleid**. Dat is 96,4% overeenkomst op de volledige referentie en 99,8% op de 1.930 herleide referentiegevallen. Het is geen 100%-garantie. De vier afwijkingen blijven controlepunten en worden niet stilzwijgend gecorrigeerd op basis van de CSV. Op een lokale kopie zijn 1.926 koppelingen toegepast, de vier afwijkingen behouden en alle oorspronkelijke attributen/geometrieën na heropenen exact met undo hersteld.

Getest met de echte QGIS 4.2.3-dashboardwidgets, achtergrondtaak, kaartselectie, echte GeoPackages, foutinjectie tijdens schrijven, gewijzigde voorstellen, twee afzonderlijke voedingen en een K-koppeling met werkelijk twee bronstations. Bestaande regressies slagen. Geen volledige handmatige Desktop-test of QGIS 3-uitvoering. [Volledige verantwoording](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/SCHEMA_LINK_VALIDATION.md).

Installeer de ZIP en herstart QGIS volledig.

## Behouden uit v1.27.3

## Vaartbroek zonder plangebied opgelost

De volledige automatische clustering slaagt nu met **4.266 aansluitingen, 24 bestaande en 41 nieuwe stations**. Totale ontwerpstroom **29.978,7 A**, langste station-aansluitingroute **762,16 m** bij een limiet van 850 m. Gebieden, routes, capaciteit, bron-ID's, latere stroomwijziging en het opgeslagen QGIS-project zijn onafhankelijk gecontroleerd. PDF en kaartafbeelding zijn gegenereerd.

- Herstel na een mislukte stationsselectie bewaart nu de actuele belasting bij iedere stap, ook als een verschuiving de routegrens overschrijdt. Routeknelpunten en onjuiste eigendom van een stationswortel kunnen zelf een gerichte extra kandidaat opleveren.
- Een belastingverdeling die niet verder verbetert blijft niet duizenden keren doorlopen. De automatische herstelstap probeert een extra geschikte kabelknoop en controleert iedere kandidaat opnieuw. Overbodige stations worden daarna alleen verwijderd als de volledige veilige verdeling behouden blijft.
- Een stationswortel mag niet door een ander kabelterritorium worden overgenomen. Zowel de gewone als de versnelde herstelberekening gebruiken dezelfde voorwaarden.
- Bij smalle gebiedsoverlap wordt het volledige grensvlak beoordeeld. Eén afgerond punt op een bijna samenvallende grens kan daardoor geen werkelijke eigenaar meer laten verdwijnen. De totale dekkingscontrole blijft actief.

Geen capaciteits- of afstandsgrenzen verhoogd, geen ontbrekende kabels verzonnen en geen aansluitingen weggelaten. Het resultaat gebruikt de bestaande voorbereide XML/Excel/BAG-invoer. Getest in QGIS 4.2.3; geen volledige nieuwe bronimport, handmatige volledige Desktop-kliktest of QGIS 3-test. [Volledige testverantwoording](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/VAARTBROEK_VALIDATION.md).

Installeer de release-ZIP en herstart QGIS volledig.

## Behouden uit v1.27.2

## Den Dungen: clustering met plangebied

Smalle verbindingsstroken tussen kabels en clustergebieden konden overlappen. De gebiedsopbouw verdeelt nu alleen die betwiste vlakken op basis van de werkelijke kabels, aansluitverbindingen en stations. Lege afgesneden fragmenten worden waar mogelijk aan een aangrenzend gebied toegevoegd. Gedeelde grenzen krijgen dezelfde knopen. Toewijzingen en kabelroutes worden niet verschoven; bestaande capaciteits-, route- en geometriecontroles blijven gelden.

Den Dungen is met de reeds voorbereide invoer volledig doorgerekend: **1.985 aansluitingen, 16 bestaande en 18 nieuwe stations**, totale ontwerpstroom **16.747 A**, langste route **642,81 m** bij een grens van 850 m. De volledige gebiedsdekking is geldig, zonder meetbare overlap of gedeeld kabeltracé. Het QGIS-project met twee layouts is opnieuw geopend en gecontroleerd.

De oude fout ‘Kabelroute 28 ligt 0.71 m buiten het eigen gebied’ is gereproduceerd met de instelling die het kabelnet op het plangebied knipt. Gebruik de sinds v1.27.1 standaard aangevinkte optie **Kabels buiten het plangebied gebruiken om aansluitingen binnen het plangebied te bereiken**. De volledige omweg telt mee; de routelimiet wordt niet versoepeld. De lokaal aangetroffen installatie was nog v1.27.0.

Getest in echte QGIS 4.2.3-processen, inclusief gebiedsreparatie, bestaande clusterfuncties, dashboardwidgets, buitenroutes, fout-/projectherstel en latere stroomwijziging. De productieproef hergebruikt voorbereide XML/Excel/BAG-resultaten; geen volledige nieuwe bronimport, handmatige volledige Desktop-kliktest of QGIS 3-test. Er zijn geen productiegegevens naar GitHub geüpload. [Volledig verslag](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/DEN_DUNGEN_VALIDATION.md).

Installeer de release-ZIP en herstart QGIS volledig.

## Behouden uit v1.27.1

## Kabels buiten het plangebied gebruiken

In **3a. Automatische clustering** staat de optie **Kabels buiten het plangebied gebruiken om aansluitingen binnen het plangebied te bereiken** standaard aan. De keuze is ook beschikbaar bij Geavanceerd → Berekening en in de Processing-tool.

- De volledige kabelroute mag het plangebied verlaten en weer binnenkomen. De volledige omweg telt mee voor de maximale kabellengte; capaciteits- en exclusiviteitscontroles blijven actief.
- De aparte selectie van aansluitingen en bestaande stations via het plangebied blijft gelden. Nieuwe stations worden binnen het plangebied geplaatst; clustergebieden worden op het plangebied begrensd.
- Als het plangebied een aangesloten route in losse vlakken knipt, mogen de binnenliggende gebiedsdelen meerdere vlakken vormen. Ieder vlak moet de echte route raken. Willekeurige losliggende gebiedsdelen blijven afgewezen.
- Uitvinken knipt het netwerk weer op de plangebiedgrens. Zonder plangebied is de optie niet van toepassing.
- De instelling wordt opgeslagen. Nieuwe resultaten bewaren hun routingkeuze voor latere handmatige correcties, stroomwijzigingen en routeherberekening. Bestaande resultaten zonder deze informatie houden hun oorspronkelijke beleid; voer stap 3 opnieuw uit om de nieuwe optie toe te passen.
- De kaart- en layoutuitsnede neemt de volledige gebruikte routes mee.

**Validatie:** echte QGIS 4.2.3-test met een U-vormige route van 40 m die buiten het plangebied loopt, afwijzing bij uitgeschakelde optie en bij te lage routelimiet, selectie van objecten binnen het plangebied, nieuw station binnen de grens, een meerdelig plangebied, bewaren/heropenen van de keuze en latere stroom-/routeherberekening. Bestaande cluster-, dashboard-, herstel- en layouttests slagen. [Volledig testverslag](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/EXTERNAL_PLAN_ROUTES_VALIDATION.md).

Installeer de release-ZIP en herstart QGIS volledig.

## Behouden uit v1.27.0

## Nieuw in deze release

- **1.3. Nieuwbouw:** plaats zelf aansluitbolletjes zonder BAG-object. Kies woningtypeberekening, vier handmatige stroomwaarden of later bepalen. Punten blijven herkenbaar als handmatige nieuwbouw, krijgen een eigen NWB-nummer en geen verzonnen BAG-ID. Kaartkeuze, annuleren en beschermd undo zijn beschikbaar. Voer stap 3 opnieuw uit om toegevoegde bronpunten mee te clusteren.
- **4i. Ontwerpstroom na clustering aanpassen:** wijzig de clusterbelasting van geselecteerde aansluitingen met bijgewerkte stationsbelasting/benutting, capaciteitscontrole, voorstelcontrole en undo. De oorspronkelijke verbruiks-/opwekvelden blijven apart; een nieuwe automatische clustering gebruikt die bronvelden opnieuw.
- **Duidelijkere clusteringfouten:** een blijvend controleproject met invoerkopieën, losse kabelcomponenten, technische diagnose en vervolgstappen. Het dashboard heeft knoppen om dit te openen.
- **Zonder plangebied:** herhaalpogingen respecteren de topologische ondergrens voor stations; ook losse nulstroomdelen zonder station worden meegenomen. Kabeldelen zonder aansluitingen hoeven geen vrije nieuwe stationslocatie te hebben.
- **Herstelbare uitvoer:** een PNG/PDF-fout behoudt de berekende lagen; een fout in de uitgebreide layout levert een eenvoudig QGIS-project met de resultaatlagen en een zichtbare waarschuwing.

**Vaartbroek:** getest op lokale kopieën van de bestaande voorbereide invoer, 4.266 aansluitingen en 39 kabelcomponenten, zonder plangebied. Nog geen geldige volledige stationsselectie gevonden tot en met 43 nieuwe stations binnen 850 m. Er is geen volledig geslaagde Vaartbroek-clustering aangetoond. Een controleproject is wel gemaakt en gecontroleerd. De brongegevens zijn niet naar GitHub geüpload.

**Tests:** echte QGIS 4.2.3-widgets, kaartcanvas, GeoPackages, automatische clusteruitvoer voor handmatige punten, stroomwijzigingen, undo na heropenen, foutinjectie voor reken-/kaart-/layoutfouten en bestaande regressies. Alle 89 Python-bronnen hebben geldige syntax. Geen handmatige volledige Desktop-test en geen QGIS 3-uitvoering. [Volledige testverantwoording](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/CLUSTER_RECOVERY_VALIDATION.md).

**Installatie:** installeer de release-ZIP via Plugins → Plugins beheren en installeren → Installeren vanuit ZIP en herstart QGIS volledig.

## Behouden uit v1.26.0

Het gekleurde dashboard heeft vier extra ingangen onder **4. Clustering aanpassen**. De bestaande 4a–4d blijven beschikbaar.

- **4e. Stationscapaciteit aanpassen:** wijzig ontwerp-kVA, met overbelastingscontrole en bijgewerkte afgeleide velden. De keuze wordt apart bewaard voor volgende berekeningen.
- **4f. Clusters samenvoegen:** expliciete bron/doelkeuze via de bestaande gecontroleerde stationsuitfasering. De broninventaris blijft behouden.
- **4g. Cluster splitsen / station bijplaatsen:** selecteer een deel van één cluster, geef naam en capaciteit op en kies een bestaande sleufknoop binnen het brongebied. Het extra station krijgt echte kabelroutes. Het bronstation houdt aansluitingen; flatgroepen blijven bijeen.
- **4h. Clusters controleren / herberekenen:** handige kaartselecties en routevernieuwing voor één of alle stations met behoud van toewijzingen. Terugvallen op oude routes worden als fout gemeld.

De bewerkingen gebruiken de wachtrij, **Voorstel controleren**, **Alles toepassen** en exact undo. Toegevoegd zijn wachtrij wissen, controle op gewijzigde bronlagen/stationsregels vlak vóór opslaan, bescherming van undo tegen latere stationskeuzes en controle op geldige gebieden, overlap en plangebieddekking. De voorstelcontrole berekent capaciteit en routes; definitieve gebiedscontrole volgt bij toepassen.

**Validatie:** geslaagde QGIS 4.2.3-tests voor de nieuwe functies, echte dashboardknoppen, kaartkiezer met CRS-transformatie/annulering, GeoPackage-invoegen en exact undo, ongeldige voorstellen, bestaande verplaatsing/herverdeling, SQLite-rollback, begeleide editor, netwerkonderhoud, gebiedsvormen en menuactie. Alle 85 Python-bronnen zijn op syntax gecontroleerd.

**Testgrenzen:** uitgevoerd met echte PyQGIS/Qt-widgets, echte workers en een kaartcanvas met een kleine Desktop-shellvervanger, op representatieve synthetische netten. Geen handmatige volledige QGIS Desktop-productietest, geen volledige nieuwe automatische clustering met productie-GEN/XML/Excel en geen QGIS 3-uitvoering. Lege reserve-stations, vrije plaatsing buiten sleuven, automatische optimale splitsing en meerdere undo-/redo-stappen zijn niet toegevoegd.

**Installatie:** installeer de ZIP via Plugins → Plugins beheren en installeren → Installeren vanuit ZIP en herstart QGIS volledig. De ZIP bevat uitsluitend de pluginmap `ls_netontwerp_wizard/`, zonder Python-cachebestanden.

[Volledig uitvoeringsplan en testverantwoording](https://github.com/LukaStuurman/Techbase-GEN-plugin/blob/main/CLUSTER_EDITING_VALIDATION.md)
