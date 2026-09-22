"""Regressietest voor opwekwaarden uit Eea-0205.K 3.2.

Uitvoeren in een Python/QGIS-omgeving, net als test_plugin_headless.py.
"""

from pathlib import Path
import sys

from qgis.core import QgsApplication


def main():
    plugin_parent = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(plugin_parent))

    app = QgsApplication([], False)
    app.initQgis()
    try:
        from ls_netontwerp_wizard.algorithms.woningtype_selectie_herberekenen_tool import (
            _configurations,
            _load_design_module,
        )

        module = _load_design_module()
        std_config, cable_config, opwek_table, opwek_cable_table = _configurations(
            {}, module
        )

        # Kader 3.2, Type 9/eigen richting: 3x100A en 3x125A met
        # G4/G6/geen/ander gas hebben voor opwek dezelfde waarde als verbruik.
        for doorlaat, expected in (("3x100A", 85.0), ("3x125A", 106.0)):
            normal = module.calculate_ontwerpstroom(
                doorlaat,
                "bedrijf",
                "",
                2020,
                "G4",
                std_config,
                1,
                None,
                True,
                True,
            )
            generation = module.calculate_opwek_ontwerpstroom(
                doorlaat,
                "bedrijf",
                "",
                "G4",
                opwek_table,
                std_config,
                normal,
                True,
            )
            assert normal == expected
            assert generation == expected

        # Regressie voor het gemelde 0 A-probleem: een aansluiting die als
        # appartement/woonfunctie is geclassificeerd maar boven de woonhuisgrens
        # valt, wordt voor verbruik via de ampere-/zakelijke tabel behandeld.
        # Opwek moet dan dezelfde waarde volgen en mag niet eerst door de
        # appartement-nulregel worden afgevangen.
        normal = module.calculate_ontwerpstroom(
            "3x100A",
            "woonfunctie",
            "appartement",
            2020,
            "G4",
            std_config,
            2,
            None,
            True,
            True,
        )
        generation = module.calculate_opwek_ontwerpstroom(
            "3x100A",
            "woonfunctie",
            "appartement",
            "G4",
            opwek_table,
            std_config,
            normal,
            True,
        )
        assert normal == 85.0
        assert generation == normal

        cable = module.calculate_ontwerpstroom(
            "3x100A",
            "woonfunctie",
            "appartement",
            2020,
            "G4",
            cable_config,
            3,
            None,
            True,
            True,
        )
        cable_generation = module.calculate_opwek_ontwerpstroom(
            "3x100A",
            "woonfunctie",
            "appartement",
            "G4",
            opwek_cable_table,
            cable_config,
            cable,
            True,
        )
        assert cable == 85.0
        assert cable_generation == cable

        # Type 8 kleinzakelijk: kabel en trafo kunnen door de gastabel van
        # elkaar verschillen, maar opwek volgt per netvlak exact verbruik.
        trafo_business = module.calculate_ontwerpstroom(
            "3x63A",
            "bedrijf",
            "",
            2020,
            "G10",
            std_config,
            4,
            None,
            True,
            True,
        )
        cable_business = module.calculate_ontwerpstroom(
            "3x63A",
            "bedrijf",
            "",
            2020,
            "G10",
            cable_config,
            5,
            None,
            True,
            True,
        )
        assert trafo_business == 138.0
        assert cable_business == 65.0
        assert module.calculate_opwek_ontwerpstroom(
            "3x63A",
            "bedrijf",
            "",
            "G10",
            opwek_table,
            std_config,
            trafo_business,
            True,
        ) == trafo_business
        assert module.calculate_opwek_ontwerpstroom(
            "3x63A",
            "bedrijf",
            "",
            "G10",
            opwek_cable_table,
            cable_config,
            cable_business,
            True,
        ) == cable_business
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
