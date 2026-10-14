from __future__ import annotations

"""Voorkom dat een vorige handmatige clustercorrectie in de volgende ronde lekt.

De Processing-tool bewaart selecties bewust terwijl resultaatlagen worden
teruggeschreven. Dat is nuttig tijdens één correctie, maar in de wizard/editor
betekende dit dat het vorige doelstation na een succesvolle verplaatsing
selectief bleef. Een volgende aansluitingselectie kon daardoor opnieuw tegen
het vorige station (en diens Max_A/belasting) worden gecontroleerd.

Deze module maakt van iedere geslaagde correctie een duidelijke sessiegrens:
aansluitingen en station worden gedeselecteerd, providers worden opnieuw
ingelezen en de gebruiker moet voor de volgende ronde opnieuw een doelstation
kiezen. Een geweigerde/mislukte correctie houdt de selectie juist vast zodat de
gebruiker de invoer kan herstellen.
"""


def _reload_and_clear(layer) -> None:
    if layer is None:
        return
    try:
        provider = layer.dataProvider()
        if provider is not None:
            provider.forceReload()
    except (AttributeError, RuntimeError):
        pass
    try:
        layer.removeSelection()
    except (AttributeError, RuntimeError):
        pass
    try:
        layer.updateExtents()
        layer.triggerRepaint()
    except (AttributeError, RuntimeError):
        pass


def _success_text(label) -> str:
    try:
        return str(label.text()).strip()
    except (AttributeError, RuntimeError):
        return ""


def _install_manual_page_reset(dialog_module) -> None:
    cls = dialog_module.LSNetontwerpDialog
    original = cls.run_manual_correction
    if getattr(original, "_ls_fresh_target_each_round", False):
        return

    def run_manual_correction(self, *args, **kwargs):
        # Consume Qt's clicked(bool): the underlying action has no arguments.
        original(self)

        message = _success_text(getattr(self, "manual_status_label", None))
        if not message.startswith("Gereed:"):
            return

        # De rekenengine heeft de waarden van het zojuist gebruikte station al
        # bijgewerkt. Lees beide bronlagen opnieuw in en verwijder daarna de
        # selectie die de Processing-tool bewust heeft behouden.
        connections = None
        stations = None
        try:
            connections = self._manual_selected_layer("AANSLUITINGEN")
            stations = self._manual_selected_layer("STATIONS")
        except (AttributeError, KeyError, RuntimeError):
            pass
        _reload_and_clear(connections)
        _reload_and_clear(stations)

        try:
            self._refresh_manual_selection_status()
        except (AttributeError, RuntimeError):
            pass
        try:
            self.manual_status_label.setText(
                message
                + " Nieuwe correctieronde: selecteer opnieuw aansluitingen en "
                "kies daarna opnieuw het doelstation."
            )
            self.manual_status_label.setToolTip(
                "Het vorige doelstation is bewust gedeselecteerd. De volgende "
                "correctie gebruikt pas de capaciteit en belasting van het nieuw "
                "gekozen station."
            )
        except (AttributeError, RuntimeError):
            pass
        try:
            if self.iface is not None:
                self.iface.actionPan().trigger()
                self.iface.mapCanvas().refresh()
        except (AttributeError, RuntimeError):
            pass

    run_manual_correction._ls_fresh_target_each_round = True
    cls.run_manual_correction = run_manual_correction


def _install_visual_editor_reset(editor_module) -> None:
    cls = editor_module.VisueleClusterEditorDialog
    original = cls.apply_change
    if getattr(original, "_ls_fresh_target_each_round", False):
        return

    def apply_change(self, *args, **kwargs):
        original(self)

        message = _success_text(getattr(self, "status_label", None))
        if not message.startswith("Gereed:"):
            return

        connections = None
        stations = None
        try:
            connections = self.layers.get("AANSLUITINGEN")
            stations = self.layers.get("STATIONS")
        except (AttributeError, RuntimeError):
            pass

        _reload_and_clear(connections)
        _reload_and_clear(stations)

        # Ook alle tijdelijke selectie-/kaartstatus uit de vorige ronde wissen.
        try:
            self._waiting = None
        except AttributeError:
            pass
        try:
            self._refresh_preview()
            self._refresh_pre_cluster_choices()
        except (AttributeError, RuntimeError):
            pass
        try:
            self._set_status(
                message
                + " Nieuwe correctieronde: selecteer opnieuw aansluitingen en "
                "klik daarna opnieuw het doelstation aan."
            )
            self.status_label.setToolTip(
                "Het vorige doelstation is na de geslaagde correctie gewist. "
                "Max_A, huidige belasting en routelimieten worden bij de volgende "
                "ronde opnieuw uit het nieuw gekozen station gelezen."
            )
        except (AttributeError, RuntimeError):
            pass
        try:
            if self.iface is not None:
                self.iface.actionPan().trigger()
                self.iface.mapCanvas().refresh()
        except (AttributeError, RuntimeError):
            pass

    apply_change._ls_fresh_target_each_round = True
    cls.apply_change = apply_change


def install() -> None:
    """Installeer de reset vóór de dashboard- en editorclasses worden gebouwd."""
    from . import cluster_paint_dialog, dialog

    _install_manual_page_reset(dialog)
    _install_visual_editor_reset(cluster_paint_dialog)
