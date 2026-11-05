"""Pure-Python check: Kader 2.0 future values versus unchanged old 3.1 rules.

The *label* of the existing profile is now Kader 3.2. Deliberately do not
update its rates to those in an externally supplied 3.2 workbook.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from ls_netontwerp_wizard import kader_20

SOURCE = ROOT / "algorithms" / "Ontwersptroom TRAFO, KABEL & OPWEK voor XML KADER 2026 V5.py"


def load_rates():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    symbols = {
        "clean_text", "parse_doorlaat", "normalize_gas", "get_gas_advies",
        "map_gebruiksdoel", "woonhuis_ontwerp", "amp_to_ontwerp", "parse_bouwjaar",
        "calculate_ontwerpstroom", "calculate_opwek_ontwerpstroom",
    }
    funcs = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in symbols]
    assert len(funcs) == len(symbols)
    scope = {
        "re": re,
        "kader_20": kader_20,
        "is_bag_object": lambda value: str(value).casefold() == "verblijfsobject",
        "has_residential_usage": lambda value: "woon" in str(value).casefold(),
    }
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SOURCE), "exec"), scope)
    constants = {node.targets[0].id: ast.literal_eval(node.value)
                 for node in tree.body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id.startswith("DEF_")}
    return scope, constants


def test():
    scope, constants = load_rates()
    # Snapshots of the ORIGINAL (pre-rename) Kader 3.1 plugin matrices.
    # No amount, gas advice, charging rate or household current may change
    # as a side-effect of renaming the profile to 3.2.
    for name, expected in {
        "DEF_WOONHUIS": ["hoekwoning",5.5,"tussen/geschakeld",5.5,
                          "twee-onder-een-kap",6.3,"vrijstaand",7.5,
                          "appartement",4.5,"onbekend",5.9],
        "DEF_WOONHUIS_2022": ["hoekwoning",5.3,"tussen/geschakeld",5.3,
                               "twee-onder-een-kap",5.9,"vrijstaand",7.0,
                               "appartement",4.2,"onbekend",5.6],
        "DEF_WOONHUIS_KABEL": ["hoekwoning",6.4,"tussen/geschakeld",6.4,
                                "twee-onder-een-kap",7.1,"vrijstaand",8.1,
                                "appartement",5.4,"onbekend",6.8],
        "DEF_WOONHUIS_KABEL_2022": ["hoekwoning",6.3,"tussen/geschakeld",6.3,
                                     "twee-onder-een-kap",6.8,"vrijstaand",7.5,
                                     "appartement",5.1,"onbekend",6.4],
        "DEF_WOONHUIS_OPWEK": ["hoekwoning",5.7,"tussen/geschakeld",5.7,
                                "twee-onder-een-kap",6.8,"vrijstaand",8.9,
                                "appartement",0,"onbekend",5.7],
        "DEF_WOONHUIS_OPWEK_KABEL": ["hoekwoning",5.9,"tussen/geschakeld",5.9,
                                      "twee-onder-een-kap",7,"vrijstaand",9.2,
                                      "appartement",0,"onbekend",5.9],
        "DEF_STRAAT": [0,35,5.8,40,50,22,63,80,36],
        "DEF_LAAD": [0,35,3.7,40,50,22,63,80,36],
        "DEF_LAAD_KABEL": [0,35,4.8,40,50,22,63,80,36],
    }.items():
        assert constants[name] == expected, name
    assert constants["DEF_AMP_GLOBAL"] == [
        0,34,8.7,0, 34,40,32,0, 40,50,44,0, 50,63,51,0,
        63,80,65,0, 80,100,85,0, 100,125,106,0,
        125,160,138,0, 160,200,210,0, 200,250,210,0,
        250,99999,0,0.85,
    ]
    assert constants["DEF_GAS_ADVIES"] == [
        "G10-G25",34,50, "G10-G25",50,80, "G10-G25",80,160,
        "G10-G25",250,250, ">G25",250,250,
    ]
    assert constants["DEF_GAS_ADVIES_KABEL"] == [
        "G10-G25",34,50, "G10-G25",50,80, "G10-G25",80,80,
        "G10-G25",9999,250, ">G25",80,80, ">G25",250,250,
    ]
    dialog = (ROOT / "dialog.py").read_text(encoding="utf-8-sig")
    assert '"Kader 3.2 (bestaande rekenwaarden behouden)", "3.2"' in dialog
    assert 'if values["design_framework"] in ("3.1", "3.2"):' in dialog
    d_tree = ast.parse(dialog)
    old_street = next(
        ast.literal_eval(node.value)
        for node in d_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "FRAMEWORK_31_STREET_MATRIX" for t in node.targets)
    )
    assert old_street == [0,6,4.3,7,10,8.7,11,35,5.8,40,50,22,63,80,36]
    workflow = (ROOT / "workflow.py").read_text(encoding="utf-8-sig")
    assert '"3.1": 1, "3.2": 1' in workflow  # legacy saved preference

    # The 3.1 and 3.2 branches below execute the SAME legacy implementation.
    amp_rows = [
        dict(min=constants["DEF_AMP_GLOBAL"][i],
             max=constants["DEF_AMP_GLOBAL"][i+1],
             fix=constants["DEF_AMP_GLOBAL"][i+2],
             fac=constants["DEF_AMP_GLOBAL"][i+3])
        for i in range(0, len(constants["DEF_AMP_GLOBAL"]), 4)
    ]
    base = dict(
        DEFAULTS={"limit_fase":3,"limit_amp":40,"bouwjaar_grens":2022},
        TYPES={0:dict(fixed=0.,use_amp=True,use_woon=False,use_straat=False),
               10:dict(fixed=0.,use_amp=True,use_woon=False,use_straat=False)},
        AMP_GLOBAL=amp_rows, REGEX_MAP=[],
        GEBRUIKS_MAP=[(["oplaadpunt", "laadpunt"], 8),
                      (["straatmeubilair"], 9)],
        GAS_ADVIES=[], WOONHUIS={}, WOONHUIS_2022={},
    )
    old = dict(base, FRAMEWORK_VERSION="3.1", NET_LEVEL="trafo")
    renamed = dict(base, FRAMEWORK_VERSION="3.2", NET_LEVEL="trafo")
    consumption = scope["calculate_ontwerpstroom"]
    generation = scope["calculate_opwek_ontwerpstroom"]
    for gas in ("G4", "G10", ">G25"):
        for supply in (25, 40, 50, 63, 80, 100, 125, 160, 200, 250):
            args = (f"3 x {supply} A", "bedrijf", "", 2010, gas)
            assert consumption(*args, old, 1, None, True) == consumption(
                *args, renamed, 1, None, True
            ), (gas, supply)
    for supply in (25, 63, 160, 250):
        a = f"3 x {supply} A"
        assert generation(a,"bedrijf","",">G25",[],old,65,True) == generation(
            a,"bedrijf","",">G25",[],renamed,65,True
        )

    # In 2.0 even a matching current 3x160 MUST NOT be read as the FUTURE
    # connection automatically. Kader 3.2 continues its existing behavior.
    config20 = dict(base, FRAMEWORK_VERSION="2.0", NET_LEVEL="trafo")
    assert consumption("3 x 160 A","bedrijf","",2015,">G25",config20,1,None,True) == 0
    assert generation("3 x 160 A","bedrijf","",">G25",[],config20,0,True) == 0
    assert consumption("3 x 25 A","bedrijf","",2015,"G4",config20,1,None,True,
                       True,None,"3 x 160 A") == 138.
    # Strong current gas service can overrule the future 3x160 base at
    # transformer level; the separate current-service advice is 3x250.
    assert consumption("3 x 25 A","bedrijf","",2015,">G25",config20,1,None,True,
                       True,None,"3 x 160 A") == 210.
    assert generation("3 x 25 A","bedrijf","",">G25",[],config20,210,True,
                      2015,None,"3 x 160 A") == 210.
    assert consumption("3 x 25 A","bedrijf","",2015,"G4",config20,1,None,True,
                       True,None,"3 x 100 A") == 0
    config20_kabel = dict(config20, NET_LEVEL="kabel")
    charge_value = consumption("3 x 25 A","oplaadpunt","",2015,"G4",config20_kabel,
                               1,None,True)
    assert charge_value == 6.7, (
        charge_value, scope["map_gebruiksdoel"]("oplaadpunt", "", config20_kabel),
        scope["parse_doorlaat"]("3 x 25 A"),
    )
    assert consumption("3 x 25 A","oplaadpunt","",2015,"G4",config20,
                       1,None,True) == 5.8
    # End-to-end pure preview of QGIS named business presets. The user
    # picks a FUTURE 3x160 rating in the GUI, not a current GEN doorlaat.
    from types import SimpleNamespace
    preset_tree = ast.parse((ROOT / "current_presets.py").read_text(encoding="utf-8-sig"))
    unit_definition = next(node for node in preset_tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == "unit_currents")
    unit_rows = next(ast.literal_eval(node.value) for node in preset_tree.body
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "UNIT_CHOICES"
                             for target in node.targets))
    preset_globals = {"UNIT_CHOICES": unit_rows}
    exec(compile(ast.Module(body=[unit_definition], type_ignores=[]),
                 "current_presets.py", "exec"), preset_globals)
    preset = preset_globals["unit_currents"]
    calc = SimpleNamespace(calculate_ontwerpstroom=consumption,
                           calculate_opwek_ontwerpstroom=generation)
    context = (calc, {"design_framework": "2.0", "one_phase_exception": True},
               config20, config20_kabel, [], [])
    assert preset(context, "Zakelijk", "160") == (138., 138., 138., 138.)
    assert preset(context, "Zakelijk", "250") == (210., 210., 210., 210.)
    assert preset(context, "Zakelijk", "100") == (0., 0., 0., 0.)
    assert preset(context, "Oplaadpunt", "laad25") == (5.8, 6.7, 0., 0.)
    assert preset(context, "Zakelijk", "lt35", "G10-G25",
                  current_service="3 x 63 A") == (138., 65., 138., 65.)
    assert preset(context, "Zakelijk", "lt35", ">G25",
                  current_service="3 x 25 A") == (210., 65., 210., 65.)
    # The complete Kader 2.0 small-business fallback is automatic for
    # smaller connections, but 3x63 without a FUTURE rating is still unknown.
    assert consumption("1 x 25 A","bedrijf","",2015,"G4",config20,1,None,True) == 8.7
    assert consumption("3 x 10 A","bedrijf","",2015,"G10-G25",config20,1,None,True) == 44.
    assert consumption("3 x 63 A","bedrijf","",2015,"G4",config20,1,None,True) == 0.
    # Non-residential BAG has no GEN electrical rating; Kader 2.0 now
    # supplies the explicit first small-business row instead of 0 A.
    assert consumption("verblijfsobject","bedrijf","",2015,"G4",
                       config20,1,None,True) == 8.7
    assert consumption("verblijfsobject","bedrijf","",2015,">G25",
                       config20,1,None,True) == 210.
    # Residential connection stays household through exactly 3x40 A.
    house_cfg = dict(config20, GEBRUIKS_MAP=[(["woonhuis"], 1)])
    assert consumption("3 x 40 A","woonhuis","vrijstaande woning",2024,">G25",
                       house_cfg,1,None,True) == 9.5
    assert consumption("3 x 50 A","woonhuis","vrijstaande woning",2024,">G25",
                       house_cfg,1,None,True,True,None,"3 x 50 A") == 210.

    # The former 3.1 preset still uses precisely the same current/gas path
    # under its renamed 3.2 selection.
    old_context = (calc, {"design_framework": "3.1", "one_phase_exception": True},
                   old, old, [], [])
    renamed_context = (calc, {"design_framework": "3.2", "one_phase_exception": True},
                       renamed, renamed, [], [])
    for key in ("lt35", "35_40", "50", "63", "80", "100", "125", "160", "200", "250"):
        for gas in ("G4", "G10", ">G25"):
            assert preset(old_context, "Zakelijk", key, gas) == preset(
                renamed_context, "Zakelijk", key, gas
            ), (key, gas)
    print("KADER_20_VS_32_REGRESSION_OK")


if __name__ == "__main__":
    test()
