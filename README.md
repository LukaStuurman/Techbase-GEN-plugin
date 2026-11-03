# Techbase-GEN-plugin

## Laatste versie: 1.25.1

[Download de QGIS-plugin](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/download/v1.25.1/ls_netontwerp_wizard-1.25.1.zip) · [Release](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/tag/v1.25.1)

Installeer de ZIP via **Plugins → Plugins beheren en installeren → Installeren vanuit ZIP** en herstart QGIS.

- **Clustering aanpassen (4a):** zet meerdere wijzigingen klaar, controleer capaciteit en routes en pas de hele wachtrij gezamenlijk toe. De gebieden worden één keer opgebouwd; het kabelnet wordt binnen de batch hergebruikt.
- **Stationsbeheer:** laat nieuwe stations vervallen of markeer bestaande stations als ‘Te verwijderen’. Verplaats de aansluitingen naar één gekozen station of laat een geldige herverdeling zoeken. Bescherm stations tegen verwijderen en neem beschermde nieuwe stations mee bij een volgende berekening. Bestaande brongegevens blijven behouden; een aparte laag toont te verwijderen stations. Stationskeuzes en uitsluitingsstralen blijven in het project bewaard.
- **Terugzetten:** de laatste toepassing kan inclusief verwijderde stations, gebieden, routes en stationskeuzes ongedaan gemaakt worden, ook na opnieuw openen. De vier resultaatlagen worden gezamenlijk opgeslagen; een schrijffout draait de databasewijzigingen terug.
- **Mooie clustergebieden (6):** voer de knop herhaaldelijk uit en wissel tussen minimale vertices met schuine grenzen en rechte blokken. Elke poging gebruikt de oorspronkelijke gebieden als basis en bewaart het vorige goede resultaat bij een fout.
- **Plangebied tekenen:** teken via ‘Tekenen…’ direct een vlak op de kaart. De plugin slaat de laag op en vult het bestand automatisch in.
- **Stroom aanpassen:** overschrijft de bestaande stroomvelden zonder nieuwe Herstel-kolommen. De gekozen instellingen worden in het project bewaard.
- **Import en layouts:** reparaties voor lagen die op een netwerkschijf niet werden gevonden, de QGIS-omgeving van het projectproces en het dubbele HTML-kader met WebKit-melding in de Scope-layout. De plugin herstelt dat laatste ook bij het openen van bestaande projecten.

Getest met QGIS 4.2.3: volledige batchbewerkingen, automatische herverdeling, bescherming en capaciteit, annuleren, terugdraaien bij schrijffouten, exact herstel na opnieuw openen, herhaald wisselen van gebiedsvorm, klassieke correcties, tekenen van een plangebied en verwijderen van het dubbele Scope-kader. De compatibiliteitscode voor QGIS 3 is behouden; QGIS 3 is niet afzonderlijk uitgevoerd.

De bestaande GitHub Actions-workflow bouwt bij een versiewijziging een release-ZIP met uitsluitend de map `ls_netontwerp_wizard/`, zonder Python-cachebestanden.

## Eerdere versie: handmatig herverdelen en eigen clusters maken (1.24.0)

Gebruik **4a. Aansluitingen herverdelen** om een bestaande clustering aan te passen, of **4b. Eigen cluster met station maken** om aansluitingen af te splitsen naar een nieuw station. Beide openen dezelfde begeleide editor:

1. Selecteer aansluitingen op de kaart, teken een selectie of kies een heel bestaand cluster.
2. Kies verplaatsen, een nieuw cluster maken of hele clusters samenvoegen. Zoek het doelstation op naam of kies het op de kaart. Nieuwe stations beginnen op 630 kVA; de locatie kan automatisch op een kabel worden voorgesteld of zelf op de kaart worden gekozen.
3. Controleer het aantal aansluitingen, de toegevoegde ontwerpstroom en de resterende stationscapaciteit. De uitvoerknop blijft onderaan zichtbaar tijdens het scrollen.

Samenvoegen neemt alle aansluitingen van de gekozen bronclusters mee en verwijdert hun stations na een geslaagde correctie. De vier bestaande veiligheidscontroles staan standaard aan en zijn bereikbaar onder **Geavanceerde instellingen en veiligheidscontroles**. De bestaande rekenengine werkt routes, statistieken, clustergebieden en layouts bij en maakt herstelkopieën. Tijdens de berekening zijn voortgang en annulering beschikbaar; annuleren wordt uitgeschakeld zodra het opslaan begint. Na een geslaagde wijziging worden de kaartselecties gewist. **Vorige selectie terughalen** haalt de laatste gebruikte aansluitingen terug; deze knop draait geen wijziging terug.

Gebruik **3b. Handmatige clustering maken** om vóór de berekening een eigen H-xx-indeling vast te leggen. Maak clusters, voeg aansluitingen toe aan een bestaand handmatig cluster of wis hun handmatige toewijzing. Als alleen het plangebied wordt berekend, telt de voortgang uitsluitend aansluitingen binnen dat gebied. Buiten het plangebied geselecteerde aansluitingen worden overgeslagen. Zodra alle relevante aansluitingen zijn ingedeeld, wordt **Handmatige clustering uitvoeren** beschikbaar. De editor heropent de bronlagen ook wanneer een resultaatproject is geladen.

Validatie: echte QGIS 4.2.3-widgetacties; echte correcties voor verplaatsen, nieuwe clusters en samenvoegen; voorbereiding, toewijzen en wissen binnen een plangebied; capaciteit, 630 kVA, dubbele namen, annulering en foutafhandeling; bestaande headless-, navigatie- en clustercorrectietests. De Qt-compatibiliteitscode voor QGIS 3 is behouden; deze versie is lokaal niet afzonderlijk uitgevoerd.
