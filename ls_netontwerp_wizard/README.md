# LS Netontwerp Wizard voor QGIS

Versie 1.17.5 laat het paneel **Type wooneenheid / aansluiting** meegroeien
wanneer bij Zakelijk de extra gasaansluitkeuze verschijnt. De keuzelijsten
en toelichting overlappen niet meer. Dit geldt voor **2a. Ontwerpstroom
aanpassen** en **2d. Nulwaarden herstellen**, ook na wisselen van categorie.
`test_uniform_ui.py` controleert beide panelen op overlap en afgekapte
toelichting bij verschillende vensterformaten.

Versie 1.17.4 onderscheidt BAG-verblijfsobjecten op basis van `gebruiksdoel`:

* **Woonfunctie:** woningtype en bouwjaar komen uit de woningtypenlaag.
  Geldige pandstromen worden overgenomen; anders worden de ingestelde
  huishoudelijke tabellen gebruikt. Ook meerdere gebruiksdoelen met
  `woonfunctie` worden herkend. Ontbrekende woninggegevens kun je aanvullen.
* **Andere gebruiksdoelen:** kantoor, winkel en andere objecten krijgen
  geen woningstromen mee van het pand. Na toevoegen opent automatisch
  **Nulwaarden herstellen** met BAG-ID, adres en gebruiksdoel. Selecteer
  een of meer regels en kies categorie, type wooneenheid en eventueel gas,
  of typ zelf de vier stroomwaarden.
* **Herberekenen:** de aanduiding `verblijfsobject` blijft in
  `service_connection_type_type`. Bij woonfunctie worden woningtype- en
  bouwjaartabellen gebruikt zonder een elektrische doorlaatwaarde te verzinnen.
  Andere gebruiksdoelen blijven zonder stroom tot de gebruiker een keuze maakt.
  Opgeslagen keuzes en handmatige BAG-stromen blijven bij een algemene
  herberekening behouden. Een wijziging van een pandwoningtype herberekent
  alleen BAG-objecten met woonfunctie en vervangt daar de eerdere correctie.
* Eerder toegevoegde niet-woonobjecten met pandstromen verschijnen eveneens
  in het hersteloverzicht zolang ze nog geen eigen categoriekeuze hebben.

Installeer `ls_netontwerp_wizard-1.17.4.zip` en herstart QGIS.
`test_bag_usage_currents.py` controleert gemengde gebruiksdoelen in hetzelfde
pand, de herstelbediening, de volledige ruimtelijke herberekening,
GEN-bronvelden, pandwoningtypewijzigingen en de gekozen doellaag.

Versie 1.17.3 vult bij het toevoegen van BAG-verblijfsobjecten via **2e.
Stationskoppeling en nieuwbouw** de kolom `service_connection_type_type`
(doorlaatwaarde uit GEN) met `verblijfsobject`.
Als de tekstkolom ontbreekt, wordt deze aangemaakt. De aanduiding wordt samen
met de nieuwe objecten opgeslagen. Bestaande GEN-aansluitingen behouden hun doorlaatwaarde.

Versie 1.17.1 maakt bij **2d. Nulwaarden herstellen** de zakelijke keuzes
**Type wooneenheid** en **Gasaansluiting** zichtbaar in eigen panelen, zonder
een extra scrollvak binnen de pagina.

Bij **2a. Ontwerpstroom aanpassen** en **2d. Nulwaarden herstellen** kun je in
alle categorieën de vier stroomwaarden zelf typen: trafoverbruik,
kabelverbruik, trafo-opwek en kabelopwek. Dit geldt ook voor huishoudelijk.
Typen schakelt **Zelf ingevulde stroomwaarden gebruiken** in. De vier waarden
worden voor alle geselecteerde aansluitingen opgeslagen; Hoogste Trafo en
Hoogste Kabel volgen automatisch het maximum van verbruik en opwek.
Ook een bewust ingevulde nulwaarde blijft behouden. Enter bevestigt het
getal zonder een navigatie- of uitvoerknop van het venster te activeren.

Schakel het vinkje uit of kies opnieuw een woningtype/aansluitwaarde of
gascategorie om de tabelberekening te gebruiken. Huishoudelijke tabellen
blijven zonder handmatige invoer per aansluiting het bouwjaar volgen.
De handmatige keuze wordt opgeslagen in `HerstelHandmatig` en bij opnieuw
openen van 2a hersteld. Een nieuwe pand-/woningtypeberekening wist deze keuze.

Installeer `ls_netontwerp_wizard-1.17.1.zip` vanuit QGIS' pluginbeheer en
herstart QGIS. `test_manual_currents.py` controleert echte toetsenbordinvoer,
oude/nieuwe huishoudelijke aansluitingen, opnieuw openen, terugschakelen
naar tabellen, de vier categorieën en zakelijke nulwaardenherstelacties.

