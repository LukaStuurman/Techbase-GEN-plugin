"""Regression checks for editable Kader 2.0 tables without QGIS."""
from __future__ import annotations
import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ls_netontwerp_wizard import kader_20
from ls_netontwerp_wizard.design_rate_profiles import (
    parse_k20_rates, original_k20_tables, normalized_framework,
)


def near(a, b):
    assert abs(a - b) < 1e-8, (a, b)


def main():
    assert normalized_framework("3.1") == "3.2"
    assert normalized_framework("2.0") == "2.0"
    initial = original_k20_tables()
    rates = parse_k20_rates(initial)
    near(kader_20.current("trafo", 1, "vrijstaand", 2024, 3, 25,
                          rate_tables=rates)[0], 9.5)
    near(kader_20.current("kabel", 1, "vrijstaand", 2024, 3, 25,
                          rate_tables=rates)[0], 10.3)
    near(kader_20.current("trafo", 8, "", 0, 3, 25,
                          rate_tables=rates)[0], 5.8)
    near(kader_20.current("kabel", 8, "", 0, 3, 25,
                          rate_tables=rates)[0], 6.7)
    near(kader_20.current("trafo", 9, "", 0, 3, 35,
                          rate_tables=rates)[0], 22)
    near(kader_20.current("trafo", 9, "", 0, 0, None,
                          rate_tables=rates, street_missing_rating=True)[0], 5.8)
    for level, expected in (("trafo", 138), ("kabel", 65)):
        near(kader_20.current(level, 10, "", 0, 3, 63,
                              current_phases=3, current_amp=63,
                              gas_category="G10-G25", rate_tables=rates)[0], expected)
    for level, expected in (("trafo", 210), ("kabel", 65)):
        near(kader_20.current(level, 10, "", 0, 3, 63,
                              current_phases=3, current_amp=63,
                              gas_category=">G25", rate_tables=rates)[0], expected)

    custom = copy.deepcopy(initial)
    custom["k20_household"][2] = 12.5
    custom["k20_business"][18] = 71
    custom["k20_business"][19] = 70
    custom["k20_street"][2] = 7.7
    custom["k20_street"][3] = 7.8
    custom["k20_charging"][1] = 6.9
    custom["k20_charging"][2] = 7.1
    custom["k20_gas"][5 * 4 + 2] = 144
    custom["k20_riser"][1] = 2.2
    custom["k20_amp_supplement"][5 * 4 + 2] = 91
    overrides = parse_k20_rates(custom)
    near(kader_20.current("trafo", 1, "vrijstaand", 2024, 3, 25,
                          rate_tables=overrides)[0], 12.5)
    near(kader_20.current("trafo", 10, "", 0, 3, 63,
                          gas_category="G4", rate_tables=overrides)[0], 71)
    near(kader_20.current("kabel", 10, "", 0, 3, 63,
                          gas_category="G4", rate_tables=overrides)[0], 70)
    near(kader_20.current("trafo", 10, "", 0, 3, 63,
                          gas_category="G10-G25", rate_tables=overrides)[0], 144)
    near(kader_20.current("kabel", 9, "", 0, 1, 10,
                          rate_tables=overrides)[0], 7.8)
    near(kader_20.current("trafo", 9, "", 0, 0, None,
                          rate_tables=overrides, street_missing_rating=True)[0], 7.7)
    near(kader_20.current("trafo", 8, "", 0, 3, 25,
                          rate_tables=overrides)[0], 6.9)
    near(kader_20.riser_current(3, 2, rate_tables=overrides), 4.4)
    # Unmodified workbook constants must stay exact.
    near(kader_20.current("trafo", 1, "vrijstaand", 2024, 3, 25)[0], 9.5)
    near(kader_20.current("trafo", 9, "", 0, 3, 25)[0], 5.8)
    near(parse_k20_rates(initial)["household"][(1, "vrijstaand")]["trafo"][0], 9.5)
    for key, position, broken in (
        ("k20_business", 1, -1),
        ("k20_gas", 0, "wrong category"),
        ("k20_household", 2, "broken"),
        ("k20_amp_supplement", 0, 1000),
    ):
        invalid = copy.deepcopy(initial)
        invalid[key][position] = broken
        try:
            parse_k20_rates(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid {key} accepted")
    print("EDITABLE_KADER_RATES_OK (original 2.0, own trafo/kabel/gas/opwek, reset and validation)")


if __name__ == "__main__":
    main()
