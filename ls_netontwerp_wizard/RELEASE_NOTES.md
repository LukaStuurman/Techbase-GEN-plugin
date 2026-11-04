# LS Netontwerp Wizard v1.28.0

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