Versie 1.17.0 brengt alle menu's en opties samen in één TechBase-vormgeving.
Het dashboard, broncontrole, LOVION/BAG-nieuwbouw, clustercorrectie,
sleuven/routes, gebieden, geavanceerde tabbladen, ontwerpstroomtabellen en
beide visuele clustereditors gebruiken dezelfde kleuren, typografie,
panelen, invoervelden en knoppen.

* Oranje knoppen voeren een wijziging uit; neutrale knoppen openen, zoeken,
  vernieuwen en navigeren. Kaartacties hebben een lichte oranje achtergrond.
  Verwijderen blijft rood herkenbaar, evenals de stopknop.
* De kop blijft bovenaan staan. Home staat op iedere subpagina rechtsonder,
  samen met de belangrijkste actieknoppen. Lange optielijsten kunnen scrollen.
* De invoer op het dashboard staat in twee kolommen. Alle werkstappen hebben
  dezelfde witte panelen. `Advanced` heet nu `Geavanceerde opties`.
* Dropdowns, aanvinkvakjes en getalvelden gebruiken dezelfde duidelijke
  bedieningstekens. Tabellen tonen hun kolomkoppen op inhoudsbreedte.
  De gele/rode gascategorieën en bestaande statuskleuren blijven behouden.
* De nieuwbouwpagina kan na Home opnieuw worden geopend. De handmatige
  clustereditor bouwt zijn acties vóór het indelen van de pagina op, zodat
  knoppen niet over elkaar of over het volgende paneel vallen.
* Informatie- en meldingsvensters van de plugin volgen dezelfde stijl.
  Native bestandskiezers en QGIS-vensters buiten de plugin behouden hun
  systeembediening.

De ontwerp- en berekeningsinstellingen blijven beschikbaar. Installeer
`ls_netontwerp_wizard-1.17.0.zip` vanuit QGIS' pluginbeheer en herstart QGIS.
De UI-controle `test_uniform_ui.py` doorloopt negen pagina's, hun geavanceerde
opties, alle ontwerpstroomtabellen, beide editormodi en de Home-navigatie.

Versie 1.16.1 gebruikt bij **2a. Ontwerpstroom aanpassen** en **2d. Nulwaarden
herstellen** de namen uit de kolom `Type wooneenheid` van Eea-0205.K 3.2:

* Zakelijk: tien huidige aansluitwaarden van `< 3x35A` t/m `3x250A`, met
  herkenbare aanduiding van type 8 (kleinzakelijk) of type 9 (grootverbruik).
* Laden: `Aansluiting 3x25A` (type 10: Netbewust publiek laden).
* Straatmeubilair: vijf aansluitwaarden van `1x6A` t/m `3x63A t/m 3x80A` (type 11).
* Huishoudelijk: Vrijstaand, Twee onder een kap, Appartement incl. publiek laden,
  Rijtjeswoning (woonboten, woonwagens, chalets en vakantiehuisjes), Hoekwoning en Onbekend.

Bij **Zakelijk** verschijnt daarnaast `Gasaansluiting` met de Excel-kleuren:
`G4, G6, geen of ander gas` (geel), `G10 t/m G25` (rood) en `> G25` (donkerrood).
Het kiezen van een aansluitwaarde of gascategorie vult de vier stroomvelden in
via de ingestelde tabellen. Trafo en kabel gebruiken hun eigen gastabel.
Je kunt de stroomvelden vervolgens aanpassen, of `Zelf invullen` kiezen.
De gekozen aansluitnaam wordt in `HerstelType` bewaard, de categorie in
`HerstelCat` en zakelijk gas in de ingestelde gaskolom (standaard `G_Type`).
Opnieuw openen herstelt deze keuzes. Een nieuwe woningtypeberekening vervangt
de eerdere handmatige correctie en wist de bijbehorende keuzemarkeringen.

De presetnamen komen uit de aangeleverde Excel 3.2. De stroomwaarden volgen
het kader en de tabellen van het geopende werkproject. De bestaande kaderkeuze
3.0/3.1 voor straatmeubilair blijft dus actief.

Installeer de bijgewerkte ZIP `ls_netontwerp_wizard-1.16.1.zip` via QGIS →
Plugins beheren en installeren → Installeren vanuit ZIP en herstart QGIS.

Versie 1.16.0 voegt op het dashboard **2e. Stationskoppeling & nieuwbouw** toe.

* **LOVION:** kies de volledige workbench-CSV. `Master Asset ID` koppelt exact
  aan de bestaande ontwerpstroomlaag en `SourceFile` wordt de tekstkolom `Station`.
  Ongekoppelde aansluitingen houden hun bestaande stationsnummer. Selecteer
  aansluitingen op de kaart en kies of typ een ander stationsnummer om de
  selectie blijvend te wijzigen. Voorloopnullen blijven behouden.
