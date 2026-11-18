# LS Netontwerp Wizard v1.33.3

Deze versie verbetert de automatische ontwerpstroomberekening, herstel van aansluitingen, meldingen in de clustereditor en de Scope- en overzichtslayouts.

## Ontwerpstroom en herstel

- **Kader 2.0 zakelijk:** een expliciete toekomstige aansluitwaarde heeft voorrang. Bij een leeg toekomstveld wordt de ondersteunde huidige aansluiting gebruikt, naast de bestaande kleinzakelijke minimumregel. Een automatisch gebruikte huidige aansluiting wordt niet als toekomstige aansluiting opgeslagen.
- **Straatmeubilair in Kader 2.0:** bekende eenfaseaansluitingen krijgen 5,8 A trafo/kabel en 0 A opwek. Zonder doorlaat of ampèrewaarde geldt hetzelfde laagste 3×25 A-profiel, zichtbaar gemarkeerd als aanname. Bron-doorlaat, fasevelden en toekomstwaarde blijven behouden. Exact 3×35 A gebruikt het profiel 3×40–50 A: **22 A trafo/kabel en 0 A opwek**. Een ingevulde ongeldige of niet ondersteunde doorlaat krijgt niet automatisch het profiel voor ontbrekende invoer.
- **Zware aansluitingen:** voor driefasige waarden boven 80 A zonder vaste Kader 2.0-waarde wordt de bestaande, ingestelde Kader 3.2-omzetting gebruikt. Vaste 2.0-waarden blijven leidend. Voorbeelden met de standaardstaffels: 3×95 A → 85 A en 3×125 A → 106 A; boven 250 A geldt de bestaande factor 0,85. Zwaar straatmeubilair en laadpunten behouden nul opwek. De gebruikte aanvulling is herkenbaar in de profielbeschrijving.
- **Gas per aansluiting en netniveau:** automatisch zakelijk herstel gebruikt standaard de eigen gasbron in Kader 2.0, 3.0 en 3.2, ook bij opgeslagen 3.1-keuzes. Trafo, kabel en beide opwekcomponenten worden afzonderlijk berekend. Gas wijzigen voor een selectie blijft een expliciete keuze; een onbekende bron blijft onbekend en krijgt waar nodig een controlemelding.
- **Keuzes blijven behouden:** de gewone hoofdherberekening bewaart herstelprofielen en handmatig ingevulde stroomwaarden. De herkomst van zakelijke presets voorkomt verwarring tussen toekomstige 2.0-waarden en huidige 3.x-waarden bij een kaderwissel. Hoge aansluitwaarden en decimalen worden volledig gelezen. De bestaande 3.x-coëfficiënten zijn niet gewijzigd.

## Herstelvenster en clustereditor

- **Nulwaarden herstellen** opent met meer tabelruimte. De verdeling tussen lijst en invoer is versleepbaar en wordt onthouden; de invoer blijft bereikbaar bij een kleiner venster.
- Kaartinstructies, samenvatting en voortgang hebben ieder een eigen rij. Lange tekst overlapt niet meer met andere meldingen.
- De herkenbare onbereikbaar-routefout verschijnt één keer, met een korte uitleg en vervolgstap. De technische oorzaak blijft beschikbaar in de tooltip. Andere fouten behouden hun eigen inhoud; de bestaande route- en veiligheidscontroles blijven actief.

## Scope en clusteringsoverzicht

- Scope toont leesbare ontwerpstroomlabels naast de gekleurde aansluitingbolletjes en behoudt bestaande stations uit de oorspronkelijke bron.
- Beide layoutlegenda’s tonen precies één bolsymbool met **Aansluitingen**. De categoriekleuren op de kaart blijven behouden.
- Bestaande Scope-layouts krijgen herstel van ontbrekende labels, legenda-items en stations waar de oorspronkelijke bron beschikbaar is. Vastgelegde Scope-gegevens blijven onafhankelijk van latere ontwerpwijzigingen. Relatieve bronpaden, verschillende coördinatenstelsels en een na herstel opgeslagen eigen kaartuitsnede worden gerespecteerd.

## Uitgevoerde controles

- **21 gerichte regressietests** en Python-syntaxcontrole geslaagd. De tests gebruiken de productieberekeningen met vervangende QGIS-dataobjecten en toetsen onder meer gasbehoud, presets, kaderwissels en herhaald herberekenen.
- De aangeleverde selectie van **103 eerdere nulwaarden** is tweemaal doorgerekend: **103 positief op trafo én kabel, geen resterende nulwaarden**. De bronwaarden bleven behouden en in deze proef werd geen toekomstveld automatisch gevuld. Dit resultaat betreft deze selectie.
- Layouts zijn met **native QGIS 3.40.6** en echte GeoPackages gerenderd en na QGZ-opslaan/heropenen gecontroleerd. Labels, legenda’s, stations, bronherstel en het behoud van de Scope-momentopname zijn getoetst.
- De clustereditor is met echte Qt-widgets gecontroleerd op verschillende vensterformaten en op fout → opnieuw proberen → gereed. De volledige editor is niet integraal met echte QGIS-project- en providerbewerkingen getest. Deze controles vormen geen volledige praktijkvalidatie van een netwerkontwerp.

## Installatie en historie

Installeer de release-ZIP via **Plugins → Plugins beheren en installeren → Installeren vanuit ZIP** en herstart QGIS volledig. Herbereken de ontwerpstromen om de nieuwe rekenregels op bestaande resultaten toe te passen.

[Wijzigingen en testdetails in PR #30](https://github.com/LukaStuurman/Techbase-GEN-plugin/pull/30) · [Geslaagde regressiecontrole](https://github.com/LukaStuurman/Techbase-GEN-plugin/actions/runs/44278425670) · [Vorige stabiele versie v1.33.2](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/tag/v1.33.2) · [Eerdere releases en tags](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases)
