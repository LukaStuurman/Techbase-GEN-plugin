"""Independent editable design-current rate profiles per Kader.

Do not mutate the original Kader 2.0 workbook constants. All configurations
are explicit per-project snapshots; a missing profile is the original rate
matrix shipped with this plugin. No QGIS dependency.
"""
from __future__ import annotations

import copy
import math

FRAMEWORKS = ("3.0", "3.2", "2.0")
K20_OPTIONS = {
    "k20_household": (
        "Woningen: Type 1–4", ("Type", "Woningtype", "Trafo verbruik A", "Trafo opwek A", "Kabel verbruik A", "Kabel opwek A"),
        [1, "vrijstaand", 9.5, 9.5, 10.3, 9.8,
         1, "twee-onder-een-kap", 8, 7.3, 8.8, 7.5,
         1, "rijtjeswoning", 7, 7.3, 7.8, 7.5,
         1, "onbekend", 7.6, 7.3, 8.4, 7.5,
         2, "vrijstaand", 3.3, 9.5, 4.1, 9.8,
         2, "twee-onder-een-kap", 3.3, 7.3, 4.1, 7.5,
         2, "rijtjeswoning", 3.3, 7.3, 4.1, 7.5,
         2, "onbekend", 3.3, 7.3, 4.1, 7.5,
         3, "appartement", 2.8, 0, 3.5, 0,
         4, "appartement", 5.5, 0, 6, 0],
    ),
    "k20_business": (
        "Zakelijk: Type 6/7", ("Min 3×A", "Max 3×A", "Type", "Trafo A", "Kabel A"),
        [25, 25, 6, 8.7, 8.7, 35, 40, 6, 32, 32, 50, 50, 6, 44, 44,
         63, 80, 6, 65, 65, 160, 160, 7, 138, 138, 250, 250, 7, 210, 210],
    ),
    "k20_street": (
        "Straatmeubilair: Type 9", ("Min 3×A", "Max 3×A", "Trafo A", "Kabel A"),
        [25, 25, 5.8, 5.8, 35, 50, 22, 22, 63, 80, 36, 36],
    ),
    "k20_charging": (
        "Publiek laden: Type 8", ("3×A", "Trafo A", "Kabel A"),
        [25, 5.8, 6.7],
    ),
    "k20_gas": (
        "Zakelijk gasadvies", ("Gas", "Max huidig 3×A", "Trafo advies A", "Kabel advies A"),
        ["G4/G6/Geen", 34.999, 8.7, 8.7,
         "G4/G6/Geen", 160, -1, -1,
         "G4/G6/Geen", 999999, 210, 210,
         "G10-G25", 34.999, 44, 44,
         "G10-G25", 50, 65, 65,
         "G10-G25", 80, 138, 65,
         "G10-G25", 999999, 210, 210,
         ">G25", 80, 210, 65,
         ">G25", 999999, 210, 210],
    ),
    "k20_riser": (
        "Stijgleidingen: hoogbouw", ("Type", "A per eenheid"),
        [3, 1.7, 4, 4.3],
    ),
    "k20_riser_business": (
        "Stijgleiding: zakelijk Type 6", ("Toekomstige 3×A", "A per eenheid"),
        [25, 8.7, 35, 32, 40, 32, 50, 44, 63, 65, 80, 65],
    ),
}
K20_KEYS = tuple(K20_OPTIONS)


def normalized_framework(value):
    name = str(value or "3.0")
    if name == "3.1":
        return "3.2"  # Existing 3.1 files intentionally have the 3.2 calculation
    return name if name in FRAMEWORKS else "3.0"


def original_k20_tables():
    return {key: copy.deepcopy(row[2]) for key, row in K20_OPTIONS.items()}


def _row_groups(profile, key):
    defaults = K20_OPTIONS[key][2]
    raw = profile.get(key, defaults)
    columns = len(K20_OPTIONS[key][1])
    if not isinstance(raw, (list, tuple)) or not raw or len(raw) % columns:
        raise ValueError(f"{K20_OPTIONS[key][0]}: er is minstens één complete regel nodig ({columns} kolommen)")
    return [list(raw[i:i + columns]) for i in range(0, len(raw), columns)]


def _num(value, key, row, col, *, minus_one=False):
    try:
        number = float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        number = float("nan")
    if not math.isfinite(number) or (number < 0 and not (minus_one and number == -1)):
        raise ValueError(f"{K20_OPTIONS[key][0]}: regel {row}, kolom {col} moet een geldig getal zijn")
    return number


def _integer(value, key, row, col, permitted=None):
    number = _num(value, key, row, col)
    if not number.is_integer() or (permitted is not None and int(number) not in permitted):
        raise ValueError(f"{K20_OPTIONS[key][0]}: regel {row}, kolom {col} is ongeldig")
    return int(number)