* **Nieuwbouw:** laad de PDOK BAG-verblijfsobjecten, zoom naar het gewenste
  gebied en selecteer de adressen op de kaart. De geselecteerde objecten worden
  aan de blijvende ontwerpstroomlaag toegevoegd. De adresmapping is
  `bronhouder_naam → city`, `woonplaats_naam → parish`, `huisnummer → housenumber`,
  `huisletter → toevoeging`, `postcode → zip_code` en
  `openbare_ruimte_naam → street`. Een aanvullende huisnummertoevoeging blijft
  apart bewaard in `huisnummertoevoeging`.
* Het pand op de locatie levert `Woningtype`, bouwjaar en eventuele expliciete
  ontwerpstromen. Anders worden huishoudelijke stromen berekend uit het
  woningtype en de ingestelde kader-/bouwjaartabellen. Bij meerdere overlappende
  panden met verschillende typen wordt geen willekeurig pand gekozen.
  Ontbreekt een bruikbaar pand/type, kies dan een woningtype of vul vier
  stroomwaarden als terugval in. Overige ontbrekende waarden verschijnen bij
  **2d. Nulwaarden herstellen**. `Hoogste Trafo` en `Hoogste Kabel` volgen steeds
  het maximum van verbruik en opwek.
* BAG-identificaties en bestaande adrescombinaties voorkomen dubbele toevoeging.
  Appartementen op dezelfde locatie blijven afzonderlijke aansluitingen.
* **Onbekend / overig** wordt expliciet opgeslagen als `onbekend` en gebruikt
  bij een huishoudelijke correctie de onbekend-rij in de stroomtabellen.

Gebruik deze bronbewerkingen na stap 1 en vóór het maken van de clustering.
Bij kaartselectie keert het dashboard automatisch terug na de selectie.
De ontwerpstroomlaag moet opgeslagen bewerkingen hebben voordat je toevoegt
of stationsnummers koppelt/wijzigt.

Installeren: QGIS → Plugins → Plugins beheren en installeren → Installeren
vanuit ZIP, selecteer `ls_netontwerp_wizard-1.16.0.zip` en herstart QGIS als de
plugin eerder geladen was.

Integratiecontrole: `test_connection_sources.py` controleert de dashboardroute,
stationsselectie, het behouden van ongekoppelde waarden, nieuwbouw/adresmapping,
appartementen, CRS-transformatie, GeoPackage-opslag, handmatige waarden,
pandstromen en beide onbekend/overig-correcties. Optioneel controleert
`--live-pdok` ook een echte PDOK-opvraag; `--csv PAD` leest een lokale LOVION-CSV.

Versie 1.15.22 voegt de optionele stationsnaamkoppeling na stap 1 toe. De wizard leest de `SourceFile`-kolom en koppelt deze via `Master Asset ID` aan de ontwerpstroomlaag.

Versie 1.15.16 maakt plangebied optioneel en verbetert de wizardinterface. Zonder plangebied gebruikt de BAG-opvraag de omvang van de geïmporteerde LS-aansluitingen. De ontwerpstroomtabellen ondersteunen regels dupliceren/verplaatsen en kopiëren/plakken met spreadsheets.

Na stap 1 kan optioneel `2e. Stationsnamen koppelen` worden gebruikt om een CSV
met `Master Asset ID` en stationsnamen te laden. `SourceFile` wordt als
stationsnaam gebruikt; bij een ander CSV-formaat kan de kolom gekozen worden.
De wizard schrijft de namen in `Station` van `LS-aansluitingen ontwerpstroom`.
Aansluitingen zonder overeenkomst blijven leeg en de wizard meldt hoeveel
aansluitingen zijn gekoppeld.

Versie 1.12.0 vereenvoudigt de uiteindelijke gedeelde grenzen als één volledige
topologische dekking. Daardoor mogen ook lange rechte schuine grenzen worden
gebruikt wanneer die een reeks kleine horizontale/verticale verspringingen
vervangen. Een samenkomst van drie of meer clusters blijft exact één gedeeld
coördinaat: geen spleet, overlap of klein driehoekje. Buitenrand,
aansluitingsindeling, aaneengeslotenheid en het ontbreken van exclaves blijven
verplicht. De eindtolerantie staat standaard op maximaal 12 m en wordt
automatisch verlaagd wanneer een aansluiting anders buiten het eigen gebied
valt. In de Buitenpepers-test koos de tool veilig 8,40 m, daalde het resultaat
van 3.415 naar 237 hoekpunten en bleven alle 14 meervoudige clusterknopen exact
genood. Slechts 4 van 29 gedeelde grensrelaties kregen schuine segmenten.

