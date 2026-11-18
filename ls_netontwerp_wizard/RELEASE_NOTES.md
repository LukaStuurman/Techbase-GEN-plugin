# LS Netontwerp Wizard v1.33.4

Deze versie herstelt de plaatsing van ontwerpstroomlabels in Scope en de weergave van geavanceerde clusterbewerkingen met voortgang in het hoofdvenster.

## Ontwerpstroom in de aansluitbol

- Scope gebruikt dezelfde gecentreerde labelpositie en dezelfde verhouding tussen tekst en bol als het clusteringoverzicht. De ontwerpstroom staat in het bolsymbool.
- Bestaande Scope-layouts met de automatisch gemaakte standaardlabels uit 1.33.3 worden eenmalig bijgewerkt. Na opslaan en heropenen blijft de nieuwe plaatsing behouden, zonder opnieuw te verkleinen.
- Herkenbare aangepaste labelinstellingen, zoals een eigen tekstgrootte of extra stijlexpressies, blijven behouden. Ook aanpassingen die na de eenmalige correctie zijn gemaakt, blijven staan.
- De bestaande stations, aansluitwaarden, categoriekleuren en vastgelegde kaartuitsnede blijven behouden. Beide overzichtslegenda’s houden één bolsymbool met **Aansluitingen**.
- De tekstbuffer wordt stabiel uit de QGIS-tekstopmaak gelezen. Een beschadigde automatisch opgeslagen bufferexpressie van de oude standaard Scope-labels wordt bij de correctie hersteld.

## Geavanceerde clusterbewerkingen en voortgang

- Het scrollgebied berekent zijn hoogte opnieuw bij het uit- en inklappen van **Geavanceerde clusterbewerkingen**. De onderste optie en alle clusterknoppen blijven binnen de kaart en bereikbaar.
- De voortgang krijgt een eigen rij onder het scrollbare dashboard. Uitklappen, scrollen of een kleiner venster laat de balk daardoor niet meer over de clusterknoppen schuiven.
- Het venster gebruikt de bestaande Qt-layoutitems opnieuw, zodat de inhoud en het scrollbereik dezelfde actuele hoogte gebruiken.

## Controles

- De uitgebreide dashboardregressie is geslaagd voor **18 schermtoestanden**. Een onafhankelijke controle slaagde voor **24 van 24 situaties**, met verschillende venster- en tekstgroottes en verborgen, lopende of afgeronde voortgang. Alle knoppen en de checkbox bleven bereikbaar, zonder overlap met de voortgang.
- De bestaande uniforme UI-controle is geslaagd voor tien pagina’s, geavanceerde tabbladen, navigatie en beide editorstanden.
- Nieuwe Scope en een werkelijk opgeslagen 1.33.3-project zijn met **QGIS 3.40.6** gerenderd, opgeslagen en heropend. Alle vier stroomlabels uit de proef lagen exact op het middelpunt van hun bol.
- Tekstgrootte, symboolgrootte en tekstbuffer komen overeen met het clusteringoverzicht. De drie bestaande proefstations, hun labels en beide legenda’s bleven zichtbaar.
- Herhaald herstel veranderde de layout niet opnieuw. Bronwaarden, geometrie, categoriekleuren en de opgeslagen kaartuitsnede bleven gelijk.

## Installatie

Download de release-ZIP en installeer die via **Plugins → Plugins beheren en installeren → Installeren vanuit ZIP**. Herstart QGIS volledig en open daarna je project en de LS Netontwerp Wizard. Bestaande standaard Scope-labels worden dan automatisch bijgewerkt.

[Vorige versie v1.33.3 en de eerdere ontwerpstroomverbeteringen](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/tag/v1.33.3) · [Alle releases](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases)
