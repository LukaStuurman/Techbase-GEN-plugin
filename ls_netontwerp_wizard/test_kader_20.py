"""Pure-Python regression checks against Eea-0205.K 2.0.xlsx.

Run without QGIS: python ls_netontwerp_wizard/test_kader_20.py
This does not replace the real QGIS integration test.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from ls_netontwerp_wizard import kader_20 as k


def check(actual, expected):
    assert math.isclose(actual, expected, abs_tol=1e-9), (actual, expected)


def main():
    # Excel rows 5-14: household Type 1 and Type 2, consumption and opwek.
    for level, type1, type2, generation in (
        ("trafo", [9.5, 8.0, 7.0, 7.6], [3.3] * 4, [9.5, 7.3, 7.3, 7.3]),
        ("kabel", [10.3, 8.8, 7.8, 8.4], [4.1] * 4, [9.8, 7.5, 7.5, 7.5]),
    ):
        for housing, expected1, expected2, expected_generation in zip(
            ("vrijstaand", "twee-onder-een-kap", "rijtjeswoning", "onbekend"),
            type1, type2, generation,
        ):
            check(k.current(level, 1, housing, 2024, 3, 25)[0], expected1)
            check(k.current(level, 1, housing, 2020, 3, 25)[0], expected2)
            check(k.current(level, 1, housing, 2024, 3, 25, generation=True)[0], expected_generation)
            check(k.current(level, 1, housing, 2020, 3, 25, generation=True)[0], expected_generation)

    # Excel rows 17 and 21: hoogbouw Type 3 vs 4.
    for level, old, new in (("trafo", 2.8, 5.5), ("kabel", 3.5, 6.0)):
        check(k.current(level, 4, "appartement", 2020, 3, 25)[0], old)
        check(k.current(level, 4, "appartement", 2024, 3, 25)[0], new)
        check(k.current(level, 4, "appartement", 2024, 3, 25, generation=True)[0], 0)
        check(k.current(level, 4, "appartement", 2020, 3, 25, generation=True)[0], 0)

    # Explicit heating types take precedence over the planning-year assumption.
    check(k.current("trafo", 1, "vrijstaand", 2020, 3, 25, explicit_type="Type 1")[0], 9.5)
    check(k.current("trafo", 1, "vrijstaand", 2024, 3, 25, explicit_type="Type 2")[0], 3.3)
    check(k.current("kabel", 4, "appartement", 2020, 3, 25, explicit_type="Type 4")[0], 6.0)
    try:
        k.current("trafo", 4, "appartement", 2020, 3, 25, explicit_type="Type 1")
    except ValueError:
        pass
    else:
        raise AssertionError("Incompatible heating system/category was accepted")

    # Workbook rows 27-35: future connection sizes for both net levels and
    # equal consumption/generation in the small/large business types.
    expected = {25: 8.7, 35: 32, 40: 32, 50: 44, 63: 65, 80: 65, 160: 138, 250: 210}
    for level in ("trafo", "kabel"):
        for amp, current in expected.items():
            for gen in (False, True):
                got, label, warn = k.current(level, 10, "", 0, 3, amp, generation=gen)
                check(got, current)
                assert not warn and ("Type 6" if amp <= 80 else "Type 7") in label
        # The workbook contains no fixed 100/125/200/other future connection
        # value. Never fall back silently to Kader 3.x defaults.
        for amp in (100, 125, 200, 315):
            got, label, warn = k.current(level, 10, "", 0, 3, amp)
            check(got, 0)
            assert warn and "niet gedefinieerd" in label

    # Excel rows 38-42: public 3x25 charging and three street furniture bands.
    check(k.current("trafo", 8, "", 0, 3, 25)[0], 5.8)
    check(k.current("kabel", 8, "", 0, 3, 25)[0], 6.7)
    for amp, rate in ((25, 5.8), (40, 22), (50, 22), (63, 36), (80, 36)):
        for level in ("trafo", "kabel"):
            check(k.current(level, 9, "", 0, 3, amp)[0], rate)
            check(k.current(level, 9, "", 0, 3, amp, generation=True)[0], 0)
    assert k.current("trafo", 9, "", 0, 1, 6)[2]

    # Independently supplied rising-main table; no Type 5 simultaneity factor
    # is guessed from an absent lookup.
    check(k.riser_current(3, 10), 17)
    check(k.riser_current(4, 10), 43)
    check(k.riser_current(6, 2, future_connection_amp=80), 130)
    check(k.type5_surcharge_a(2, 3.45, 0.5), 5)
    for function, args in ((k.riser_current, (6, 1, 125)),
                           (k.type5_surcharge_a, (1, 3.5, -0.5))):
        try:
            function(*args)
        except ValueError:
            pass
        else:
            raise AssertionError("Kader 2.0 undefined value accepted")

    # Source integration contracts: framework choice propagates through UI,
    # workflow, per-feature calculation, and retrospective housing edits.
    source = (ROOT / "algorithms" / "Ontwersptroom TRAFO, KABEL & OPWEK voor XML KADER 2026 V5.py").read_text(encoding="utf-8-sig")
    ast.parse(source)
    for needle in ("FRAMEWORK_VERSION", "KaderVersie", "KaderType", "Kader20Type",
                   "Kader20ToekomstigeAansluitwaarde", "generation=True"):
        assert needle in source, needle
    for filename in ("dialog.py", "workflow.py", "algorithms/woningtype_selectie_herberekenen_tool.py",
                     "zero_current_page.py"):
        file_source = (ROOT / filename).read_text(encoding="utf-8-sig")
        ast.parse(file_source)
    assert '"2.0"' in (ROOT / "dialog.py").read_text(encoding="utf-8-sig")
    assert '"2.0": 2' in (ROOT / "workflow.py").read_text(encoding="utf-8-sig")
    print("KADER_20_WORKBOOK_RATES_AND_WIZARD_WIRING_OK")


if __name__ == "__main__":
    main()