Versie 1.11.1 houdt de gebieden overwegend rechthoekig, maar verwijdert kleine
trapvormige verspringingen langs iedere gedeelde grens â€“ ook wanneer slechts
twee clusters aan elkaar grenzen. Een lokale hoek mag worden vervangen door
één korte schuine afsnijding. Standaard is de afwijking maximaal 4 m en een
nieuw schuin segment nooit langer dan driemaal die waarde. Lange hoofdgrenzen
blijven dus horizontaal/verticaal. Iedere kandidaat wordt met dezelfde
topologie-, aansluitings- en exclavecontroles gevalideerd. In de
Buitenpepers-test verdwenen nog 4 hoekpunten; slechts 2 van 150 interne
segmenten werden lokaal schuin, met een maximale lengte van 10,01 m.

Versie 1.11.0 maakt stap 6 nadrukkelijk blokvormig. Eerst probeert de tool een
volledig rechthoekige verdeling op basis van de aansluitpunten met zo weinig
mogelijk horizontale en verticale scheidslijnen. Die variant wordt alleen
gebruikt wanneer ieder cluster één aaneengesloten gebied houdt. Daarna worden
lege smalle uitlopers en halzen iteratief aan het dichtstbijzijnde compacte
buurgebied gegeven. Een verbinding die nodig is om aansluitingen van hetzelfde
cluster bijeen te houden blijft bestaan, maar krijgt standaard minimaal 20 m
breedte. Advanced maakt deze blok-/halsbreedte instelbaar. Het resultaat bevat
geen exclaves, geen diagonale interne grenssegmenten en bewaart iedere
aansluiting in het eigen cluster. De Buitenpepers-test daalde van 3.415 naar 373
hoekpunten, met 29 van 29 volledig rechte gedeelde grensrelaties en nul
diagonale interne segmenten.

Versie 1.10.1 zet `Clustergebieden vereenvoudigd` expliciet in de vaste
kaarttekenvolgorde op de positie van de oorspronkelijke gebieden en altijd
boven OpenStreetMap. Daardoor is de laag na het maken direct zichtbaar en niet
alleen selecteerbaar. Rechte-hoekvereenvoudiging staat standaard aan: iedere
interne gedeelde grens wordt opgebouwd uit horizontale en verticale segmenten
met uitsluitend 90°-knikken. Eerst worden de kortste L- en Z-grenzen geprobeerd;
alleen wanneer aansluitingen dat vereisen volgt een nauwkeuriger trappad. Na
een laatste topologische reparatie blijven alle aansluitingen, gebieden en
gedeelde grenzen sluitend. In de Buitenpepers-test bleven van 3.415 nog 451
hoekpunten over en waren alle 198 interne grenssegmenten horizontaal of verticaal.

Versie 1.10.0 voegt de laatste stap `6. Mooie clustergebieden` toe. De wizard
herstelt kleine overlap in de berekende brongebieden, vereenvoudigt daarna alle
vlakken als één topologische dekking en zoekt automatisch de grootste veilige
tolerantie. Gedeelde grenzen blijven exact gelijk en geen aansluiting mag uit
het gebied van zijn eigen cluster vallen. De blijvende GeoPackage-laag
`Clustergebieden vereenvoudigd` bewaart ook de gebruikte tolerantie en het
aantal hoekpunten. Selecteer vervolgens precies twee aangrenzende gebieden en
teken één nieuwe grens: hun gezamenlijke buitenrand blijft ongewijzigd, overlap
en gaten zijn uitgesloten en vóór iedere wijziging wordt een GeoPackage-back-up
gemaakt.

Versie 1.9.4 versnelt `Nieuwe sleuf tekenen` zonder de bestaande netkwaliteit
te verlagen. Het al geknipte/genode netwerk wordt niet meer volledig opnieuw
samengevoegd: alleen lijnstukken die de nieuwe sleuf kruisen, raken of binnen
de knooptolerantie liggen worden lokaal opnieuw genood. Alle overige geometrie
en rekenfactoren blijven exact behouden. Raakt een nieuwe sleuf toch minstens
60% van het netwerk, dan kiest de tool automatisch het veilige volledige
noden. De aparte sleufworker importeert bovendien niet langer de zware
clusteringbibliotheken SciPy, Matplotlib en NetworkX. In de Buitenpepers-test
werd voor de getekende lijn 1 van 4.095 bestaande sleufdelen opnieuw berekend.

Versie 1.9.3 voorkomt dat een zichtbare clusterroute verdwijnt bij handmatig
herberekenen of routeverversing. Wanneer station en aansluiting na het noden
op dezelfde netwerkknoop vallen, bevat een wiskundig kortste pad nul lijnstukken.
De tool vervangt de oude route dan niet langer door een lege geometrie, maar
behoudt de bestaande route en Route_m en toont een waarschuwing met de
betreffende stationsnaam. Als een oude route al ontbreekt, probeert de tool hem
vanaf de dichtstbijzijnde knopen van het actuele genode sleuvennet te herstellen.
Ook het terugschrijven naar de projectlaag weigert als extra beveiliging een
lege resultaatroute over een bestaande geometrie heen te schrijven.

