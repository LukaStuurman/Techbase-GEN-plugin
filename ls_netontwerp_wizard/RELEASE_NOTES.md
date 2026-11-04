# LS Netontwerp Wizard v1.26.0

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
