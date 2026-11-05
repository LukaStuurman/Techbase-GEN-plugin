"""Exact rate tables from Eea-0205.K 2.0 (user supplied workbook).

Workbook SHA-256: 229d6343c333c98023a609e5d16fc0d98c2c1498c7c6005732e3223885efa195.
Sources: Ontwerpstroom_trafo B5:D42, Ontwerpstroom_kabel B5:D42,
Ontwerpstroom_stijgleiding B5:C17 and Versie beheer B4.

IMPORTANT: Type 1-4 describes *heating system*, not merely building age.
When no Kader20Type column is available the familiar 2022 build-year split
is only a planning assumption. This is reported as an inferred profile.
Undefined 'overig' connection values and Type 5 heating surcharges must be
provided separately; no 3.0/3.1 tariff is silently substituted.
"""

from __future__ import annotations

import math
import re

VERSION = "2.0"
SOURCE = "Eea-0205.K 2.0.xlsx"

# Tables use Excel consumption (C) and generation (D) independently.
# Null D cells are explicitly unprovided and therefore 0 A generation.
HOUSEHOLD = {
    "trafo": {
        1: {
            "vrijstaand": (9.5, 9.5),
            "twee-onder-een-kap": (8.0, 7.3),
            "rijtjeswoning": (7.0, 7.3),
            "onbekend": (7.6, 7.3),
        },
        2: {
            "vrijstaand": (3.3, 9.5),
            "twee-onder-een-kap": (3.3, 7.3),
            "rijtjeswoning": (3.3, 7.3),
            "onbekend": (3.3, 7.3),
        },
        3: {"appartement": (2.8, 0.0)},
        4: {"appartement": (5.5, 0.0)},
    },
    "kabel": {
        1: {
            "vrijstaand": (10.3, 9.8),
            "twee-onder-een-kap": (8.8, 7.5),
            "rijtjeswoning": (7.8, 7.5),
            "onbekend": (8.4, 7.5),
        },
        2: {
            "vrijstaand": (4.1, 9.8),
            "twee-onder-een-kap": (4.1, 7.5),
            "rijtjeswoning": (4.1, 7.5),
            "onbekend": (4.1, 7.5),
        },
        3: {"appartement": (3.5, 0.0)},
        4: {"appartement": (6.0, 0.0)},
    },
}
# Type 6: future connection value; Type 7: own LV direction >3x80A.
BUSINESS_FUTURE = {
    25: (6, 8.7),
    35: (6, 32.0),
    40: (6, 32.0),
    50: (6, 44.0),
    63: (6, 65.0),
    80: (6, 65.0),
    160: (7, 138.0),
    250: (7, 210.0),
}
PUBLIC_CHARGING = {"trafo": {25: 5.8}, "kabel": {25: 6.7}}
STREET_FURNITURE = {25: 5.8, 40: 22.0, 50: 22.0, 63: 36.0, 80: 36.0}
RISER = {3: 1.7, 4: 4.3}
RISER_BUSINESS = {25: 8.7, 35: 32.0, 40: 32.0, 50: 44.0, 63: 65.0, 80: 65.0}


def normalize_housing(value: str) -> str:
    text = str(value or "").strip().casefold()
    if any(token in text for token in ("appartement", "flat", "galerij", "maisonnette", "hoogbouw", "portiek")):
        return "appartement"
    if "vrijstaand" in text or "villa" in text:
        return "vrijstaand"
    if "twee-onder-een" in text or "2-onder-1" in text or "2 onder 1" in text:
        return "twee-onder-een-kap"
    if any(token in text for token in ("rijtjes", "tussen", "hoekwoning", "geschakeld", "woonboot", "chalet")):
        return "rijtjeswoning"
    return "onbekend"


def explicit_household_type(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"(?:type\s*)?([1-4])(?:\s*[:.].*)?", text, flags=re.I)
    if match is None:
        raise ValueError(f"Kader20Type moet Type 1, 2, 3 of 4 zijn: {value!r}")
    return int(match.group(1))


