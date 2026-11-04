# Stationsherleiding uit LS-schema — v1.28.0

## Doel en gebruik

De aansluiting bevat de kabelgroep waaraan zij hangt. De plugin kan die groep via de schema-export volgen naar een station, zodat daarvoor geen per-station aansluitingenlijst uit LOVION-netwerkanalyse nodig is.

1. Open **1.4. Voedend station uit LS-schema** in het echte dashboard.
2. Kies de bij elkaar horende XML en Excel met de drie collecties/werkbladen **LS Veld**, **LS Railsectie**, **LS Smeltveiligheid**. XML-objecten en Excel-rijen moeten dezelfde ID-selectie, statussen en bovenliggende relaties hebben. Excel levert de kabelgroep en de nominale zekeringwaarde. De XML levert objectidentiteit en schematische geometrie.
3. Kies de blijvende aansluitingenlaag en de kolommen voor Master Asset ID en kabelgroep. De gewone ontwerpstroomlaag wordt waar mogelijk herkend/heropend. De stationslaag moet `Station` en een SAP-functieplaatsnummer bevatten, zoals `trafo_sap_structure_indicator` uit de GEN-import. De vertaling wordt niet uit het controlebestand geleerd.
4. Kies optioneel een schematische ASCII-DXF voor aanvullende geometriecontrole en een CSV voor onafhankelijke vergelijking. De aangeleverde DXF heeft geen volledige object-ID-koppelingen voor een zelfstandige import; DXF alleen wordt daarom duidelijk afgewezen. De XML/Excel-route werkt zonder DXF.
5. Bereken het voorstel op de achtergrond. Bekijk station, referentiestation, status, reden en voedingspad. Filter op afwijkingen/onbekenden/toepasbare regels en selecteer tabelregels op de kaart. Exporteer het volledige controlerapport.
6. Pas gecontroleerd toe. Met een CSV zijn alleen gelijke regels standaard toepasbaar. Bestaande afwijkende stationsnamen vervangen vergt de aparte aanvinkoptie. CSV-afwijkingen, dubbele ID's en onzekere schema-uitkomsten blijven altijd uitgesloten zolang dat controlebestand is gekozen. Zonder CSV zijn de regels modelmatig herleid en niet extern bevestigd.
7. Gebruik **Laatste toepassing terugdraaien** voor beschermd undo, ook na heropenen. Voer een clustering zo nodig opnieuw uit na het aanpassen van haar bronlaag.

## Verbindingsregels

- De fysieke positie van het smeltobject op de schematische rail bepaalt de elektrische aansluiting. Bij de echte invoer wijken 41 gebruikte veldposities af van de administratieve bovenliggende rail. Die administratieve indeling alleen kan gescheiden voedingen onterecht samenvoegen.
- Volgens de gebruikersregel geldt een geregistreerd actief doorverbindingsmes of doorverbinding als invoer naar de eigen rail. Een positieve numerieke zekeringwaarde kleiner dan 9999 geldt als afgaande verbinding. 9999 is geen normale 9999 A-zekering. Onbekende en tegenstrijdige rollen worden niet geraden.
- Gelijke ingevulde kabelgroepcodes verbinden de velden via de groep; leeg en 0 doen dat nooit. Een subgroupvorm zoals `SMG123-00` wordt exact naar zijn groep `SMG123` genormaliseerd. Er is geen fuzzy match, adresmatch of geografische dichtstbijzijnde-stationkeuze.
- Rails blijven afzonderlijk, tenzij een actief koppelveld met mes twee eenduidige rails van dezelfde schematische installatie verbindt. Bij XML/Excel alleen volgt die brug uit het expliciete koppelveld en precies twee secties. Bij DXF-controle moet een getekende veldligging/interne verbinding het smeltpunt én beide rails raken.
- Een DXF moet de echte lagen voor railsecties en smeltveiligheden bevatten. Ondersteund worden de rechte ASCII-DXF LINE/POLYLINE- en INSERT-geometrieën van deze export. Binaire of gebogen varianten worden niet stilzwijgend benaderd. Posities/geometrie moeten binnen 0,002 m overeenkomen; de GEN-schemacoördinaten worden van millimeter naar meter omgerekend. Dit is een schematische precisiecontrole, geen netwerktopologische snapping van geografische kabels.
- De herleiding volgt de geregistreerde objecten en deze voedingsregel. Zij meet geen actuele stroomrichting/schakelstand en rekent geen elektrisch vermogen. Een station kan meerdere fysieke trafos hebben; expliciete transformatorvelden worden daarom afzonderlijk gerapporteerd. Ontbrekende smeltobjecten bewijzen geen open toestand.

## Onafhankelijke Den Dungen-proef

