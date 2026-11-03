"""Deterministische tests voor dakcontacten, zonder AHN-netwerk en zonder 3DBAG."""
import tempfile

from qgis.core import QgsGeometry, QgsProcessingFeedback

from ls_netontwerp_wizard.ahn_roof_contact import (
    AhnRoofContact, _contact_samples, roof_connection_decision,
)


def _polygon(x0, x1):
    return QgsGeometry.fromWkt(
        "POLYGON((%s 0,%s 0,%s 10,%s 10,%s 0))"
        % (x0, x1, x1, x0, x0)
    )


def test_roof_thresholds():
    assert roof_connection_decision([6.0]*4, [6.3]*4, [6.5]*8, [6.6]*8) is True
    assert roof_connection_decision([2.6]*4, [2.8]*4, [7.0]*8, [7.0]*8) is False
    assert roof_connection_decision([6.0]*4, [7.9]*4, [7.0]*8, [8.9]*8) is None
    assert roof_connection_decision([6.0]*2, [6.0]*2, [6.0], [6.0]) is None


def test_adjacent_roof_and_carport_without_network():
    a, b = _polygon(0, 10), _polygon(10, 20)
    assert len(_contact_samples(a, b)) >= 3

    with tempfile.TemporaryDirectory() as directory:
        contact = AhnRoofContact(
            QgsProcessingFeedback(), cache_dir=directory, offline_only=True
        )
        contact.height = lambda x, y: 7.0
        assert contact.check_pair(a, b) is True
        contact.height = lambda x, y: 2.0 if abs(x-10) < 3 else 7.0
        assert contact.check_pair(a, b) is False
        contact.height = lambda x, y: None
        assert contact.check_pair(a, b) is None


def test_only_neighbor_pairs_are_checked():
    geometries = (_polygon(0, 10), _polygon(10, 20), _polygon(50, 60))
    data = [
        dict(geom=geom, has_woon=True, is_app=False, ignore_neighbor=False)
        for geom in geometries
    ]
    with tempfile.TemporaryDirectory() as directory:
        contact = AhnRoofContact(
            QgsProcessingFeedback(), cache_dir=directory, offline_only=True
        )
        contact.height = lambda x, y: 7.0
        contact.populate_tile(data)
    assert data[0]["ahn_roof_links"] == {1: True}
    assert data[1]["ahn_roof_links"] == {0: True}
    assert data[2]["ahn_roof_links"] == {}


if __name__ == "__main__":
    from qgis.core import QgsApplication
    app = QgsApplication([], False)
    app.initQgis()
    try:
        test_roof_thresholds()
        test_adjacent_roof_and_carport_without_network()
        test_only_neighbor_pairs_are_checked()
        print("AHN dakcontact-tests geslaagd")
    finally:
        app.exitQgis()