def _intervals(rows, key, category=None):
    last = -float("inf")
    for i, item in enumerate(sorted(rows, key=lambda it: (it["min"], it["max"]))):
        if item["min"] > item["max"] or item["min"] <= last:
            raise ValueError(f"{K20_OPTIONS[key][0]}: overlappende of omgekeerde bereikregels")
        last = item["max"]


def parse_k20_rates(profile=None):
    """Validate Kader 2.0 table cells and build the calculation dictionaries.

    -1 in the gas advice means 'volg de huidige elektrische aansluitwaarde'.
    All other currents must be finite and nonnegative. No invalid row is dropped.
    """
    profile = profile or {}
    if not isinstance(profile, dict):
        raise ValueError("Kader 2.0-regels moeten een object met afzonderlijke tabellen zijn")
    out = {}

    household = {}
    key = "k20_household"
    for i, (kind, home, tc, tg, kc, kg) in enumerate(_row_groups(profile, key), 1):
        kind = _integer(kind, key, i, 1, (1, 2, 3, 4))
        home = str(home).strip().casefold()
        allowed = ("appartement",) if kind in (3, 4) else ("vrijstaand", "twee-onder-een-kap", "rijtjeswoning", "onbekend")
        if home not in allowed or (kind, home) in household:
            raise ValueError(f"Woningen: regel {i} heeft een onjuist of dubbel woningtype")
        values = [_num(x, key, i, j) for j, x in enumerate((tc, tg, kc, kg), 3)]
        household[(kind, home)] = {"trafo": (values[0], values[1]), "kabel": (values[2], values[3])}
    out["household"] = household

    business = []
    key = "k20_business"
    for i, (lower, upper, kind, tc, kc) in enumerate(_row_groups(profile, key), 1):
        business.append({
            "min": _num(lower, key, i, 1), "max": _num(upper, key, i, 2),
            "type": _integer(kind, key, i, 3, (6, 7)),
            "trafo": _num(tc, key, i, 4), "kabel": _num(kc, key, i, 5),
        })
    _intervals(business, key)
    out["business"] = sorted(business, key=lambda row: row["min"])

    street = []
    key = "k20_street"
    for i, (lower, upper, tc, kc) in enumerate(_row_groups(profile, key), 1):
        street.append({
            "min": _num(lower, key, i, 1), "max": _num(upper, key, i, 2),
            "trafo": _num(tc, key, i, 3), "kabel": _num(kc, key, i, 4),
        })
    _intervals(street, key)
    out["street"] = sorted(street, key=lambda row: row["min"])

    charge = {}
    key = "k20_charging"
    for i, (amp, tc, kc) in enumerate(_row_groups(profile, key), 1):
        amp = _num(amp, key, i, 1)
        if amp <= 0 or amp in charge:
            raise ValueError(f"Publiek laden: regel {i} heeft een dubbele of ongeldige aansluiting")
        charge[amp] = {"trafo": _num(tc, key, i, 2), "kabel": _num(kc, key, i, 3)}
    out["charging"] = charge

    gas = {"G4/G6/Geen": [], "G10-G25": [], ">G25": []}
    key = "k20_gas"
    for i, (category, maximum, tc, kc) in enumerate(_row_groups(profile, key), 1):
        category = str(category).strip()
        if category not in gas:
            raise ValueError(f"Gasadvies: regel {i} moet G4/G6/Geen, G10-G25 of >G25 bevatten")
        max_el = _num(maximum, key, i, 2)
        if max_el <= 0 or any(row["max"] == max_el for row in gas[category]):
            raise ValueError(f"Gasadvies: regel {i} heeft een ongeldige of dubbele bovengrens")
        gas[category].append({
            "max": max_el,
            "trafo": _num(tc, key, i, 3, minus_one=True),
            "kabel": _num(kc, key, i, 4, minus_one=True),
        })
    for category in gas:
        gas[category].sort(key=lambda row: row["max"])
    out["gas"] = gas

    riser = {}
    key = "k20_riser"
    for i, (kind, current) in enumerate(_row_groups(profile, key), 1):
        kind = _integer(kind, key, i, 1, (3, 4))
        if kind in riser:
            raise ValueError("Stijgleiding: dubbele typewaarde")
        riser[kind] = _num(current, key, i, 2)
    out["riser"] = riser

    riser_business = {}
    key = "k20_riser_business"
    for i, (rating, current) in enumerate(_row_groups(profile, key), 1):
        amp = _num(rating, key, i, 1)
        if amp <= 0 or amp in riser_business:
            raise ValueError("Zakelijke stijgleiding: dubbele of ongeldige aansluiting")
        riser_business[amp] = _num(current, key, i, 2)
    out["riser_business"] = riser_business
    return out


def flatten_k20_values(profile=None):
    profile = profile or {}
    parse_k20_rates(profile)
    return {key: copy.deepcopy(list(profile.get(key, default[2])))
            for key, default in K20_OPTIONS.items()}
