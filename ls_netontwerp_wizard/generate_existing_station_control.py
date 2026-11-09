"""Maak een controlebestand met expliciet synthetische verdeelkasttestgegevens.

Dit is GEEN echte GEN/Lovion-metingscontrole. Het geeft toetsresultaten van
dezelfde rekenmodules die de optionele clusteringmodus aanroept.
"""
import argparse
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention
from ls_netontwerp_wizard.test_existing_cabinet_feeders import fixture


def write_csv(path, items, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer=csv.DictWriter(handle,fieldnames=columns,delimiter=";")
        writer.writeheader()
        writer.writerows(items)


def build(output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    station,points,stations,cables,cabinets=fixture()
    data=prepare_retention(points,stations,cables,850.,
                           distribution_cabinets=cabinets)
    check=data["retention"]
    if check["stations"][station]["belasting_a"]!=75.:
        raise AssertionError("Unexpected tested transformer load")
    if set(check["behouden"])!={"cab-main","cab-branch","station-main"}:
        raise AssertionError("Original membership was changed")
    station_rows=[
        dict(Station=name,Belasting_A=f'{v["belasting_a"]:.2f}',
             Maximum_A=f'{v["maximum_a"]:.2f}',
             Voldoet="ja" if v["pass"] else "nee")
        for name,v in sorted(check["stations"].items())
    ]
    groups=[]
    parts=[]
    for (name,code),state in sorted(check["richtingen"].items()):
        groups.append(dict(
            Station=name,Kabel_Subgroep=code,
            Verdeelkast=str(data["cabinet_metadata"].get((name,code),"")),
            Bovenliggende_groep=str(data["feeder_parents"].get((name,code),"")),
            Belasting_A=f'{state["belasting_a"]:.2f}',
            Max_ontwerp_A=f'{state["max_ontwerp_a"]:.2f}',
            gG_berekend_A=state["gg_a"] or "",
            gG_geinstalleerd_bekend="ja" if state["werkelijk_gg_bekend"] else "nee",
            Max_pad_m=f'{state["length_m"]:.2f}',
            Fysiek_uniek_m=f'{state["fysiek_uniek_m"]:.2f}',
            Impedantie_Ohm=f'{state["impedantie_ohm"]:.8f}',
            Voldoet="ja" if state["pass"] else "nee",
        ))
        for edge_id,kind,length in state["segmenten"]:
            parts.append(dict(
                Station=name,Kabel_Subgroep=code,Kabeldeel=edge_id,
                Kabeltype=kind,Lengte_m=f"{length:.2f}",
                Achterliggend_A=f'{state["deel_belasting_a"].get(edge_id,0.):.2f}',
            ))
    write_csv(output/"controle_stations.csv",station_rows,list(station_rows[0]))
    write_csv(output/"controle_richtingen.csv",groups,list(groups[0]))
    write_csv(output/"controle_kabeldelen.csv",parts,list(parts[0]))
    write_csv(output/"controle_aansluitingen.csv",data["records"],
              list(data["records"][0]))
    overloaded=points.copy()
    overloaded.loc[1,"Ontwerpstroom"]=60.
    overloaded.loc[1,"Ontwerpstroom kabel"]=60.
    limited=prepare_retention(
        overloaded,stations,cables,850.,
        distribution_cabinets=cabinets,
        installed_fuses={
            (station,"S07-00"):160,(station,"B99-00"):160,
            (station,"B99-01"):63,(station,"S03-00"):160,
        },
    )
    assert limited["retention"]["vrijgegeven"]==("cab-branch",)
    sha=os.getenv("GITHUB_SHA","lokale toets")
    run=os.getenv("GITHUB_RUN_ID")
    report=[
        "# Controlebestand bestaande stations en verdeelkasten",
        "",
        "**Herkomst:** uitsluitend gesimuleerde RD-lijnen, geen originele GEN/Lovion-meetwaarden.",
        f"**Opgesteld:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Git-commit:** {sha}",
        (f"**CI-run:** https://github.com/LukaStuurman/Techbase-GEN-plugin/actions/runs/{run}"
         if run else "**CI-run:** lokaal"),
        "",
        "## Station- en groepsresultaten",
        "",
        f"Station {station}: {check['stations'][station]['belasting_a']:.2f} A "
        f"van {check['stations'][station]['maximum_a']:.2f} A trafocapaciteit; "
        f"{len(check['behouden'])} originele aansluitingen behouden.",
        "",
        "| Station | Kabel Subgroep | Belast (A) | Max. berekend (A) | Lengte uniek (m) | gG voorstel (A) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for record in groups:
        report.append(
            f"| {record['Station']} | {record['Kabel_Subgroep']} | "
            f"{record['Belasting_A']} | {record['Max_ontwerp_A']} | "
            f"{record['Fysiek_uniek_m']} | {record['gG_berekend_A']} |"
        )
    report.extend([
        "",
        "Verdeelkast LS-024709 wordt gevoed door S07-00. De aparte "
        "B99-00-kastuitgang en B99-01-aftakking behouden ieder een eigen "
        "kabeltype, fysieke lengte, gG-controle en ontwerpstroom. "
        "De upstream S07-00 draagt de totale 50 A van beide kastgroepen "
        "één keer; de stationstrafo krijgt daarnaast 25 A uit S03-00.",
        "",
        "## Afzekering en afschalen",
        "",
        "In de afzonderlijke geforceerde zekeringstest heeft B99-01 een "
        "63 A gG met 57 A maximale ontwerpstroom, terwijl de aansluiting "
        "60 A vraagt. Resultaat: uitsluitend cab-branch wordt vrijgegeven. "
        "cab-main en station-main blijven bij hun originele station.",
        "",
        "## Andere uitgevoerde regressies",
        "",
        "- -00 hoofdroute en -01/-02/-03 aftakkingen: eigen kabellengte en achterliggende stroom.",
        "- Een verdeelkast via directe S07-00 en via upstream S07-01: afzonderlijke volledige padcontrole.",
        "- Een verdeelkast tot 15 m van station wordt niet automatisch als directe stationuitgang gezien.",
        "- Een verdeelkastpolygoon met twee verschillende kabeluiteinden wordt alleen gevoed als een echte interne nul-rekenmeterverbinding bestaat.",
        "- Als de interne verdeelkastverbinding ontbreekt, wordt de originele clustertoewijzing afgekeurd.",
        "- Meerdere stationnetten met dezelfde groepscode worden niet samengevoegd.",
        "- Ontbrekende verdeelkast en twee mogelijke voedende richtingen worden afgekeurd.",
        "- Apart verbruik, opwek, hoofdstationcapaciteit, kabelrichting-gG en maximale route.",
        "- Vrijgegeven aansluitingen uitsluitend naar nieuwe stations; bestaande kabelterritoria blijven gereserveerd.",
        "- Alle oude aansluitingen mogen worden vrijgegeven als geen veilige restcapaciteit bestaat.",
        "",
        "## Bestanden en beperkingen",
        "",
        "controle_stations.csv, controle_richtingen.csv, controle_kabeldelen.csv "
        "en controle_aansluitingen.csv zijn afzonderlijk op te vragen.",
        "",
        "**Let op:** station 044.529 en verdeelkast LS-024709 zijn hier alleen "
        "testlabels. De werkelijke zekeringen/gG van het project zijn niet "
        "aangeleverd; de gG in de basiscontrole is een berekend maximum, "
        "geen bevestigde installatie. Dit is geen volledige QGIS-end-to-end-"
        "controle van het echte project of van daadwerkelijke schakelingen. "
        "Bij een onvoldoende of niet-bewezen aansluiting wordt geen "
        "nieuwe fysieke netscheiding of kabelroute verzonnen.",
        "",
    ])
    target=output/"controle_bestaande_stations_verdeelkasten.md"
    target.write_text("\n".join(report),encoding="utf-8")
    print(f"CONTROL_REPORT_READY: {target}")
    print(f"CONTROLE_STATION: {station}: {check['stations'][station]['belasting_a']} A")
    print("CONTROLE_KABELGROEPEN: "+", ".join(
        f'{g["Kabel_Subgroep"]}={g["Belasting_A"]}A' for g in groups
    ))
    print("CONTROLE_VRIJGEGEVEN_BIJ_63A: "+",".join(
        limited["retention"]["vrijgegeven"]
    ))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",default="controle_verdeelkasten")
    args=parser.parse_args()
    build(args.output_dir)