Versie 1.9.2 verwijdert de dubbele, verkleinde layoutlagen uit het gemaakte
QGIS-project. Kaartvenster en Print Layout gebruiken nu dezelfde blijvende
GeoPackage-laag; die ene stijldefinitie gebruikt layoutafhankelijke vaste
millimetermaten voor de kleinere symbolen, labels en routes. Handmatige cluster-, route- en
sleufbewerkingen schrijven hun QGIS-invoer voortaan naar één tijdelijke
GeoPackage en slaan niet na iedere bewerking nogmaals het volledige QGIS-project
synchroon op. De zichtbare projectlaag wordt nog steeds rechtstreeks aangepast;
de aparte rekenomgeving en herstelback-up blijven behouden voor stabiel
herhaald gebruik.

Versie 1.9.1 herstelt het tekenen van een nieuwe sleuf. Na het vastleggen
geeft QGIS de tijdelijke tekenfeature een nieuw ID; de wizard controleert nu
de werkelijk opgeslagen geometrie, zodat geldige lijnen niet meer onterecht
als lengte nul worden afgewezen. De netwerkpagina bevat bovendien
`Geselecteerde routes verversen`: selecteer eerst één of meer objecten uit
`Kabelroutes per cluster` of `Stations ontwerp`; uitsluitend die clusters
krijgen daarna een nieuw kortste exclusieve kabelroute. De overige routes
blijven ongewijzigd.

Versie 1.9.0 voegt de interne pagina `5. Sleuven/routes` toe. `Nieuwe sleuf
tekenen` activeert direct de QGIS-lijntool; na afsluiten met de rechter
muisknop wordt de lijn blijvend aan `Sleuven geknipt/genood` toegevoegd. Het
volledige net wordt exact geknipt op kruisingen en T-aansluitingen en kleine
eindpuntspleten worden binnen de instelbare tolerantie verbonden. De handmatige
clustercorrectie kan die nieuwe knopen daarna meteen gebruiken. `Alle
clusterroutes verversen` houdt iedere aansluiting bij hetzelfde station, maar
bouwt alle routes opnieuw op als kortste exclusieve kabelpaden. Daardoor kan
een nieuw getekende sleuf een bestaande langere route vervangen. Route_m,
routegeometrieën, gebieden, stationstatistieken, tabel, legenda en layout
worden gezamenlijk vernieuwd. Beide acties maken eerst een GeoPackage-back-up;
Advanced maakt lagen, tolerantie, maximale route en routecontroles instelbaar.

Versie 1.8.0 verfijnt uitsluitend de QGIS-printlayout: stationssymbolen staan
op 67%, stationslabels op 50% met extra afstand tot het symbool, flatkasten op
20% in kaart en legenda en gekleurde kabelroutes op 20% lijndikte. De gewone
QGIS-kaartweergave blijft ongewijzigd. De stationstabel bevat een blijvend
`Volgnummer`. Na handmatig samenvoegen of verwijderen van een cluster worden
de bestaande stations eerst en de nieuwe stations daarna opnieuw doorlopend
genummerd; tabelwaarden, legenda-categorieën en de layoutweergave
worden meteen vernieuwd.

Versie 1.7.0 toont in de controlefase na stap 1 ook `Bestaande stations
(bron)`. Geldige bestaande stations gebruiken hetzelfde rode, zwart omlijnde
vierkant als na de clustering en vaste labels met stationsnaam en `Max_A`. De
wizard voegt `Max_A` numeriek en blijvend aan de stations-GeoPackage toe met
de berekening `kVA / 0,23 / 3`. De nieuwe interne knop `2c. Stations aanpassen`
kiest de stationslaag en de velden automatisch. Geselecteerde stations kunnen
één nieuwe trafocapaciteit krijgen, waarbij `Max_A` direct opnieuw wordt
berekend, of na bevestiging definitief worden verwijderd. Beide wijzigingen
worden in de bronlaag opgeslagen en worden daardoor rechtstreeks gebruikt
door stap 3. Advanced maakt stationslaag, stationsnaam-, capaciteit- en
Max_A-kolom instelbaar. Dezelfde functie is ook beschikbaar in het pluginmenu
en als Processing-algoritme.

Versie 1.6.0 versnelt de clustering zonder route-, capaciteit- of
gebiedscontroles te versoepelen. Kortste-padafstanden worden per kabelbron
hergebruikt, exact onhaalbare MILP-benuttingsgrenzen worden vooraf
overgeslagen, nulmeterdelen worden ruimtelijk geïndexeerd en onafhankelijke
kandidaatcontroles gebruiken maximaal 24 logische processors. Op de volledige
Buitenpepers-praktijkset daalde stap 3 van circa 427 naar 351 seconden (18%),
terwijl alle 1.370 aansluitingstoewijzingen, 16 stations, gebieden, routes en
het genode kabelnet bytegelijk bleven. De layout toont verplichte
stationslabels ook bij overlap, gebruikt aansluitingssymbolen en -cijfers op
40% van de kaartvenstergrootte, bewaart 600 dpi als exportresolutie en gebruikt
OpenStreetMap tot zoomniveau 19 met HiDPI-tegels.

