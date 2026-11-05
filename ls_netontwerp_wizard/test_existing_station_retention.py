"""Pure regression tests; no QGIS required."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ls_netontwerp_wizard.existing_station_retention import (
    Cable, OriginalConnection, cable_check, retain_original,
    parent_group, group_code, type_key, CATALOG,
)


def conn(id, station, group, ids, load):
    return OriginalConnection(id,station,group,tuple(ids),load,0.,load,0.)


def test():
    assert parent_group("K01-01")=="K01"
    assert parent_group("K01-02")=="K01"
    assert parent_group("K01") is None
    assert group_code("k01-01")=="K01-01"
    assert type_key("4*150mm2 Al")=="150AL"
    assert type_key("95Al")=="95AL"

    # Exact electrical-case reference from checker documentation:
    # 209.09m 150Al + 68.59m 95Al -> Z = 0.06868816869589478.
    a=Cable("a","K01","s","n1","4*150mm2 Al",209.09)
    b=Cable("b","K01","n1","n2","4*95mm2 Al",68.59)
    c=cable_check([a,b])
    assert abs(c["impedantie_ohm"]-0.06868816869589478)<1e-12,c
    assert c["gg_a"]==200 and c["max_ontwerp_a"]==180.,c

    # A physical branch '-01' must not have its 160m added to the main
    # direction's separate physical length or impedance.
    trunk=Cable("trunk","K01","s","junction","4*150mm2 Al",65.)
    trunk_end=Cable("trunkend","K01","junction","main_end","4*95mm2 Al",120.)
    branch=Cable("branch","K01-01","junction","branch_end","4*50mm2 Al",160.)
    connections=[
        conn("m","044.529","K01",("trunk","trunkend"),60),
        conn("b","044.529","K01-01",("branch",),40),
    ]
    result=retain_original(
        {"044.529":217.},connections,[trunk,trunk_end,branch],
        station_origins={"044.529":"s"},
        branch_roots={("044.529","K01-01"):"junction"},
        parent_routes={("044.529","K01-01"):("trunk",)},
    )
    assert result["behouden"]==("b","m"),result
    assert result["richtingen"][("044.529","K01")]["length_m"]==185.,result
    assert result["richtingen"][("044.529","K01-01")]["length_m"]==160.,result
    assert result["richtingen"][("044.529","K01")]["belasting_a"]==100.,result
    assert result["richtingen"][("044.529","K01-01")]["belasting_a"]==40.,result
    assert result["richtingen"][("044.529","K01")]["fysiek_uniek_m"]==185.,result
    assert result["stations"]["044.529"]["belasting_a"]==100.

    # Transformer and physical direction constraints both act as ceilings;
    # no retained connection can be attached to a different station.
    more=[conn("main","044.529","K01",("trunk","trunkend"),90),
          conn("side","044.529","K01-01",("branch",),140)]
    result=retain_original(
        {"044.529":217.},more,[trunk,trunk_end,branch],
        station_origins={"044.529":"s"},
        branch_roots={("044.529","K01-01"):"junction"},
        parent_routes={("044.529","K01-01"):("trunk",)},
    )
    assert result["vrijgegeven"],result
    assert set(result["behouden"]).issubset({"main","side"})
    assert all(x["pass"] for x in result["stations"].values())
    assert all(x["pass"] for x in result["richtingen"].values())

    # Duplicate subgroup ownership and missing physical paths fail closed.
    try:
        retain_original(
            {"044.529":217.},
            [conn("x","044.529","K01-01",("trunk",),4)],
            [trunk],station_origins={"044.529":"s"},
            branch_roots={("044.529","K01-01"):"junction"},
        )
    except ValueError as e:
        assert "Verkeerde kabelgroep" in str(e)
    else:
        raise AssertionError("Nonexistent physical branch accepted")
    try:
        group_code("K01, K02")
    except ValueError:
        pass
    else:raise AssertionError("Multi-group connection guessed")
    print("EXISTING_STATION_GROUP_AND_CHECKER_OK")


if __name__=="__main__":
    test()
