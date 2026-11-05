"""Originele LS-kabelgroepen: type-/lengtecontrole en conservatieve afschaling.

Source electrical data: LukaStuurman/AutoCAD-Enexis-kabels-checker,
src/Enexis.KabelChecker.Core/KabelChecker.cs.
No geographic proximity, guessed cable type or invented branch fuse is accepted
as proof of historic connectivity. Terminal route_edge_ids come from confirmed
group-coded physical cable geometry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import hypot, isfinite
import re

CATALOG = {
    "240AL":(.129,.073,343.6020), "150AL":(.206,.079,260.2125),
    "120AL":(.281,.081,232.8426), "95AL":(.320,.082,203.6016),
    "70AL":(.443,.0835,169.1442), "50AL":(.641,.085,137.3436),
    "35AL":(.868,.101,115.0929), "25AL":(1.200,.094,95.9931),
    "16AL":(1.910,.096,74.3337), "185CU":(.107,.068,382.9842),
    "150CU":(.125,.068,339.0741), "95CU":(.194,.069,266.5143),
    "70CU":(.268,.072,222.7014), "50CU":(.387,.085,179.9739),
    "35CU":(.524,.100,152.0127), "25CU":(.727,.094,126.6111),
    "16CU":(1.150,.097,97.8642),
}
FUSES = (63,80,100,125,160,200,250)
DESIGN_AMPS = (57.,72.,90.,113.,144.,180.,225.)
Z_LIMITS = {
    "evenredig":(.250,.250,.204,.163,.128,.092,.062),
    "laatste_helft":(.215,.170,.136,.109,.085,.068,.055)
}


def group_code(code):
    """Full exact group identity: K01 and K01-01 are NEVER merged."""
    value = str(code or "").strip().upper()
    if not value or value.casefold() in {"null", "none", "nan"}:
        raise ValueError("Kabelgroepcode ontbreekt.")
    if any(char in value for char in (",", ";", "|")):
        raise ValueError(
            f"Meerdere kabelgroepen {value!r}; aansluiting moet eenduidig gekoppeld zijn."
        )
    return value


def parent_group(code):
    """K01-00 = hoofdroute; K01-01/-02/-03 = aparte aftakkingen.

    Do not invent a parent "K01" for K01-00: the main electrical route
    is explicitly marked -00 in the 'Kabel Subgroep' source column.
    Legacy un-suffixed codes remain valid standalone main directions.
    """
    code = group_code(code)
    match = re.fullmatch(r"(.+)-(\d{2})", code)
    if match is None or match.group(2) == "00":
        return None
    return match.group(1) + "-00"


def is_descendant_group(code, ancestor):
    """Whether a full subgroup is electrically downstream from ancestor."""
    current = parent_group(code)
    while current is not None:
        if current == ancestor:
            return True
        current = parent_group(current)
    return False


def direct_child_group(code, ancestor):
    """Find the first subgroup between a descendant and its ancestor."""
    current = group_code(code)
    while True:
        parent = parent_group(current)
        if parent is None:
            raise ValueError(f"Subgroep {code} ligt niet onder {ancestor}")
        if parent == ancestor:
            return current
        current = parent


def type_key(description):
    value = str(description or "").upper().replace("²","2")
    material = [m for m in ("AL","CU") if m in value]
    sizes = set(re.findall(r"(?<!\d)(240|185|150|120|95|70|50|35|25|16)(?!\d)",value))
    if len(material)!=1 or len(sizes)!=1:
        raise ValueError(f"Kabeltype niet eenduidig: {description!r}")
    key = next(iter(sizes))+material[0]
    if key not in CATALOG:
        raise ValueError(f"Kabeltype niet ondersteund door Enexis-checker: {description!r}")
    return key


@dataclass(frozen=True)
class Cable:
    id: str
    group: str
    from_node: str
    to_node: str
    type: str
    length_m: float
    def __post_init__(self):
        group_code(self.group)
        type_key(self.type)
        if not self.id or not self.from_node or not self.to_node or self.from_node==self.to_node:
            raise ValueError("Kabeldeel vereist ID en twee verschillende knopen.")
        if not isfinite(self.length_m) or self.length_m<=0:
            raise ValueError("Ongeldige fysieke kabellengte.")


@dataclass(frozen=True)
class OriginalConnection:
    id: str
    station: str
    group: str
    edge_ids: tuple[str,...]
    trafo_verbruik_a: float
    trafo_opwek_a: float
    kabel_verbruik_a: float
    kabel_opwek_a: float
    def __post_init__(self):
        group_code(self.group)
        if not self.id or not self.station or not self.edge_ids:
            raise ValueError("Oorspronkelijke station-/groep-/routekoppeling vereist.")
        if any(not isfinite(v) or v<0 for v in (
            self.trafo_verbruik_a,self.trafo_opwek_a,
            self.kabel_verbruik_a,self.kabel_opwek_a
        )):
            raise ValueError("Negatieve/ongeldige ontwerpstroom.")


def cable_check(cables, installed_fuse_a=None, profile="both"):
    """Same cable properties, grouped R/X and gG options as AutoCAD checker.

    Both evenredig and laatste_helft are checked conservatively, or select
    the established profile explicitly. No installed gG rating is invented.
    """
    segments=list(cables)
    if not segments:
        raise ValueError("Geen oorspronkelijke kabeldelen.")
    if len({s.id for s in segments})!=len(segments):
        raise ValueError("Dubbele kabel-ID in een richtingscontrole.")
    if profile not in ("both","evenredig","laatste_helft"):
        raise ValueError("Ongeldig belastingprofiel.")
    rt=xt=0.
    ampacity=float("inf")
    for e in segments:
        r,x,i=CATALOG[type_key(e.type)]
        rt+=r*e.length_m/1000.
        xt+=x*e.length_m/1000.
        ampacity=min(ampacity,i)
    z=hypot(rt,xt)
    allowable=[]
    for idx,gg in enumerate(FUSES):
        if installed_fuse_a is not None and gg!=installed_fuse_a:
            continue
        if ampacity+1e-10<DESIGN_AMPS[idx]:
            continue
        profiles=Z_LIMITS if profile=="both" else {profile:Z_LIMITS[profile]}
        if all(z<=limits[idx]+1e-12 for limits in profiles.values()):
            allowable.append((gg,DESIGN_AMPS[idx]))
    if installed_fuse_a is not None and installed_fuse_a not in FUSES:
        raise ValueError(f"gG-afzekering {installed_fuse_a} niet ondersteund.")
    best=allowable[-1] if allowable else (None,0.)
    return {
        "impedantie_ohm":z,
        "minimum_zomer_a":ampacity,
        "gg_a":best[0],
        "max_ontwerp_a":best[1],
        "controleprofiel":profile,
        "werkelijk_gg_bekend":installed_fuse_a is not None,
    }


def _maximum(records,prefix):
    return max(
        sum(getattr(c,prefix+"_verbruik_a") for c in records),
        sum(getattr(c,prefix+"_opwek_a") for c in records),
        0.,
    )


def check_paths(connections, cables, station_origins=None, branch_roots=None):
    """No arbitrary paths, cable mixing or off-branch directional shortcuts.

    station_origins maps station->station origin node, branch_roots maps
    (station, subgroup)->actual intersection node with parent. A -01
    direction starts at its parent junction, not at the substation.
    """
    edges={e.id:e for e in cables}
    if len(edges)!=len(cables):
        raise ValueError("Dubbele kabeldeel-ID's.")
    seen={}
    for c in connections:
        group=group_code(c.group)
        start=None
        if parent_group(group):
            if branch_roots is not None:
                start=branch_roots.get((c.station,group))
                if not start: raise ValueError(f"Geen bevestigd aftakpunt voor {c.station}/{group}")
        elif station_origins is not None:
            start=station_origins.get((c.station,group),station_origins.get(c.station))
            if not start: raise ValueError(f"Geen bevestigd stationsbeginpunt voor {c.station}")
        current=start
        history=set([current]) if current else set()
        for id in c.edge_ids:
            if id not in edges:raise ValueError(f"Onbekend kabeldeel {id}")
            e=edges[id]
            if group_code(e.group)!=group:
                raise ValueError(f"Verkeerde kabelgroep bij {c.id}: {e.group} i.p.v. {group}")
            owner=seen.setdefault(id,(c.station,group))
            if owner!=(c.station,group):
                raise ValueError(f"Kabel {id} is bij meerdere stations/groepen ingedeeld.")
            if current is None:
                current=e.from_node
            if current==e.from_node:
                current=e.to_node
            elif current==e.to_node:
                current=e.from_node
            else:
                raise ValueError(f"Ongeldige onderbreking in oorspronkelijke route van {c.id}")
            if current in history:
                raise ValueError(f"Kabellus in {c.id}, unieke route ontbreekt.")
            history.add(current)


def retain_original(stations_a, connections, cables, *, installed_fuses=None,
                    station_origins=None, branch_roots=None,
                    parent_routes=None, profile="both"):
    """Best-effort conservative removal, never adds a foreign connection.

    Returns retained/released IDs and separate per-(station, full group) cable
    checks. Each group's length is its union of distinct original typed
    segments. A suffix '-01' is its OWN length, not the main group's length.
    For branching circuits shared upstream power is calculated per physical
    edge; do not double-count it as extra transformer demand.
    """
    connections=tuple(connections);cables=tuple(cables)
    if not connections:raise ValueError("Geen bestaande aansluitingen.")
    if len(set(c.id for c in connections))!=len(connections):
        raise ValueError("Aansluit-ID's niet uniek.")
    check_paths(connections,cables,station_origins,branch_roots)
    edge_by_id={e.id:e for e in cables}
    active={c.id for c in connections}
    rejected={}
    stations=set(stations_a)
    if any(c.station not in stations for c in connections):
        raise ValueError("Oorspronkelijk station ontbreekt in stationsinventaris.")

    def states():
        # Group -01 starts at its own tap, but all descendant loads also run
        # through the main group's upstream cable (once per connection).
        by_group=defaultdict(list)
        direct=defaultdict(list)
        for c in connections:
            if c.id not in active:continue
            name=group_code(c.group)
            direct[(c.station,name)].append(c)
            while name:
                by_group[(c.station,name)].append(c)
                name=parent_group(name)
        direction={}
        for key,members in by_group.items():
            own=direct.get(key,[])
            paths=[c.edge_ids for c in own]
            # Each child must have a verified physical path on THIS parent
            # group to its tap. Never add the child's length to the parent.
            children=sorted({
                direct_child_group(c.group,key[1])
                for c in members
                if c.group!=key[1] and is_descendant_group(c.group,key[1])
            })
            for child in children:
                link_key=(key[0],child)
                if parent_routes is None or link_key not in parent_routes:
                    raise ValueError(
                        f"Fysieke bovenliggende route tot aftakking {child} "
                        "ontbreekt; de belasting van de parent mag niet worden genegeerd."
                    )
                paths.append(tuple(parent_routes[link_key]))
            if not paths:
                raise ValueError("Richting zonder werkelijk fysiek pad.")
            checked=[]
            used=set()
            for path in paths:
                path=tuple(path)
                if not path:raise ValueError(f"Leeg fysiek pad voor {key}")
                used.update(path)
                physical=[edge_by_id[id] for id in path]
                fuse=None if installed_fuses is None else installed_fuses.get(key)
                checked.append((
                    sum(x.length_m for x in physical),
                    cable_check(physical,installed_fuse_a=fuse,profile=profile)
                ))
            # CableChecker is a feeder-path impedance calculation, NOT a sum
            # of disconnected parallel branches. Use worst individual path,
            # but count every endpoint load on the shared upstream feeder.
            worst_length=max(length for length,_ in checked)
            limiting=min(checked,key=lambda row:row[1]["max_ontwerp_a"])[1]
            load=_maximum(members,"kabel")
            union=[edge_by_id[id] for id in sorted(used)]
            direction[key]={
                **limiting,
                "belasting_a":load,
                "pass":bool(limiting["gg_a"]) and load<=limiting["max_ontwerp_a"]+1e-7,
                "length_m":worst_length,
                "fysiek_uniek_m":sum(x.length_m for x in union),
                "paden":len(paths),
                "segmenten":tuple((x.id,x.type,x.length_m) for x in union),
                "behouden_ids":tuple(sorted(c.id for c in members))
            }
        station={}
        for name,capacity in stations_a.items():
            if not isfinite(capacity) or capacity<=0:
                raise ValueError(f"Station {name} heeft geen betrouwbare trafocapaciteit.")
            members=[c for c in connections if c.station==name and c.id in active]
            v=_maximum(members,"trafo")
            station[name]={"belasting_a":v,"maximum_a":capacity,"pass":v<=capacity+1e-7}
        return station,direction

    # Repeatedly release the most constraining original endpoint, e.g. a far
    # branch or high-demand connection. Every resulting set is a subset of
    # verified original membership. Never assign a cable to a new station here.
    for _ in range(len(connections)+1):
        station,groups=states()
        bad_groups={k for k,x in groups.items() if not x["pass"]}
        bad_stations={k for k,x in station.items() if not x["pass"]}
        if not bad_groups and not bad_stations:
            break
        possibles=[c for c in connections if c.id in active and
                   (c.station in bad_stations or any(
                       station == c.station and (
                           group_code(c.group) == group
                           or is_descendant_group(c.group,group)
                       )
                       for station,group in bad_groups
                   ))]
        if not possibles:
            raise ValueError("Ongeldige richting/station kan niet door afschalen hersteld worden.")
        chosen=max(possibles,key=lambda c:(
            any(station == c.station and (
                group_code(c.group) == group
                or is_descendant_group(c.group,group)
            ) for station,group in bad_groups),
            max(c.kabel_verbruik_a,c.kabel_opwek_a,c.trafo_verbruik_a,c.trafo_opwek_a),
            sum(edge_by_id[x].length_m for x in c.edge_ids),c.id))
        active.remove(chosen.id)
        rejected[chosen.id]=(
            "Kabelrichting of bestaande kabellengte/type onvoldoende" if
            any(station==chosen.station and (
                group_code(chosen.group)==group
                or is_descendant_group(chosen.group,group)
            ) for station,group in bad_groups) else
            "Trafocapaciteit onvoldoende"
        )
    else:
        raise ValueError("Bestaande richtingen niet veilig af te schalen.")
    station,directions=states()
    return {"behouden":tuple(sorted(active)),
            "vrijgegeven":tuple(sorted(rejected)),
            "redenen":rejected,
            "stations":station,"richtingen":directions,
            "waarschuwingen":(
                ["gG-afzekering niet uit inventaris bevestigd; adviezen zijn berekende maxima"]
                if installed_fuses is None else []
            )}