Versie 1.5.9 integreert ook `2a. Stroom aanpassen` en `2b. Woningtype
aanpassen` volledig in het TechBase-wizardvenster. Beide pagina's hebben een
Home-knop, automatische laag- en kolomkeuze, kaartselectiestatus, interne
voortgang en een resultaatmelding. Bij stroom aanpassen kies je huishoudelijk,
zakelijk, laadpunt of straatmeubilair. Trafo- en kabelverbruik en trafo- en
kabelopwek worden opgeslagen; Hoogste Trafo en Hoogste Kabel worden daaruit
opnieuw berekend. Advanced maakt de aansluitingenlaag instelbaar. Bij
woningtype aanpassen wordt het gekozen BAG-woningtype opgeslagen en worden
gekoppelde aansluitingen opnieuw berekend; Advanced toont beide lagen en alle vijf gebruikte kolommen. De
nulwaardenpagina 2d toont en schrijft verbruik en opwek voor trafo en kabel,
plus de opnieuw berekende hoogste waarden. Ook de aparte plugin-menukeuzes
openen voortaan deze interne pagina's.

Versie 1.5.8 brengt de volledige handmatige clustercorrectie onder in een eigen
TechBase-pagina binnen het wizardvenster. Met `Home` ga je zonder een nieuw
venster terug naar het beginscherm. De normale modus kiest de bekende blijvende
resultaatlagen automatisch en activeert alle veiligheidscontroles. `Advanced`
toont alle zes laagkeuzes, het samenvoegen/verwijderen van een broncluster,
`ALLES TOESTAAN`, de vier afzonderlijke controles, maximale route,
knooptolerantie en back-upmap. Voortgang, waarschuwingen en resultaat blijven
op dezelfde pagina. Ook de losse plugin-menukeuze opent deze interne pagina.

Versie 1.5.7 geeft bestaande stations een rood gevuld vierkant en nieuwe
stations een lichtblauw gevulde ster. Stationslabels tonen nu naast de naam
ook `Max_A` en `Belast_A`, afgerond op hele ampères. De kaartlayout gebruikt
een tweede blijvende weergave van dezelfde aansluitingenlaag met symbolen,
ontwerpstroomcijfers en tekstbuffers op exact 50%; in het gewone kaartvenster
blijft de oorspronkelijke goed leesbare grootte behouden.

Versie 1.5.6 voegt aan de handmatige correctie de optie `Hele broncluster
samenvoegen en verwijderen` toe. Eén geselecteerde aansluiting identificeert
de broncluster; alle aansluitingen daarvan verhuizen naar het geselecteerde
doelstation en het oude station-, gebied- en routerecord worden uit de
blijvende resultaatlagen verwijderd. De hoofdschakelaar `ALLES TOESTAAN`
overrulet in één keer alle vier veiligheidscontroles. In het wizardvenster
opent `4b. Vrij aanpassen` de tool direct met deze vrije modus actief. Als
zelfs geen kabelpad tussen verschillende netcomponenten bestaat, gebruikt deze
bewust vrije modus een gemelde directe correctieroute zodat de gekozen
toewijzing toch altijd wordt uitgevoerd.

Versie 1.5.5 voorkomt dat de aparte handmatige-correctieworker vastloopt op
volle Windows-uitvoerpipes. Voortgang en fouten worden tijdens het rekenen
direct in QGIS getoond. De correctie hergebruikt bij de standaard
knooptolerantie 0 het al geknipte/genode sleuvennet en leidt ongewijzigde
clusterroutes af uit dat ene netwerk, in plaats van alle routes per station
opnieuw te knippen. Een volledige lokale correctietest daalde daarmee van
meerdere minuten naar ongeveer twaalf seconden.

Versie 1.5.4 houdt de gefilterde aansluitkabellaag nu daadwerkelijk in het
rekennet. Eerder werd deze laag wel gelezen en gezamenlijk genood, maar bij het
opbouwen van het definitieve netwerk per ongeluk weer vervangen door alleen de
hoofdkabels. Alleen werkelijk ontbrekende aansluitingen krijgen nog een
automatische verbinding. De wizard heeft daarnaast de knop `4. Clustering
aanpassen`, die de blijvende resultaatlagen automatisch in de bestaande
handmatige correctietool selecteert. Het opruimen van tijdelijke
kabel-Voronoi-kandidaten gebeurt in veilige batches voor een kortere rekentijd.