def household_profile(housing, build_year, new_build_year=2022, explicit_type=None):
    """Return (type number, provenance) without equating gas category to heating."""
    name = normalize_housing(housing)
    explicit = explicit_household_type(explicit_type)
    if explicit is not None:
        if (name == "appartement") != (explicit in (3, 4)):
            raise ValueError(
                f"Kader20Type {explicit} past niet bij woningcategorie {name}"
            )
        return explicit, "expliciet Kader20Type"
    try:
        new_build = int(float(build_year)) >= int(new_build_year)
    except (TypeError, ValueError):
        new_build = False
    if name == "appartement":
        return (4 if new_build else 3), "aanname op basis van bouwjaar"
    return (1 if new_build else 2), "aanname op basis van bouwjaar"


def classify_category(category, phases, amps):
    """All Kaders: a household is domestic up to and including 3x40 A.

    Above 40 A per phase, it uses business rating rules. A missing GEN
    doorlaat (e.g. residential BAG) does not trigger reclassification.
    """
    try:
        nominal = float(amps)
    except (ValueError, TypeError):
        return category
    if category in (1, 4) and phases and (int(phases) > 3 or nominal > 40):
        return 10
    return category


def _business_rate(phases, amp):
    if amp is None:
        return None
    value = float(amp)
    if not math.isfinite(value) or value <= 0 or phases not in (1, 2, 3):
        return None
    # The first 2.0 row is 3x25 A. A smaller supply (e.g. 1x25 A,
    # 2x25 A or 3x10 A) cannot yield an invented smaller business current.
    if phases * value <= 3 * 25:
        return 6, 8.7
    if phases != 3:
        return None
    if 35 <= value <= 40:
        return 6, 32.0
    if 63 <= value <= 80:
        return 6, 65.0
    return BUSINESS_FUTURE.get(int(value)) if value.is_integer() else None


def default_small_business_future(phases, amp):
    """Minimum 3x25 A for unknown or smaller-than-3x25 business supplies.

    Never silently downgrade an already larger 3-phase business connection.
    """
    if not phases or not amp:
        return "3 x 25 A"
    return "3 x 25 A" if (
        phases in (1, 2, 3) and float(amp) > 0
        and phases * float(amp) <= 75.0
    ) else None


def _current_from_suggested_amps(amps):
    """Design current for the exact suggested 2.0 standard 3-phase rating."""
    return {25: 8.7, 50: 44.0, 80: 65.0, 160: 138.0, 250: 210.0}[amps]


def gas_advice(level, gas_category, phases, amps):
    """Source: embedded gas advice illustrations beside the 2.0 trafo sheet.

    The recommendation depends on the CURRENT electricity service and gas
    service, separately for transformer and main LS cable; the business base
    value itself comes from FUTURE electricity service.
    """
    if level not in ("trafo", "kabel"):
        raise ValueError("Ongeldig netniveau voor gasadvies")
    category = str(gas_category or "").upper().replace(" ", "")
    if (">G25" in category or "G>25" in category or ">=G25" in category):
        gas = ">G25"
    elif "G10" in category or "G25" in category and "G4" not in category:
        gas = "G10-G25"
    else:
        gas = "G4/G6/Geen"
    try:
        equivalent_amp = (float(phases or 0) * float(amps or 0)) / 3.0
    except (ValueError, TypeError):
        equivalent_amp = 0.0
    if not math.isfinite(equivalent_amp) or equivalent_amp < 0:
        equivalent_amp = 0.0
    if gas == ">G25":
        recommended = 250 if level == "trafo" or equivalent_amp > 80 else 80
        return _current_from_suggested_amps(recommended)
    if gas == "G10-G25":
        if equivalent_amp < 35:
            recommended = 50
        elif equivalent_amp <= 50:
            recommended = 80
        elif equivalent_amp <= 80:
            recommended = 160 if level == "trafo" else 80
        else:
            recommended = 250
        return _current_from_suggested_amps(recommended)
    # G4/G6/no gas: under 3x35 A use 3x25 A, from 3x35 to 3x160
    # the diagram says 'use current electricity service' and over 3x160
    # use 3x250 A. The exact rating can be unknown (3x100/3x125):
    # in that case leave the *future* base intact, not invent a tariff.
    if equivalent_amp < 35:
        return 8.7
    if equivalent_amp > 160:
        return 210.0
    if phases in (1, 2, 3) and amps:
        row = _business_rate(phases, amps)
        return float(row[1]) if row else 0.0
    return 0.0


def _value_business(phases, amp):
    row = _business_rate(phases, amp)
    if row is None:
        return (0.0, "Type 6/7 - toekomstige aansluitwaarde niet gedefinieerd")
    type_number, value = row
    return (value, f"Type {type_number} - toekomstige aansluitwaarde")


