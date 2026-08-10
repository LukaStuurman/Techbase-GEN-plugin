from __future__ import annotations

from collections import defaultdict

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessingException,
    QgsProject,
    QgsWkbTypes,
)

from .clustergebieden_vereenvoudigen_tool import (
    ClustergebiedenVereenvoudigenAlgorithm as _BaseClustergebiedenVereenvoudigenAlgorithm,
    _vertex_count,
)


class ClustergebiedenVereenvoudigenAlgorithm(_BaseClustergebiedenVereenvoudigenAlgorithm):
    """Uitbreiding met een expliciete minimale-vertexmodus.

    RECHTE_HOEKEN=True behoudt de bestaande compacte blokworkflow. Bij
    RECHTE_HOEKEN=False worden schuine gedeelde grenzen toegestaan en kiest de
    tool binnen de ingestelde maximale tolerantie de geldige gezamenlijke
    dekking met het laagste totale aantal vertices. De buitenrand van de totale
    dekking blijft daarbij behouden en iedere aansluiting moet in het gebied
    van zijn eigen cluster blijven.
    """

    def createInstance(self):
        return ClustergebiedenVereenvoudigenAlgorithm()

    @staticmethod
    def _shape_vertex_count(geometries):
        total = 0
        for geometry in geometries:
            polygons = (
                list(geometry.geoms)
                if geometry.geom_type == "MultiPolygon"
                else [geometry]
            )
            for polygon in polygons:
                total += len(polygon.exterior.coords)
                total += sum(len(ring.coords) for ring in polygon.interiors)
        return total

    @staticmethod
    def _single_part_areas(geometries):
        """Voorkom dat vertexreductie nieuwe losse exclaves introduceert."""
        return all(
            geometry.geom_type == "Polygon"
            or (
                geometry.geom_type == "MultiPolygon"
                and len(geometry.geoms) == 1
            )
            for geometry in geometries
        )

    @staticmethod
    def _area_change(source, candidate):
        return sum(
            original.symmetric_difference(updated).area
            for original, updated in zip(source, candidate)
        )

    def _minimum_vertex_coverage(
        self,
        shapes,
        clusters,
        points_by_cluster,
        maximum_tolerance,
        feedback,
    ):
        from shapely import coverage_simplify

        original_vertices = self._shape_vertex_count(shapes)
        best_shapes = list(shapes)
        best_tolerance = 0.0
        best_score = (original_vertices, 0.0, 0.0)

        # Niet alleen de grootste tolerantie testen: de veiligste geldige vorm
        # met de minste vertices kan door de topologie bij een lagere tolerantie
        # liggen. Daarom vergelijken we een reeks kandidaten expliciet op het
        # totale aantal hoekpunten.
        factors = (
            1.00,
            0.95,
            0.90,
            0.85,
            0.80,
            0.75,
            0.70,
            0.65,
            0.60,
            0.55,
            0.50,
            0.45,
            0.40,
            0.35,
            0.30,
            0.25,
            0.20,
            0.15,
            0.10,
            0.075,
            0.05,
            0.025,
        )
        maximum_tolerance = max(0.0, float(maximum_tolerance))
        for index, factor in enumerate(factors, 1):
            if feedback.isCanceled():
                break
            tolerance = maximum_tolerance * factor
            if tolerance <= 0.0:
                continue
            try:
                candidate = list(
                    coverage_simplify(
                        shapes,
                        tolerance,
                        # De buitenrand van het volledige clustergebied blijft
                        # gelijk; alleen gedeelde/interne grenzen worden simpeler.
                        simplify_boundary=False,
                    )
                )
            except Exception:
                candidate = []
            if not candidate or not self._single_part_areas(candidate):
                continue
            if not self._valid_result(candidate, clusters, points_by_cluster):
                continue

            vertex_count = self._shape_vertex_count(candidate)
            movement = self._area_change(shapes, candidate)
            # Eerst zo weinig mogelijk vertices, daarna zo weinig mogelijk
            # geometrische verplaatsing. Bij volledige gelijkstand mag de
            # grotere tolerantie winnen.
            score = (vertex_count, movement, -tolerance)
            if score < best_score:
                best_shapes = candidate
                best_tolerance = tolerance
                best_score = score
            feedback.setProgress(min(82, 5 + int(index * 72 / len(factors))))

        # Een tweede gezamenlijke topologische pass kan lange trapvormige
        # gedeelde grenzen nog door één rechte schuine lijn vervangen. Deze
        # helper valideert opnieuw de volledige coverage en alle aansluitingen.
        if maximum_tolerance > 0.0 and not feedback.isCanceled():
            (
                global_shapes,
                _junctions,
                _removed,
                _diagonals,
                global_tolerance,
            ) = self._simplify_shared_boundaries_global(
                best_shapes,
                clusters,
                points_by_cluster,
                maximum_tolerance,
                feedback,
            )
            if self._single_part_areas(global_shapes) and self._valid_result(
                global_shapes, clusters, points_by_cluster
            ):
                global_score = (
                    self._shape_vertex_count(global_shapes),
                    self._area_change(shapes, global_shapes),
                    -max(best_tolerance, global_tolerance),
                )
                if global_score < best_score:
                    best_shapes = global_shapes
                    best_tolerance = max(best_tolerance, global_tolerance)
                    best_score = global_score

        feedback.pushInfo(
            "Minimale-vertexmodus: "
            f"{original_vertices} → {best_score[0]} hoekpunten binnen maximaal "
            f"{maximum_tolerance:.2f} m afwijking."
        )
        return best_shapes, best_tolerance

    def processAlgorithm(self, parameters, context, feedback):
        right_angles = self.parameterAsBoolean(
            parameters, self.RECHTE_HOEKEN, context
        )
        if right_angles:
            return super().processAlgorithm(parameters, context, feedback)

        areas = self.parameterAsVectorLayer(parameters, self.GEBIEDEN, context)
        connections = self.parameterAsVectorLayer(
            parameters, self.AANSLUITINGEN, context
        )
        area_field = self.parameterAsString(
            parameters, self.GEBIED_CLUSTER, context
        )
        connection_field = self.parameterAsString(
            parameters, self.AANSLUITING_CLUSTER, context
        )
        max_tolerance = self.parameterAsDouble(
            parameters, self.MAX_TOLERANTIE_M, context
        )
        if areas is None or connections is None:
            raise QgsProcessingException(
                "De gebieden- of aansluitingenlaag ontbreekt."
            )
        if areas.fields().lookupField(area_field) < 0:
            raise QgsProcessingException(
                f"Kolom '{area_field}' ontbreekt in de gebiedenlaag."
            )
        if connections.fields().lookupField(connection_field) < 0:
            raise QgsProcessingException(
                f"Kolom '{connection_field}' ontbreekt in de aansluitingenlaag."
            )

        from shapely import coverage_is_valid, from_wkb

        features = [
            feature
            for feature in areas.getFeatures()
            if feature.hasGeometry()
        ]
        if not features:
            raise QgsProcessingException("De clustergebiedenlaag is leeg.")
        shapes = [
            from_wkb(bytes(feature.geometry().asWkb()))
            for feature in features
        ]
        clusters = [
            self._cluster_text(feature[area_field])
            for feature in features
        ]
        if any(not cluster for cluster in clusters):
            raise QgsProcessingException(
                "Ieder clustergebied moet een geldige clusterwaarde hebben."
            )

        transform = None
        if connections.crs() != areas.crs():
            transform = QgsCoordinateTransform(
                connections.crs(), areas.crs(), QgsProject.instance()
            )
        points_by_cluster = defaultdict(list)
        for feature in connections.getFeatures():
            if not feature.hasGeometry():
                continue
            cluster = self._cluster_text(feature[connection_field])
            if not cluster:
                continue
            geometry = QgsGeometry(feature.geometry())
            if transform is not None:
                geometry.transform(transform)
            point_geometry = geometry.centroid()
            points_by_cluster[cluster].append(
                from_wkb(bytes(point_geometry.asWkb()))
            )

        if not bool(coverage_is_valid(shapes)):
            feedback.pushInfo(
                "Kleine overlap/gaten in de brongebieden topologisch herstellen…"
            )
            shapes = self._repair_coverage(
                shapes, clusters, points_by_cluster
            )
        if not self._valid_result(shapes, clusters, points_by_cluster):
            raise QgsProcessingException(
                "Minstens een aansluiting ligt al buiten het brongebied van zijn "
                "cluster. Corrigeer eerst de gewone clustergebieden."
            )

        feedback.pushInfo(
            "Minimaal aantal vertices zoeken; schuine gedeelde grenzen zijn toegestaan…"
        )
        best_shapes, best_tolerance = self._minimum_vertex_coverage(
            shapes,
            clusters,
            points_by_cluster,
            max_tolerance,
            feedback,
        )
        if not self._valid_result(
            best_shapes, clusters, points_by_cluster
        ):
            raise QgsProcessingException(
                "Er kon geen topologisch geldige minimale-vertexvariant worden gemaakt."
            )

        fields = QgsFields(areas.fields())
        tolerance_index = fields.lookupField("Simpl_m")
        if tolerance_index < 0:
            fields.append(
                QgsField("Simpl_m", QVariant.Double, len=12, prec=2)
            )
            tolerance_index = fields.lookupField("Simpl_m")
        vertex_index = fields.lookupField("Vertices")
        if vertex_index < 0:
            fields.append(QgsField("Vertices", QVariant.Int))
            vertex_index = fields.lookupField("Vertices")
        block_index = fields.lookupField("Blok_m")
        if block_index < 0:
            fields.append(
                QgsField("Blok_m", QVariant.Double, len=12, prec=2)
            )
            block_index = fields.lookupField("Blok_m")
        junction_index = fields.lookupField("Knoop_m")
        if junction_index < 0:
            fields.append(
                QgsField("Knoop_m", QVariant.Double, len=12, prec=2)
            )
            junction_index = fields.lookupField("Knoop_m")
        mode_index = fields.lookupField("Vormmodus")
        if mode_index < 0:
            fields.append(QgsField("Vormmodus", QVariant.String, len=24))
            mode_index = fields.lookupField("Vormmodus")

        sink, destination = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.multiType(areas.wkbType()),
            areas.crs(),
        )
        if sink is None:
            raise QgsProcessingException(
                "De uitvoerlaag kon niet worden gemaakt."
            )

        original_vertices = 0
        output_vertices = 0
        for feature, shape in zip(features, best_shapes):
            output = QgsFeature(fields)
            output.setAttributes(
                [
                    *feature.attributes(),
                    *([None] * (len(fields) - len(areas.fields()))),
                ]
            )
            geometry = QgsGeometry()
            geometry.fromWkb(shape.wkb)
            if not QgsWkbTypes.isMultiType(geometry.wkbType()):
                geometry.convertToMultiType()
            output.setGeometry(geometry)
            values = output.attributes()
            values[tolerance_index] = round(best_tolerance, 2)
            values[vertex_index] = _vertex_count(geometry)
            values[block_index] = 0.0
            values[junction_index] = 0.0
            values[mode_index] = "min_vertices"
            output.setAttributes(values)
            if not sink.addFeature(output, QgsFeatureSink.FastInsert):
                raise QgsProcessingException(
                    "Een vereenvoudigd gebied kon niet worden opgeslagen."
                )
            original_vertices += _vertex_count(feature.geometry())
            output_vertices += values[vertex_index]

        feedback.setProgress(100)
        shared_relations, right_relations, diagonal_segments = (
            self._boundary_stats(best_shapes)
        )
        feedback.pushInfo(
            f"Minimale-vertexmodus gereed: {original_vertices} → "
            f"{output_vertices} vertices; gebruikte tolerantie "
            f"{best_tolerance:.2f} m; gedeelde grensrelaties "
            f"{shared_relations}; volledig rechte relaties "
            f"{right_relations}; diagonale interne segmenten "
            f"{diagonal_segments}. Alle aansluitingen zijn binnen hun eigen "
            "clustergebied gecontroleerd."
        )
        return {self.OUTPUT: destination}