Versie 1.5.3 schakelt bij een mislukte nieuwe-stationsselectie direct over op
een kabelverbonden kortste-padverdeling. Die terugval bepaalt zelf hoeveel
nieuwe stations nodig zijn en voorkomt dat een geldige kabeltopologie na een
reeks mislukte aantallen (zoals 20 stations) ten onrechte wordt afgekeurd.

Versie 1.5.2 verwerkt alle voortgang in het hoofdvenster van de plugin. Een
korte statusregel staat boven de balk; volledige lange meldingen komen in het
optionele detailvak. De clustering kan na een topologische verhoging naar
bijvoorbeeld 16 stations nu ook automatisch 17 tot en met 26 proberen. Voorheen
eindigde de retryreeks precies bij 16 en verscheen direct de fout dat zestien
stations niet geselecteerd konden worden.

Versie 1.5.1 herstelt de volledige workflow onder QGIS 4.2. Het plangebied
wordt nu geometrisch en expliciet naar RD New getransformeerd, omdat de oude
writer-optie in QGIS 4 stil werd genegeerd. De BAG-omvang gebruikt alleen
plausibele LS-aansluitingen rond het plangebied, zodat een geometrische
uitschieter geen landelijke of miljoenenmeters grote opvraag kan veroorzaken.
Stap 1 en stap 3 zijn zonder handmatige correctiestap volledig geïntegreerd
getest, inclusief GeoPackage, project, layout, PDF en PNG.

Versie 1.5.0 haalt woningtypen op voor de gezamenlijke omvang van het
plangebied en alle geïmporteerde LS-aansluitingen, plus 25 meter marge. Daardoor
krijgen ook aansluitingen buiten de plangrens een BAG-woningtype. De nieuwe
stap `2b. Woningtype aanpassen` wijzigt geselecteerde BAG-panden blijvend naar
een gekozen woningtype en herberekent direct alle bijbehorende
ontwerpstroomvelden van de aansluitingen.

Versie 1.4.4 legt de render-volgorde na stap 1 expliciet vast met
OpenStreetMap als laatste en dus onderste kaartlaag. De ontwerpstroombollen,
hun omlijning, cijfers en witte tekstbuffer gebruiken vaste schermeenheden
(pixels), waardoor ze bij in- en uitzoomen even groot blijven.

Versie 1.4.3 voegt boven in de wizard een informatieknop toe. Het venster legt
de volledige voorbereiding in GEN uit: ruim een trail tekenen, de meegeleverde
query uitvoeren, alle resultaten selecteren en eerst als XML en daarna als
Excel exporteren. Ook staat de noodzakelijke tweede Excel-exportstap vermeld.
De volledige GEN-query staat in het venster en kan met één knop naar het
klembord worden gekopieerd.

Versie 1.4.2 schakelt schaalafhankelijke zichtbaarheid voor alle lagen uit.
Na stap 1 zijn OpenStreetMap, woningtypen, ontwerpstroomaansluitingen, beide
kabellagen en het plangebied aangevinkt. Woningtypen krijgen hun vaste
categorie-opmaak. De twee kabellagen worden gecategoriseerd op hun gekozen
`function`-kolom; alleen categorieën met de ingestelde Function-woorden
(standaard `LS`) zijn binnen de legenda aangevinkt.

Versie 1.4.1 zet het plangebied in stap 1 altijd zichtbaar boven de bronlagen,
zonder vlakvulling en met een rode begrenzing van 1 mm. Na stap 1 zoomt de
kaart naar de volledige omvang van het plangebied.

Versie 1.4.0 gebruikt de TechBase-huisstijl en het TechBase-logo in het
pluginmenu, de werkbalk en het hoofdvenster. Onder
`Advanced > Ontwerpstroomtabellen` staan nu dezelfde instelbare matrices als in
de losse ontwerpstroom-processingtool: woonhuis (oud en nieuw), kabelwaarden,
opwek, ampèrestaffels, gebruikstypen, straat, laden, gas, regex- en
trefwoordclassificatie. Wijzigingen worden rechtstreeks aan de berekening
doorgegeven.

Versie 1.3.0 gebruikt een gefaseerde workflow:

1. Direct bij de start wordt een blijvend `LS_netontwerp_werkproject.qgz`
   gemaakt. Import-, plangebied- en controlelagen worden tijdens de berekening
   aan ditzelfde project toegevoegd.
2. Na de ontwerpstroomberekening pauzeert de wizard. De laag
   `LS-aansluitingen ontwerpstroom` toont `Hoogste Trafo` in vaste kaartlabels.
   Selecteer aansluitingen en gebruik `Hoogste trafo en kabel aanpassen
   (selectie)`; de waarden worden rechtstreeks in het blijvende GeoPackage
   opgeslagen. Deze stap mag onbeperkt worden herhaald.
3. `Clustering maken` gebruikt standaard en expliciet `Hoogste Trafo` als
   ontwerpstroom.
