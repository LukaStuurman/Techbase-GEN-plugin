def classFactory(iface):
    # Installeer vóór het dashboard wordt geïmporteerd de correctiesessiereset.
    # Zo kan een eerder geselecteerd doelstation nooit doorsijpelen naar de
    # volgende handmatige verplaatsing.
    from .repeated_correction_fix import install

    install()

    from .plugin import LSNetontwerpPlugin

    return LSNetontwerpPlugin(iface)
