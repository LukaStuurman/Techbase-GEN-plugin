# Stationsherleiding via kabelgroepen

Uitgevoerd v1.30.0: zelfstandige DXF-herleiding met geografische stationsankers, kabeltekstankers en volledige volgordes langs verwijslijnen; daarnaast fysieke veldnummercontrole voor administratief verkeerd gekoppelde smeltobjecten. Zie [planuitkomst, gebruik en tests](DXF_SCHEMA_VALIDATION.md).

Uitbreiding v1.29.0: OV-kabelcoderegistratie en wederzijdse object-ID-relaties voor de aansluitkabel zijn uitgevoerd en onafhankelijk zonder CSV gevalideerd. Zie [gebruik, resultaten en beperkingen](LS_OV_LINK_VALIDATION.md). De onderstaande stappen beschrijven de oorspronkelijke LS-route.

1. Lees veld/rail/smelt uit XML en Excel met tekst-ID's. Gebruik de schematische positie van het smeltobject, niet uitsluitend de administratieve bovenliggende rail. Behandel messen als invoer en numerieke zekeringen als afgang volgens de gebruikersregel. K koppelt alleen de twee bedoelde rails. DXF kan de posities en brug controleren; zonder XML ontbreken in deze export de object-ID's voor een betrouwbare zelfstandige DXF-import.
2. Herleid kabelgroepen naar MS-stations en vertaal via de bestaande stationslaag naar de stationsnaam. Gebruik geen afstands- of referentie-CSV-truc om onbekende voedingen te raden.
3. Koppel aansluitingen via hun kabelgroep. Vergelijk uitsluitend op Master Asset ID met de controle-CSV. Rapporteer alle vergelijkingsgevallen, ook ontbrekende, dubbele of tegenstrijdige ID's. De controle-CSV is geen voorspeller.
4. Voeg een zichtbare dashboardactie en een geïntegreerde pagina met bronkeuze, laag-/kolomkeuze, achtergrondanalyse, voorstel, kaartselectie, rapportexport, toepassen en beschermd blijvend undo toe. Schrijf alleen goedgekeurde enkelvoudige koppelingen in de bronlaag. Referentieafwijkingen zijn standaard uitgesloten. Clusterresultaatlagen worden niet rechtstreeks gewijzigd.
5. Test gewone en schematische railherleiding op de productiegegevens en voer regressies uit voor twee losse rails, K, ontbrekende informatie, Master Asset ID, gewijzigde voorstellen, transactieherstel en undo na heropenen. Controleer echte Qt-dashboardwidgets. Publiceer pas na geslaagde controles; benoem DXF- en referentiebeperkingen.