De productieproef gebruikt de reeds voorbereide GEN-import/ontwerpstroomlaag en de aangeleverde schema-XML, Excel en DXF. Geen nieuwe volledige GEN/BAG-import. De oorspronkelijke bestanden zijn niet gewijzigd. De bron bevat 2.763 aansluitingen. De controle-CSV bevat **1.998 rijen en 1.998 unieke Master Asset ID's**; alle ID's worden exact teruggevonden, zonder adres- of positieherstel en zonder dubbele doel-ID's. De vergelijking gebruikt de kabelgroep uit de aansluitingenlaag, niet die uit de controle-CSV.

| Methode | Gelijk aan controle-CSV | Afwijkend | Niet herleid |
| --- | ---: | ---: | ---: |
| Administratieve rail, met voedingsrichting | 1.891 | 4 | 103 |
| XML/Excel met fysieke schematische smeltpositie | 1.926 | 4 | 68 |
| Hetzelfde, met DXF-controle | 1.926 | 4 | 68 |

Het beste resultaat is **96,4% overeenkomst op alle 1.998 referentiegevallen**. Er zijn 1.930 herleide referentiegevallen, waarvan 1.926 overeenkomen: **99,8% overeenkomst binnen de herleide gevallen**. De overige 68 zijn niet als voorspelling meegeteld in die laatste verhouding. De vier afwijkingen zijn reële verschillen met de controlebron en worden niet verborgen, op afstand omgeleid of met de referentiewaarde overschreven. CSV-loze herleiding heeft daardoor geen aangetoonde 100%-betrouwbaarheid.

Over de volledige bronlaag hebben 2.654 aansluitingen een herleid station, 93 geen herleiding en 16 geen eenduidige vertaling naar een stationsnaam in de gekozen stationslaag. De aanvullende DXF-controle bevestigt dezelfde voorspellingen. In dit bestand levert DXF dus extra controle, geen extra juiste matches ten opzichte van de schematische XML/Excel-route.

Op een **aparte lokale GeoPackage-kopie** zijn daadwerkelijk 1.926 CSV-bevestigde regels toegepast. De vier afwijkingen bleven ongemoeid. Daarna is de laag heropend en undo uitgevoerd: alle oorspronkelijke kolommen, waarden, FID's en geometrieblobs komen exact overeen met de oorspronkelijke kopie. Nieuw toegevoegde herkomstkolommen en eventueel de nieuwe Station-kolom blijven na undo leeg aanwezig. De echte dashboardactie is aangeklikt, de achtergrondberekening voltooid, het afwijkingenfilter toonde de vier regels en schermafbeeldingen zijn gecontroleerd.

## Opslag en bescherming

Alleen een blijvende GeoPackage-bronlaag kan worden toegepast. Een laag in bewerkingsmodus, een alleen-lezenlaag of een gefilterde laag wordt geweigerd waar de betreffende controle nodig is. Een geclusterde resultaatlaag wordt niet rechtstreeks gewijzigd. De laaginhoud, Master Asset ID/FID-koppeling, bronbestandsdigests en stationsgegevens worden voor toepassen opnieuw gecontroleerd. Een veranderd voorstel vereist herberekening.

Schrijven gebeurt in één SQLite-transactie, inclusief nieuwe herkomstkolommen en undo-opslag. Een geïnjecteerde databasefout heeft aantoonbaar geen gedeeltelijke waarden of kolommen achtergelaten. Undo staat in hetzelfde GeoPackage, is per tabel gescheiden en wordt geweigerd als de tabel nadien is gewijzigd. Aansluitgeometrie, ontwerpstromen en clusterresultaten worden niet door deze functie herberekend. De rapportbestanden omvatten alle aansluitingen, ook onbekenden en afwijkingen; Master Asset ID moet bij openen/bewerken in Excel als tekst behouden blijven.

## Geautomatiseerde controles en beperkingen

`test_schema_linking.py` controleert met synthetische gegevens twee rails met verschillende voedingen, een actief K-veld dat werkelijk twee bronnen samenbrengt (moet meervoudig blijven), fysieke railcorrectie, XML/Excel tegenover DXF, subgroupnormalisatie, lange exacte ID's, dubbele doel-/referentie-ID's, geen labellek uit de controle-CSV, een schrijffout met rollback, undo na heropenen, alleen-lezen, gewijzigde laag/bronnen en annuleren. De echte Qt-dashboardactie, asynchrone taak en kaartselectie worden uitgevoerd.

Bestaande tests voor stationpresentatie, uniforme UI, aansluitingsbronnen, handmatige nieuwbouw, clusteringherstel, buitenroutes, clusteruitbreidingen en het pluginmenu worden uitgevoerd. De stationpresentatietest heeft nu vier invoeracties en haar Desktop-shellvervanger implementeert de reeds bestaande pluginmenu-API's. Daarvoor is geen bestaande productfunctionaliteit aangepast.

Getest in QGIS 4.2.3/Qt6 op Windows. Geen volledige handmatige Desktop-kliktest, geen QGIS 3-uitvoering en geen bewijs voor een zelfstandige DXF-only herleiding. De productiegegevens, adressen, Master Asset ID's, CSV en tekeningen worden niet naar GitHub geüpload; de repository bevat alleen code, synthetische tests en deze geaggregeerde verantwoording.