4. Na de clustering is `Handmatige clustercorrectie (selectie naar station)`
   beschikbaar in het pluginmenu, de werkbalk en de Processing-provider.

Het werkproject bevat een workflowstatusbestand, zodat de controlefase na het
opslaan, sluiten en opnieuw openen van het project kan worden hervat.

Versie 1.2.0 introduceerde daarnaast de plaatsing van nieuwe stations bij
voorkeur uitsluitend op de gekozen
hoofdkabellaag. Knooppunten op aansluitkabels en binnen 1,5 meter van een
LS-aansluiting vallen af. Alleen in een volledig losse kabelcomponent zonder
hoofdkabel wordt het station naast de beschikbare kabel geplaatst en met een
korte stationsverbinding aan de berekende route gekoppeld.

De gemaakte QGIS-projectlagen gebruiken expliciet vaste millimeter-/puntmaten.
Daardoor blijven met name de gekleurde LS-bollen en hun ontwerpstroomcijfers bij
in- en uitzoomen even groot op het scherm.

Deze plugin voert de volledige workflow uit:

1. GEN XML en kabelgegevens uit Excel importeren;
2. optioneel plangebied naar RD New en GeoPackage omzetten;
3. BAG/3DBAG-panden ophalen en woningtypen bepalen;
4. ontwerpstroom per LS-aansluiting berekenen;
5. kabels gezamenlijk knippen/noden;
6. kabelverbonden stationsclusters berekenen;
7. GeoPackage, QGIS-project, Print Layout, PDF, PNG en CSV schrijven.

## Eenvoudige modus

Open in QGIS `Vector > LS Netontwerp > LS-netontwerp wizard` of gebruik de
werkbalkknop. Kies alleen:

- GEN XML;
- kabelgegevens Excel;
- uitvoermap.

Een plangebied is optioneel. Vink `Zonder plangebied werken` aan om een eerder
gekozen bestand tijdelijk uit te schakelen. De BAG-opvraag gebruikt dan de
omvang van de geïmporteerde LS-aansluitingen met 25 meter marge. Clustering
gebruikt in dat geval geen plangebiedfilter. Als de aansluitingen meer dan
100 km uiteen liggen, stopt de voorbereiding met een melding zodat de BAG-opvraag
niet onverwacht een zeer groot gebied bestrijkt.

De bekende GEN-laagnamen en kolommen zijn al ingevuld. Iedere uitvoering krijgt
een eigen blijvende resultaatmap, zodat een eerder resultaat niet wordt
overschreven.

De plugin detecteert standaard het aantal logische processors en gebruikt ze
automatisch, met één processor vrij voor QGIS en Windows. Op een computer met
24 logische processors gebruikt de standaardmodus dus 23 threads. Dit versnelt
BAG/3DBAG-opvragingen, HiGHS/SciPy-optimalisaties en onafhankelijke controles
van kandidaatstations. Afhankelijke hoofdstappen blijven in de juiste volgorde.

## Advanced

Zet `Advanced` aan om vijf tabbladen te tonen:

- `Import en BAG`: Excel-tabbladen, 3DBAG, threads en bron-CRS;
- `Lagen`: alle geïmporteerde aansluit-, kabel-, station-, flatkast- en
  verdeelkastlagen;
- `Kolommen`: doorlaatwaarde, gebruik, gas, woningtype, bouwjaar,
  ontwerpstroom, multistory, Function, stationsnaam en trafocapaciteit;
- `Berekening`: appartementfallback, knippen/noden, plangebiedfilter,
  automatische of handmatige CPU-threads, automatische stationskeuze, 630 kVA,
  90%, 850 meter en shapefile-optie.
- `Ontwerpstroomtabellen`: alle woonhuis-, kabel-, opwek-, ampère-, type-,
  straat-, laad-, gas- en classificatietabellen, plus de opwekfilters en
  fallbackwaarde voor laadpunten. Regels kunnen worden toegevoegd,
  gedupliceerd, verplaatst en verwijderd. Een volledige tabel is als
  tabgescheiden tekst te kopiëren en terug te plakken vanuit een spreadsheet;
  de standaardwaarden blijven per tabel herstelbaar.

De Advanced-instellingen wijzigen alleen de huidige uitvoering. De eenvoudige
standaarden blijven beschikbaar wanneer Advanced weer wordt uitgezet.

## Installatie

Pak `ls_netontwerp_wizard.zip` uit in de QGIS-pluginmap, zodat daarin direct de
map `ls_netontwerp_wizard` staat. Voor QGIS 4 is de standaardlocatie:

`%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins`

Herstart QGIS en activeer `LS Netontwerp Wizard` via `Plugins beheren en
installeren` wanneer de plugin nog niet automatisch actief is.

De plugin bevat eigen kopieën van de vier Processing-tools en de volledige
clusteringbibliotheek. De losse scripts hoeven daarom niet apart geïnstalleerd
te zijn.