def current(level, category, housing, build_year, phases, amp, *,
            generation=False, explicit_type=None, new_build_year=2022,
            gas_category=None, current_phases=None, current_amp=None):
    """Return (A, Kader type description, review warning).

    'level' is 'trafo' or 'kabel'; classification category is the existing
    plugin's 1=woon, 4=appartement, 8=laad, 9=straat, 10=zakelijk.
    Unsupported future connections return 0 with an explicit review reason.
    """
    if level not in HOUSEHOLD:
        raise ValueError(f"Onbekend netvlak: {level}")
    category = classify_category(
        category, current_phases if current_phases is not None else phases,
        current_amp if current_amp is not None else amp,
    )
    # GEN uses 'Huishoudelijk' for flats as well as detached houses.
    # The housing type, not just the broad use category, determines Type 3/4.
    if category == 1 and normalize_housing(housing) == "appartement":
        category = 4
    if category in (1, 4):
        number, provenance = household_profile(
            housing if category == 1 else "appartement",
            build_year, new_build_year, explicit_type,
        )
        if category == 1 and number in (3, 4):
            raise ValueError("Type 3/4 vereist een hoogbouw/appartementcategorie")
        if category == 4 and number in (1, 2):
            raise ValueError("Type 1/2 vereist een laagbouw/woningcategorie")
        row = HOUSEHOLD[level][number][
            "appartement" if number in (3, 4) else normalize_housing(housing)
        ]
        return row[1 if generation else 0], f"Type {number} ({provenance})", ""
    if category == 8:
        value = PUBLIC_CHARGING[level].get(float(amp)) if phases == 3 and amp is not None else None
        if value is None:
            return 0.0, "Type 8 - ongedefinieerde laadaansluiting", "Kader 2.0 definieert netbewust publiek laden alleen voor 3x25 A"
        return (0.0 if generation else value), "Type 8 - netbewust publiek laden", ""
    if category == 9:
        value = None
        if phases == 3 and amp is not None:
            nominal = float(amp)
            if 40 <= nominal <= 50:
                value = 22.0
            elif 63 <= nominal <= 80:
                value = 36.0
            elif nominal == 25:
                value = 5.8
        if value is None:
            return 0.0, "Type 9 - ongedefinieerd straatmeubilair", "Kader 2.0 definieert deze straatmeubilairaansluiting niet"
        return (0.0 if generation else value), "Type 9 - straatmeubilair", ""
    # Base from FUTURE supply; separate gas recommendation is tied to the
    # CURRENT gas+electricity supplies in two embedded Excel illustrations.
    value, label = _value_business(phases, amp)
    if value <= 0:
        return 0.0, label, (
            "Kader 2.0 mist een vaste waarde voor deze toekomstige zakelijke "
            "aansluiting; bepaal de toekomstige waarde en corrigeer handmatig."
        )
    gas_value = gas_advice(
        level, gas_category,
        current_phases if current_phases is not None else phases,
        current_amp if current_amp is not None else amp,
    )
    if gas_value > value:
        return gas_value, label + " (gasadvies verhoogt ontwerpstroom)", ""
    return value, label, ""


def riser_current(kind, number_of_units, future_connection_amp=None):
    """Dedicated Kader 2.0 stijgleiding calculation (not transformer current)."""
    count = float(number_of_units)
    if not math.isfinite(count) or count < 0:
        raise ValueError("Aantal eenheden moet eindig en niet-negatief zijn")
    if kind in (3, 4):
        return count * RISER[kind]
    if kind == 6 and future_connection_amp is not None:
        business = _business_rate(3, future_connection_amp)
        if business is not None and business[0] == 6:
            return count * business[1]
    raise ValueError("Kader 2.0 geeft geen stijgleidingwaarde voor dit type/aansluitwaarde")


def type5_surcharge_a(count, electrical_power_kw, coincidence_factor):
    """Type 5 = number × power × supplied coincidence / (3×0.23 kV).

    Kader 2.0 does NOT supply the coincidence-factor lookup in this workbook;
    callers must explicitly supply it. No surcharge is assumed by default.
    """
    values = tuple(float(x) for x in (count, electrical_power_kw, coincidence_factor))
    if any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("Type 5 invoer moet eindig en niet-negatief zijn")
    return values[0] * values[1] * values[2] / 0.69
