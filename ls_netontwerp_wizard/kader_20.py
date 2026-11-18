"""Exact rate tables from Eea-0205.K 2.0 (user supplied workbook).

Workbook SHA-256: 229d6343c333c98023a609e5d16fc0d98c2c1498c7c6005732e3223885efa195.
Sources: Ontwerpstroom_trafo B5:D42, Ontwerpstroom_kabel B5:D42,
Ontwerpstroom_stijgleiding B5:C17 and Versie beheer B4.

IMPORTANT: Type 1-4 describes *heating system*, not merely building age.
When no Kader20Type column is available the familiar 2022 build-year split
is only a planning assumption. This is reported as an inferred profile.
By explicit user choice, missing three-phase ratings above 80 A can use
the caller's active 3.x ampere conversion, marked as a 3.2 supplement.
Known one-phase street furniture uses the lowest street profile; 3x35 A
uses the 3x40-50 A street profile by explicit user choice.
An explicit one-phase source field is sufficient for that lowest profile
when the service rating is missing; no amperage or future rating is inferred.
By explicit user choice, street furniture with a missing/unknown rating or
only a phase count also uses the lowest 3x25 A profile, labelled as an
assumption. Invalid or unsupported stated ratings do not use this fallback.
Other undefined values and Type 5 heating surcharges need separate input.
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


def _street_phase_count(value, allow_bare=False):
    text = str(value).strip().casefold() if value is not None else ""
    match = re.fullmatch(r"([123])\s*(?:[-–]\s*)?(?:f|fase(?:n)?)", text)
    if match:
        return int(match.group(1))
    if allow_bare and re.fullmatch(r"[123](?:\.0+)?", text):
        return int(float(text))
    return 0


def is_missing_street_rating(doorlaat):
    """Recognize missing ratings without treating invalid stated ratings as absent."""
    service = str(doorlaat).strip().casefold() if doorlaat is not None else ""
    return service in (
        "", "null", "none", "onbekend", "unknown", "nvt", "n.v.t.", "n/a"
    ) or bool(_street_phase_count(service))


def street_phase_hint(doorlaat, number_of_phases=None, phase=None):
    """Return (phase count, source fields, warning) for a missing street rating.

    Only explicit phase counts are accepted. A phase conductor name such as
    L1, R or T is not an independent declaration of the connection's phase
    count. Partial service text participates in conflict detection; the
    missing-rating profile never changes these source facts into one phase.
    Complete service ratings remain the caller's primary input.
    """
    if not is_missing_street_rating(doorlaat):
        return 0, "", ""
    candidates = [
        (_street_phase_count(doorlaat), "doorlaat"),
        (_street_phase_count(number_of_phases, allow_bare=True), "number_of_phases"),
        (_street_phase_count(phase), "phase"),
    ]
    known = [(count, source) for count, source in candidates if count]
    if not known:
        return 0, "", ""
    sources = " + ".join(source for _count, source in known)
    if len({count for count, _source in known}) > 1:
        return 0, sources, "Tegenstrijdige fasevelden; controleer het aantal fasen en de doorlaatwaarde"
    return known[0][0], sources, ""


def _business_rate(phases, amp, rate_tables=None, level="trafo"):
    if amp is None:
        return None
    value = float(amp)
    if not math.isfinite(value) or value <= 0 or phases not in (1, 2, 3):
        return None
    if rate_tables is not None:
        if phases * value <= 3 * 25:
            value = 25.0
        elif phases != 3:
            return None
        for row in rate_tables["business"]:
            if row["min"] <= value <= row["max"]:
                return row["type"], float(row[level])
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


def _heavy_amp_fallback(phases, amp, amp_fallback):
    """Use the active 3.x conversion only for three-phase supplies above 80 A."""
    if phases != 3 or amp_fallback is None:
        return None
    try:
        nominal = float(amp)
        if not math.isfinite(nominal) or nominal <= 80:
            return None
        value = float(amp_fallback(nominal))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def business_future_basis(phases, amp, explicit_future=None, amp_fallback=None, rate_tables=None):
    """Resolve a business calculation basis and its provenance.

    An explicitly chosen future service always wins, even when its tariff
    is undefined. Otherwise keep the established small-business minimum,
    then use a supported current service, including the requested 3.x
    supplement above 3x80 A. A current-service basis is not a planned future
    connection and must not be saved as one.
    """
    explicit = str(explicit_future).strip() if explicit_future is not None else ""
    if explicit.casefold() not in ("", "null", "none"):
        return explicit, "explicit"
    minimum = default_small_business_future(phases, amp)
    if minimum:
        return minimum, "minimum"
    try:
        row = _business_rate(phases, amp, rate_tables=rate_tables)
    except (TypeError, ValueError):
        row = None
    if phases == 3 and (
        row is not None or _heavy_amp_fallback(phases, amp, amp_fallback) is not None
    ):
        return f"3 x {float(amp):g} A", "current"
    return None, "undefined"


def _current_from_suggested_amps(amps, level="trafo", rate_tables=None):
    """Design current for the exact suggested 2.0 standard 3-phase rating."""
    if rate_tables is not None:
        row = _business_rate(3, amps, rate_tables, level=level)
        return row[1] if row else 0.0
    return {25: 8.7, 50: 44.0, 80: 65.0, 160: 138.0, 250: 210.0}[amps]


def gas_advice(level, gas_category, phases, amps, rate_tables=None, amp_fallback=None):
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
    if rate_tables is not None:
        for row in rate_tables["gas"].get(gas, []):
            if equivalent_amp > row["max"]:
                continue
            advice = float(row[level])
            if advice == -1.0:
                if phases in (1, 2, 3) and amps:
                    business = _business_rate(phases, amps, rate_tables, level=level)
                    if business:
                        return float(business[1])
                    if phases == 3 and amp_fallback is not None:
                        try:
                            fallback = float(amp_fallback(float(amps)))
                            return fallback if math.isfinite(fallback) and fallback > 0 else 0.0
                        except (ValueError, TypeError):
                            pass
                return 0.0
            return advice
        return 0.0
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
        if row:
            return float(row[1])
        # The 2.0 business "future" rows leave 3x100/125 and several
        # other intermediate sizes undefined. In the *gas advice* image,
        # however, G4/G6 explicitly says to retain the CURRENT service
        # through 3x160. Apply the existing GEN nominal-amp conversion
        # to those intermediate CURRENT ratings, not a fictional future
        # rating and never 0 A.
        if phases == 3:
            nominal = float(amps)
            for maximum, current in (
                (40.0, 32.0), (50.0, 44.0), (63.0, 51.0),
                (80.0, 65.0), (100.0, 85.0), (125.0, 106.0),
                (160.0, 138.0),
            ):
                if nominal <= maximum:
                    return current
    return 0.0


def _value_business(phases, amp, level="trafo", rate_tables=None):
    row = _business_rate(phases, amp, rate_tables, level=level)
    if row is None:
        return (0.0, "Type 6/7 - toekomstige aansluitwaarde niet gedefinieerd")
    type_number, value = row
    return (value, f"Type {type_number} - toekomstige aansluitwaarde")


def current(level, category, housing, build_year, phases, amp, *,
            generation=False, explicit_type=None, new_build_year=2022,
            gas_category=None, current_phases=None, current_amp=None,
            amp_fallback=None, street_phase_hint=None, street_missing_rating=False,
            rate_tables=None):
    """Return (A, Kader type description, review warning).

    'level' is 'trafo' or 'kabel'; classification category is the existing
    plugin's 1=woon, 4=appartement, 8=laad, 9=straat, 10=zakelijk.
    The caller supplies its active 3.x ampere converter for the requested
    supplement above 3x80 A. Exact 2.0 rows always have priority.
    Other unsupported connections return 0 with an explicit review reason.
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
        household_name = "appartement" if number in (3, 4) else normalize_housing(housing)
        if rate_tables is None:
            row = HOUSEHOLD[level][number][household_name]
        else:
            entry = rate_tables["household"].get((number, household_name))
            if entry is None:
                return 0.0, f"Type {number} - woningcategorie ontbreekt in eigen tabel", "Vul deze woningcategorie aan in de 2.0-tabel"
            row = entry[level]
        return row[1 if generation else 0], f"Type {number} ({provenance})", ""
    if category == 8:
        if rate_tables is None:
            value = PUBLIC_CHARGING[level].get(float(amp)) if phases == 3 and amp is not None else None
        else:
            entry = rate_tables["charging"].get(float(amp)) if phases == 3 and amp is not None else None
            value = entry[level] if entry is not None else None
        label = "Type 8 - netbewust publiek laden"
        if value is None:
            value = _heavy_amp_fallback(phases, amp, amp_fallback)
            if value is not None:
                label += " (aanvulling Kader 3.2)"
        if value is None:
            return 0.0, "Type 8 - ongedefinieerde laadaansluiting", "Geen ondersteunde Kader 2.0-laadaansluiting of zware 3-faseaanvulling"
        return (0.0 if generation else value), label, ""
    if category == 9:
        value = None
        label = "Type 9 - straatmeubilair"
        lowest = (STREET_FURNITURE[25] if rate_tables is None
                  else next((item[level] for item in rate_tables["street"]
                             if item["min"] <= 25 <= item["max"]), None))
        if not phases and (amp is None or amp == 0) and street_missing_rating:
            label += " (aanname: laagste 3x25A-profiel; doorlaatwaarde ontbreekt)"
            warning = ""
            if street_phase_hint:
                hint_phases, hint_source, hint_warning = street_phase_hint
                if hint_phases:
                    label += f" ({hint_phases}-fase via {hint_source}; amperage onbekend)"
                if hint_warning:
                    label += " (tegenstrijdige fasevelden; controleren)"
                    warning = hint_warning
            if lowest is None:
                return 0.0, label, "Het laagste straatmeubilairprofiel ontbreekt in Kader 2.0"
            return (0.0 if generation else lowest), label, warning
        if not phases and (amp is None or amp == 0) and street_phase_hint:
            hint_phases, hint_source, hint_warning = street_phase_hint
            if hint_warning:
                return 0.0, "Type 9 - tegenstrijdige fasevelden (herstellen)", hint_warning
            if hint_phases == 1:
                value = lowest
                label += f" (1-fase via {hint_source}; amperage onbekend, laagste profiel)"
            elif hint_phases:
                return (
                    0.0,
                    f"Type 9 - amperage ontbreekt ({hint_phases}-fase via {hint_source})",
                    "Aantal fasen is bekend, maar de straatmeubilairregel vereist ook de amperagewaarde",
                )
        if amp is not None:
            nominal = float(amp)
            if phases == 1 and math.isfinite(nominal) and nominal > 0:
                value = lowest
                label += " (1-fase, laagste profiel)"
            elif phases == 3:
                if rate_tables is not None:
                    value = next((item[level] for item in rate_tables["street"]
                                  if item["min"] <= nominal <= item["max"]), None)
                elif nominal == 35 or 40 <= nominal <= 50:
                    value = 22.0
                elif 63 <= nominal <= 80:
                    value = 36.0
                elif nominal == 25:
                    value = 5.8
                if nominal == 35:
                    label += " (3x35 A, profiel 3x40-50 A)"
        if value is None:
            value = _heavy_amp_fallback(phases, amp, amp_fallback)
            if value is not None:
                label += " (aanvulling Kader 3.2)"
        if value is None:
            return 0.0, "Type 9 - ongedefinieerd straatmeubilair", "Kader 2.0 definieert deze straatmeubilairaansluiting niet"
        return (0.0 if generation else value), label, ""
    # Base from FUTURE supply; separate gas recommendation is tied to the
    # CURRENT gas+electricity supplies in two embedded Excel illustrations.
    value, label = _value_business(phases, amp, level, rate_tables)
    if value <= 0:
        supplemented = _heavy_amp_fallback(phases, amp, amp_fallback)
        if supplemented is not None:
            value = supplemented
            label = "Type 7 - toekomstige aansluitwaarde (aanvulling Kader 3.2)"
    if value <= 0:
        return 0.0, label, (
            "Kader 2.0 mist een vaste waarde voor deze toekomstige zakelijke "
            "aansluiting; bepaal de toekomstige waarde en corrigeer handmatig."
        )
    gas_value = gas_advice(
        level, gas_category,
        current_phases if current_phases is not None else phases,
        current_amp if current_amp is not None else amp,
        rate_tables=rate_tables, amp_fallback=amp_fallback,
    )
    if gas_value > value:
        return gas_value, label + " (gasadvies verhoogt ontwerpstroom)", ""
    return value, label, ""


def riser_current(kind, number_of_units, future_connection_amp=None, rate_tables=None):
    """Dedicated Kader 2.0 stijgleiding calculation (not transformer current)."""
    count = float(number_of_units)
    if not math.isfinite(count) or count < 0:
        raise ValueError("Aantal eenheden moet eindig en niet-negatief zijn")
    if kind in (3, 4):
        rates = RISER if rate_tables is None else rate_tables["riser"]
        if kind in rates:
            return count * rates[kind]
    if kind == 6 and future_connection_amp is not None:
        rates = RISER_BUSINESS if rate_tables is None else rate_tables["riser_business"]
        if float(future_connection_amp) in rates:
            return count * rates[float(future_connection_amp)]
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

