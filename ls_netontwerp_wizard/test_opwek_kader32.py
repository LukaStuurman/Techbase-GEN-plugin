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

        # Huishoudelijk t/m 3x40A blijft onafhankelijk van de (zware)
        # gasaansluiting en van de 1-fase-exceptie-instelling.
        for config, generation_table in ((std_config, opwek_table), (cable_config, opwek_cable_table)):
            for usage in ("woonhuis", "woonfunctie", "Huishoudelijk"):
                for phases in (1, 2, 3):
                    for amp in (25, 40):
                        connection = f"{phases}x{amp}A"
                        for one_phase_exception in (False, True):
                            normal = module.calculate_ontwerpstroom(
                                connection, usage, "hoekwoning", 2020, "Geen", config,
                                10, None, one_phase_exception,
                            )
                            generation = module.calculate_opwek_ontwerpstroom(
                                connection, usage, "hoekwoning", "Geen", generation_table,
                                config, normal, one_phase_exception,
                            )
                            for gas in ("G10", "G25", "G40", ">G25"):
                                actual = module.calculate_ontwerpstroom(
                                    connection, usage, "hoekwoning", 2020, gas, config,
                                    10, None, one_phase_exception,
                                )
                                actual_generation = module.calculate_opwek_ontwerpstroom(
                                    connection, usage, "hoekwoning", gas, generation_table,
                                    config, actual, one_phase_exception,
                                )
                                assert actual == normal, (usage, connection, gas, actual, normal)
                                assert actual_generation == generation, (usage, connection, gas)
            # Grotere huishoudelijke aansluiting blijft via de ampere/zakelijke
            # tabel lopen; gasadvies mag daar nog steeds het verbruik verhogen.
            regular = module.calculate_ontwerpstroom(
                "3x50A", "Huishoudelijk", "hoekwoning", 2020, "Geen", config, 10, None, False,
            )
            gas_adjusted = module.calculate_ontwerpstroom(
                "3x50A", "Huishoudelijk", "hoekwoning", 2020, "G10", config, 10, None, False,
            )
            assert gas_adjusted > regular

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
