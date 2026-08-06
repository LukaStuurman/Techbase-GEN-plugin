from __future__ import annotations

from collections import defaultdict

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsWkbTypes,
)

from .handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm


def _vertex_count(geometry):
    return sum(1 for _ in geometry.vertices())


class ClustergebiedenVereenvoudigenAlgorithm(QgsProcessingAlgorithm):
    """Topologically simplify a complete cluster-area coverage."""

    GEBIEDEN = "GEBIEDEN"
    AANSLUITINGEN = "AANSLUITINGEN"
    GEBIED_CLUSTER = "GEBIED_CLUSTER"
    AANSLUITING_CLUSTER = "AANSLUITING_CLUSTER"
    MAX_TOLERANTIE_M = "MAX_TOLERANTIE_M"
    RECHTE_HOEKEN = "RECHTE_HOEKEN"
    MIN_BREEDTE_M = "MIN_BREEDTE_M"
    KNOOP_AFSCHUINING_M = "KNOOP_AFSCHUINING_M"
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("ClustergebiedenVereenvoudigen", text)

    def createInstance(self):
        return ClustergebiedenVereenvoudigenAlgorithm()

    def name(self):
        return "clustergebieden_topologisch_vereenvoudigen"

    def displayName(self):
        return self.tr("Clustergebieden mooi en topologisch vereenvoudigen")

    def group(self):
        return self.tr("Netontwerp")

    def groupId(self):
        return "netontwerp"

    def shortHelpString(self):
        return self.tr(
            "Vereenvoudigt alle clustergebieden als een gezamenlijke dekking. "
            "Gedeelde grenzen blijven exact gelijk en iedere aansluiting moet "
            "binnen het gebied van zijn eigen cluster blijven. Als de gekozen "
            "tolerantie te groot is, zoekt de tool automatisch de grootste veilige waarde. "
            "Standaard worden interne grenzen daarna horizontaal/verticaal gemaakt "
            "met uitsluitend 90°-hoeken en zo weinig mogelijk knikken. Smalle lege "
            "uitlopers worden aan het aangrenzende compacte gebied toegewezen; "
            "aansluitingen en aaneengeslotenheid blijven verplicht. In een laatste "
            "gezamenlijke topologische stap mogen rechte schuine gedeelde grenzen "
            "worden gebruikt wanneer die duidelijk minder hoekpunten nodig hebben; "
            "3+-clusterpunten blijven daarbij exact één gedeelde knoop."
        )

    def initAlgorithm(self, config=None):
        defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        areas = QgsProcessingParameterVectorLayer(
            self.GEBIEDEN,
            self.tr("Clustergebieden"),
            [QgsProcessing.TypeVectorPolygon],
        )
        if defaults.get(HandmatigeClusterCorrectieAlgorithm.GEBIEDEN):
            areas.setDefaultValue(defaults[HandmatigeClusterCorrectieAlgorithm.GEBIEDEN])
        self.addParameter(areas)
        points = QgsProcessingParameterVectorLayer(
            self.AANSLUITINGEN,
            self.tr("Aansluitingen geclusterd"),
            [QgsProcessing.TypeVectorPoint],
        )
        if defaults.get(HandmatigeClusterCorrectieAlgorithm.AANSLUITINGEN):
            points.setDefaultValue(defaults[HandmatigeClusterCorrectieAlgorithm.AANSLUITINGEN])
        self.addParameter(points)
        self.addParameter(
            QgsProcessingParameterField(
                self.GEBIED_CLUSTER,
                self.tr("Clusterkolom gebieden"),
                parentLayerParameterName=self.GEBIEDEN,
                defaultValue="Cluster",
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.AANSLUITING_CLUSTER,
                self.tr("Clusterkolom aansluitingen"),
                parentLayerParameterName=self.AANSLUITINGEN,
                defaultValue="Cluster",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_TOLERANTIE_M,
                self.tr("Maximale vereenvoudigingstolerantie (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=12.0,
                minValue=0.01,
                maxValue=250.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KNOOP_AFSCHUINING_M,
                self.tr("Schuine topologische grensvereenvoudiging (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=12.0,
                minValue=0.0,
                maxValue=50.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RECHTE_HOEKEN,
                self.tr("Interne grenzen horizontaal/verticaal met 90°-hoeken"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_BREEDTE_M,
                self.tr("Minimale breedte van gebiedshals/uitloper (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=20.0,
                minValue=0.0,
                maxValue=100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr("Clustergebieden vereenvoudigd")
            )
        )

    @staticmethod
    def _cluster_text(value):
        return "" if value is None else str(value).strip()

    @staticmethod
    def _valid_result(shapes, clusters, points_by_cluster):
        from shapely import coverage_is_valid
        from shapely.ops import unary_union

        if any(shape.is_empty or not shape.is_valid for shape in shapes):
            return False
        if not bool(coverage_is_valid(shapes)):
            return False
        grouped = defaultdict(list)
        for cluster, shape in zip(clusters, shapes):
            grouped[cluster].append(shape)
        for cluster, points in points_by_cluster.items():
            if cluster not in grouped:
                return False
            area = unary_union(grouped[cluster])
            if any(not area.covers(point) for point in points):
                return False
        return True

    @staticmethod
    def _repair_coverage(shapes, clusters, points_by_cluster):
        """Polygonize all borders and assign every atomic cell exactly once."""
        from shapely.ops import polygonize, unary_union

        linework = unary_union([shape.boundary for shape in shapes])
        cells = [cell for cell in polygonize(linework) if cell.area > 1e-6]
        assigned = defaultdict(list)
        cluster_indices = defaultdict(list)
        for index, cluster in enumerate(clusters):
            cluster_indices[cluster].append(index)
        for cell in cells:
            overlaps = [cell.intersection(shape).area for shape in shapes]
            maximum = max(overlaps, default=0.0)
            # Do not fill true gaps or holes which were outside every source area.
            if maximum <= 1e-6:
                continue
            forced_clusters = {
                cluster
                for cluster, points in points_by_cluster.items()
                if any(cell.contains(point) for point in points)
            }
            if len(forced_clusters) > 1:
                raise QgsProcessingException(
                    "Twee aansluitingen van verschillende clusters liggen in hetzelfde "
                    "overlappende bronvlak; deze overlap kan niet automatisch veilig "
                    "worden hersteld."
                )
            candidates = (
                cluster_indices[next(iter(forced_clusters))]
                if forced_clusters
                else range(len(shapes))
            )
            owner = max(candidates, key=lambda index: overlaps[index])
            assigned[owner].append(cell)
        repaired = []
        for index in range(len(shapes)):
            if not assigned[index]:
                raise QgsProcessingException(
                    f"Clustergebied {clusters[index]} verdwijnt bij het herstellen van overlap."
                )
            repaired.append(unary_union(assigned[index]))
        return repaired

    @staticmethod
    def _line_parts(geometry):
        if geometry.geom_type == "LineString":
            return [geometry]
        if geometry.geom_type in ("MultiLineString", "GeometryCollection"):
            result = []
            for part in geometry.geoms:
                result.extend(ClustergebiedenVereenvoudigenAlgorithm._line_parts(part))
            return result
        return []

    @staticmethod
    def _orthogonalize_boundaries(shapes, clusters, points_by_cluster, feedback):
        """Replace shared borders by the simplest safe rectilinear cuts."""
        from shapely import from_wkb
        from shapely.geometry import LineString, Point
        from shapely.ops import linemerge

        from .clustergebied_grens import replace_shared_boundary

        result = list(shapes)
        converted = 0
        skipped = 0
        pairs = []
        for first in range(len(result)):
            for second in range(first + 1, len(result)):
                if result[first].boundary.intersection(result[second].boundary).length > 0.001:
                    pairs.append((first, second))
        for number, (first, second) in enumerate(pairs, 1):
            if feedback.isCanceled():
                break
            shared = result[first].boundary.intersection(result[second].boundary)
            parts = ClustergebiedenVereenvoudigenAlgorithm._line_parts(shared)
            if not parts:
                continue
            already_axis_aligned = all(
                abs(start[0] - end[0]) <= 1e-8
                or abs(start[1] - end[1]) <= 1e-8
                for part in parts
                for start, end in zip(list(part.coords), list(part.coords)[1:])
            )
            combined = result[first].union(result[second])
            merged = linemerge(parts)
            if merged.geom_type == "LineString":
                coordinates = list(merged.coords)
                start = coordinates[0]
                end = coordinates[-1]
            else:
                # Interlocking source polygons can share several separate line
                # pieces. Replace the whole relation by one divider between the
                # two shared endpoints on the outside of their combined area.
                endpoints = []
                for part in parts:
                    part_coordinates = list(part.coords)
                    if part_coordinates:
                        endpoints.extend((part_coordinates[0], part_coordinates[-1]))
                exterior_endpoints = [
                    point
                    for point in endpoints
                    if combined.boundary.distance(Point(point)) <= 0.01
                ]
                endpoint_pool = exterior_endpoints if len(exterior_endpoints) >= 2 else endpoints
                if len(endpoint_pool) < 2:
                    skipped += 1
                    continue
                start, end = max(
                    (
                        (left, right)
                        for offset, left in enumerate(endpoint_pool)
                        for right in endpoint_pool[offset + 1:]
                    ),
                    key=lambda pair: (pair[0][0] - pair[1][0]) ** 2
                    + (pair[0][1] - pair[1][1]) ** 2,
                )
                coordinates = [start, end]
            minx, miny, maxx, maxy = combined.bounds
            centre = shared.centroid
            x_values = {
                start[0],
                end[0],
                centre.x,
                (start[0] + end[0]) / 2.0,
                minx + (maxx - minx) * 0.25,
                minx + (maxx - minx) * 0.50,
                minx + (maxx - minx) * 0.75,
            }
            y_values = {
                start[1],
                end[1],
                centre.y,
                (start[1] + end[1]) / 2.0,
                miny + (maxy - miny) * 0.25,
                miny + (maxy - miny) * 0.50,
                miny + (maxy - miny) * 0.75,
            }

            def clean(values):
                cleaned = []
                for value in values:
                    point = (float(value[0]), float(value[1]))
                    if not cleaned or point != cleaned[-1]:
                        cleaned.append(point)
                changed = True
                while changed and len(cleaned) >= 3:
                    changed = False
                    reduced = [cleaned[0]]
                    for index in range(1, len(cleaned) - 1):
                        previous = reduced[-1]
                        current = cleaned[index]
                        following = cleaned[index + 1]
                        if (
                            abs(previous[0] - current[0]) <= 1e-9
                            and abs(current[0] - following[0]) <= 1e-9
                        ) or (
                            abs(previous[1] - current[1]) <= 1e-9
                            and abs(current[1] - following[1]) <= 1e-9
                        ):
                            changed = True
                            continue
                        reduced.append(current)
                    reduced.append(cleaned[-1])
                    cleaned = reduced
                return cleaned

            def staircase(reference, horizontal_first):
                path = [reference[0]]
                for index, target in enumerate(reference[1:]):
                    source = path[-1]
                    use_horizontal_first = (
                        horizontal_first if index % 2 == 0 else not horizontal_first
                    )
                    corner = (
                        (target[0], source[1])
                        if use_horizontal_first
                        else (source[0], target[1])
                    )
                    path.extend((corner, target))
                return clean(path)

            def densify(reference, maximum_step=4.0):
                dense = [reference[0]]
                for source, target in zip(reference, reference[1:]):
                    distance = (
                        (target[0] - source[0]) ** 2
                        + (target[1] - source[1]) ** 2
                    ) ** 0.5
                    steps = max(1, int(distance / maximum_step) + 1)
                    for step in range(1, steps + 1):
                        fraction = step / steps
                        dense.append(
                            (
                                source[0] + (target[0] - source[0]) * fraction,
                                source[1] + (target[1] - source[1]) * fraction,
                            )
                        )
                return dense

            candidates = []
            if abs(start[0] - end[0]) <= 1e-8 or abs(start[1] - end[1]) <= 1e-8:
                candidates.append(clean([start, end]))
            candidates.extend(
                [
                    clean([start, (start[0], end[1]), end]),
                    clean([start, (end[0], start[1]), end]),
                ]
            )
            for x_value in x_values:
                candidates.append(
                    clean(
                        [
                            start,
                            (x_value, start[1]),
                            (x_value, end[1]),
                            end,
                        ]
                    )
                )
            for y_value in y_values:
                candidates.append(
                    clean(
                        [
                            start,
                            (start[0], y_value),
                            (end[0], y_value),
                            end,
                        ]
                    )
                )
            # Safe fallback for winding boundaries: make small orthogonal
            # steps close to the existing divider. The simpler candidates win
            # whenever they are valid because candidates are scored by vertex
            # count first.
            candidates.append(staircase(coordinates, True))
            candidates.append(staircase(coordinates, False))
            if len(coordinates) > 1:
                for maximum_step in (4.0, 2.0, 1.0, 0.5, 0.2, 0.05, 0.01):
                    dense_coordinates = densify(coordinates, maximum_step)
                    candidates.append(staircase(dense_coordinates, True))
                    candidates.append(staircase(dense_coordinates, False))
            unique = {}
            for candidate in candidates:
                if len(candidate) >= 2:
                    unique[tuple(candidate)] = candidate
            valid = []
            candidate_errors = defaultdict(int)
            point_wkb_first = [point.wkb for point in points_by_cluster.get(clusters[first], [])]
            point_wkb_second = [point.wkb for point in points_by_cluster.get(clusters[second], [])]
            for candidate in sorted(unique.values(), key=len):
                if valid and len(candidate) > valid[0][0]:
                    break
                line = LineString(candidate)
                if not line.is_simple or line.length <= 0.001:
                    continue
                try:
                    first_wkb, second_wkb = replace_shared_boundary(
                        result[first].wkb,
                        result[second].wkb,
                        line.wkb,
                        point_wkb_first,
                        point_wkb_second,
                    )
                    first_shape = from_wkb(first_wkb)
                    second_shape = from_wkb(second_wkb)
                except (ValueError, TypeError) as error:
                    candidate_errors[str(error)] += 1
                    continue
                area_change = abs(first_shape.area - result[first].area)
                distance = line.hausdorff_distance(shared)
                valid.append(
                    (
                        len(candidate),
                        area_change,
                        distance,
                        first_shape,
                        second_shape,
                    )
                )
            if valid:
                _, _, _, result[first], result[second] = min(
                    valid, key=lambda item: item[:3]
                )
                converted += 1
            else:
                if not already_axis_aligned:
                    skipped += 1
                    feedback.pushWarning(
                        f"Gedeelde grens {clusters[first]} / {clusters[second]} kon "
                        "niet veilig recht worden gezet zonder een aansluiting af te snijden. "
                        + (
                            max(candidate_errors, key=candidate_errors.get)
                            if candidate_errors
                            else "Geen geldige rechthoekige scheidslijn."
                        )
                    )
            feedback.setProgress(
                min(98, 90 + int(number * 8 / max(1, len(pairs))))
            )
        return result, converted, skipped

    @staticmethod
    def _boundary_stats(shapes):
        relations = 0
        right_relations = 0
        diagonal_segments = 0
        for first in range(len(shapes)):
            for second in range(first + 1, len(shapes)):
                shared = shapes[first].boundary.intersection(shapes[second].boundary)
                if shared.length <= 0.001:
                    continue
                relations += 1
                diagonal = 0
                for part in ClustergebiedenVereenvoudigenAlgorithm._line_parts(shared):
                    coordinates = list(part.coords)
                    for start, end in zip(coordinates, coordinates[1:]):
                        if (
                            abs(start[0] - end[0]) > 1e-8
                            and abs(start[1] - end[1]) > 1e-8
                        ):
                            diagonal += 1
                diagonal_segments += diagonal
                if diagonal == 0:
                    right_relations += 1
        return relations, right_relations, diagonal_segments

    @staticmethod
    def _junction_points(shapes):
        """Return exact coverage vertices shared by at least three polygons."""
        memberships = defaultdict(set)

        def polygons(geometry):
            return list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]

        for index, shape in enumerate(shapes):
            for polygon in polygons(shape):
                rings = [polygon.exterior, *polygon.interiors]
                for ring in rings:
                    for x_value, y_value in ring.coords:
                        memberships[(round(x_value, 6), round(y_value, 6))].add(index)
        return [coordinate for coordinate, owners in memberships.items() if len(owners) >= 3]

    @staticmethod
    def _simplify_multicluster_junctions(
        shapes, clusters, points_by_cluster, maximum_tolerance, feedback
    ):
        """Chamfer only tiny staircase corners near 3+-cluster junctions."""
        from shapely import from_wkb
        from shapely.geometry import LineString
        from shapely.ops import linemerge

        from .clustergebied_grens import replace_shared_boundary

        junctions = ClustergebiedenVereenvoudigenAlgorithm._junction_points(shapes)
        if maximum_tolerance <= 0.0:
            return list(shapes), len(junctions), 0, 0
        result = list(shapes)
        removed = 0
        diagonal_count = 0
        for first in range(len(result)):
            for second in range(first + 1, len(result)):
                shared = result[first].boundary.intersection(result[second].boundary)
                parts = [
                    part
                    for part in ClustergebiedenVereenvoudigenAlgorithm._line_parts(shared)
                    if not part.is_empty and part.length > 1e-8
                ]
                if not parts:
                    continue
                merged = linemerge(parts)
                if merged.geom_type != "LineString":
                    continue
                coordinates = list(merged.coords)
                if len(coordinates) < 3:
                    continue

                def trim_options(values, endpoint_is_junction):
                    options = [1]
                    if not endpoint_is_junction:
                        return options
                    cumulative = 0.0
                    for index in range(1, len(values) - 1):
                        previous = values[index - 1]
                        current = values[index]
                        cumulative += (
                            (current[0] - previous[0]) ** 2
                            + (current[1] - previous[1]) ** 2
                        ) ** 0.5
                        if index >= 2 and cumulative <= maximum_tolerance + 1e-8:
                            options.append(index)
                    return options

                left_options = trim_options(coordinates, True)
                right_options = trim_options(list(reversed(coordinates)), True)
                valid = []
                point_wkb_first = [
                    point.wkb for point in points_by_cluster.get(clusters[first], [])
                ]
                point_wkb_second = [
                    point.wkb for point in points_by_cluster.get(clusters[second], [])
                ]
                for left_trim in left_options:
                    for right_trim in right_options:
                        middle_end = len(coordinates) - 1 - right_trim
                        candidate_coordinates = [coordinates[0]]
                        if left_trim <= middle_end:
                            candidate_coordinates.extend(
                                coordinates[left_trim : middle_end + 1]
                            )
                        if candidate_coordinates[-1] != coordinates[-1]:
                            candidate_coordinates.append(coordinates[-1])
                        if len(candidate_coordinates) >= len(coordinates):
                            continue
                        candidate_line = LineString(candidate_coordinates)
                        if not candidate_line.is_simple:
                            continue
                        try:
                            first_wkb, second_wkb = replace_shared_boundary(
                                result[first].wkb,
                                result[second].wkb,
                                candidate_line.wkb,
                                point_wkb_first,
                                point_wkb_second,
                            )
                            first_shape = from_wkb(first_wkb)
                            second_shape = from_wkb(second_wkb)
                        except (ValueError, TypeError):
                            continue
                        removed_here = len(coordinates) - len(candidate_coordinates)
                        area_change = abs(first_shape.area - result[first].area)
                        diagonal_lengths = [
                            (
                                (start[0] - end[0]) ** 2
                                + (start[1] - end[1]) ** 2
                            ) ** 0.5
                            for start, end in zip(
                                candidate_coordinates, candidate_coordinates[1:]
                            )
                            if abs(start[0] - end[0]) > 1e-8
                            and abs(start[1] - end[1]) > 1e-8
                        ]
                        if any(
                            length > maximum_tolerance * 3.0 + 1e-8
                            for length in diagonal_lengths
                        ):
                            continue
                        diagonals_here = len(diagonal_lengths)
                        valid.append(
                            (
                                -removed_here,
                                area_change,
                                first_shape,
                                second_shape,
                                removed_here,
                                diagonals_here,
                            )
                        )
                # Also chamfer a short dogleg in the middle of a two-area
                # border. Only a small local subpath may be replaced, so the
                # overall block direction remains horizontal/vertical.
                for start_index in range(0, len(coordinates) - 2):
                    first_step = coordinates[start_index + 1]
                    cumulative = (
                        (coordinates[start_index][0] - first_step[0]) ** 2
                        + (coordinates[start_index][1] - first_step[1]) ** 2
                    ) ** 0.5
                    for end_index in range(start_index + 2, len(coordinates)):
                        previous = coordinates[end_index - 1]
                        current = coordinates[end_index]
                        cumulative += (
                            (current[0] - previous[0]) ** 2
                            + (current[1] - previous[1]) ** 2
                        ) ** 0.5
                        if cumulative > maximum_tolerance * 4.0:
                            break
                        chord_length = (
                            (coordinates[start_index][0] - current[0]) ** 2
                            + (coordinates[start_index][1] - current[1]) ** 2
                        ) ** 0.5
                        if chord_length > maximum_tolerance * 3.0 + 1e-8:
                            continue
                        candidate_coordinates = (
                            coordinates[: start_index + 1]
                            + coordinates[end_index:]
                        )
                        candidate_line = LineString(candidate_coordinates)
                        if not candidate_line.is_simple:
                            continue
                        try:
                            first_wkb, second_wkb = replace_shared_boundary(
                                result[first].wkb,
                                result[second].wkb,
                                candidate_line.wkb,
                                point_wkb_first,
                                point_wkb_second,
                            )
                            first_shape = from_wkb(first_wkb)
                            second_shape = from_wkb(second_wkb)
                        except (ValueError, TypeError):
                            continue
                        removed_here = end_index - start_index - 1
                        area_change = abs(first_shape.area - result[first].area)
                        diagonal_here = int(
                            abs(coordinates[start_index][0] - current[0]) > 1e-8
                            and abs(coordinates[start_index][1] - current[1]) > 1e-8
                        )
                        valid.append(
                            (
                                -removed_here,
                                area_change,
                                first_shape,
                                second_shape,
                                removed_here,
                                diagonal_here,
                            )
                        )
                # Douglas-Peucker candidates remove small doglegs in the
                # middle of an ordinary two-area boundary as well. Pairwise
                # split validation below keeps this strictly local and safe.
                for factor in (1.0, 0.75, 0.5, 0.25):
                    simplified_line = merged.simplify(
                        maximum_tolerance * factor,
                        preserve_topology=True,
                    )
                    if simplified_line.geom_type != "LineString":
                        continue
                    candidate_coordinates = list(simplified_line.coords)
                    if len(candidate_coordinates) >= len(coordinates):
                        continue
                    try:
                        first_wkb, second_wkb = replace_shared_boundary(
                            result[first].wkb,
                            result[second].wkb,
                            simplified_line.wkb,
                            point_wkb_first,
                            point_wkb_second,
                        )
                        first_shape = from_wkb(first_wkb)
                        second_shape = from_wkb(second_wkb)
                    except (ValueError, TypeError):
                        continue
                    removed_here = len(coordinates) - len(candidate_coordinates)
                    area_change = abs(first_shape.area - result[first].area)
                    diagonal_lengths = [
                        (
                            (start[0] - end[0]) ** 2
                            + (start[1] - end[1]) ** 2
                        ) ** 0.5
                        for start, end in zip(
                            candidate_coordinates, candidate_coordinates[1:]
                        )
                        if abs(start[0] - end[0]) > 1e-8
                        and abs(start[1] - end[1]) > 1e-8
                    ]
                    if any(
                        length > maximum_tolerance * 3.0 + 1e-8
                        for length in diagonal_lengths
                    ):
                        continue
                    diagonals_here = len(diagonal_lengths)
                    valid.append(
                        (
                            -removed_here,
                            area_change,
                            first_shape,
                            second_shape,
                            removed_here,
                            diagonals_here,
                        )
                    )
                if valid:
                    (
                        _,
                        _,
                        result[first],
                        result[second],
                        removed_here,
                        diagonals_here,
                    ) = min(valid, key=lambda item: item[:2])
                    removed += removed_here
                    diagonal_count += diagonals_here
        if removed:
            feedback.pushInfo(
                f"{removed} kleine grenshoekjes lokaal samengevoegd."
            )
        if not ClustergebiedenVereenvoudigenAlgorithm._valid_result(
            result, clusters, points_by_cluster
        ):
            return list(shapes), len(junctions), 0, 0
        return result, len(junctions), removed, diagonal_count

    @staticmethod
    def _simplify_shared_boundaries_global(
        shapes, clusters, points_by_cluster, maximum_tolerance, feedback
    ):
        """Simplify the full coverage together, allowing long clean diagonals."""
        from shapely import coverage_simplify

        def vertex_count(geometries):
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

        def single_parts(geometries):
            return all(
                geometry.geom_type == "Polygon"
                or (
                    geometry.geom_type == "MultiPolygon"
                    and len(geometry.geoms) == 1
                )
                for geometry in geometries
            )

        junctions_before = ClustergebiedenVereenvoudigenAlgorithm._junction_points(
            shapes
        )
        original_vertices = vertex_count(shapes)
        best = list(shapes)
        best_vertices = original_vertices
        used_tolerance = 0.0
        if maximum_tolerance > 0.0:
            for factor in (1.0, 0.85, 0.7, 0.55, 0.4, 0.25):
                tolerance = maximum_tolerance * factor
                try:
                    candidate = list(
                        coverage_simplify(
                            shapes,
                            tolerance,
                            simplify_boundary=False,
                        )
                    )
                except Exception:
                    continue
                if not single_parts(candidate):
                    continue
                if not ClustergebiedenVereenvoudigenAlgorithm._valid_result(
                    candidate, clusters, points_by_cluster
                ):
                    continue
                candidate_vertices = vertex_count(candidate)
                if candidate_vertices < best_vertices:
                    best = candidate
                    best_vertices = candidate_vertices
                    used_tolerance = tolerance

        # Count internal diagonal segments in the accepted topological coverage.
        diagonal_segments = 0
        for first in range(len(best)):
            for second in range(first + 1, len(best)):
                shared = best[first].boundary.intersection(best[second].boundary)
                for part in ClustergebiedenVereenvoudigenAlgorithm._line_parts(shared):
                    coordinates = list(part.coords)
                    diagonal_segments += sum(
                        1
                        for start, end in zip(coordinates, coordinates[1:])
                        if abs(start[0] - end[0]) > 1e-8
                        and abs(start[1] - end[1]) > 1e-8
                    )
        removed = max(0, original_vertices - best_vertices)
        if removed:
            feedback.pushInfo(
                f"{removed} grenshoekpunten verwijderd met een gezamenlijke "
                f"topologische tolerantie van {used_tolerance:.2f} m."
            )
        return (
            best,
            len(junctions_before),
            removed,
            diagonal_segments,
            used_tolerance,
        )

    @staticmethod
    def _remove_panhandles(shapes, clusters, points_by_cluster, minimum_width, feedback):
        """Reassign narrow empty appendages to the nearest compact neighbour."""
        from shapely.ops import polygonize, unary_union

        if minimum_width <= 0.0:
            return list(shapes), 0
        radius = minimum_width / 2.0
        combined = unary_union(shapes)
        cores = []
        for shape in shapes:
            core = shape.buffer(-radius, join_style="mitre").buffer(
                radius, join_style="mitre"
            )
            core = core.intersection(shape)
            # A genuinely small cluster must not disappear just because its
            # whole area is narrower than the requested appendage width.
            cores.append(shape if core.is_empty else core)

        linework = unary_union(
            [combined.boundary]
            + [shape.boundary for shape in shapes]
            + [core.boundary for core in cores]
        )
        cells = [
            cell
            for cell in polygonize(linework)
            if cell.area > 1e-6 and combined.covers(cell.representative_point())
        ]
        if not cells:
            return list(shapes), 0

        cluster_index = {cluster: index for index, cluster in enumerate(clusters)}
        assigned = defaultdict(list)
        reassigned = 0
        for cell in cells:
            representative = cell.representative_point()
            forced = {
                cluster
                for cluster, points in points_by_cluster.items()
                if any(cell.contains(point) for point in points)
            }
            if len(forced) > 1:
                raise QgsProcessingException(
                    "Aansluitingen van verschillende clusters liggen te dicht bij "
                    "elkaar om met de ingestelde blokbreedte veilig te scheiden."
                )
            original_owner = next(
                (
                    index
                    for index, shape in enumerate(shapes)
                    if shape.covers(representative)
                ),
                None,
            )
            if forced:
                owner = cluster_index[next(iter(forced))]
            else:
                distances = [representative.distance(core) for core in cores]
                owner = min(
                    range(len(cores)),
                    key=lambda index: (
                        round(distances[index], 6),
                        0 if index == original_owner else 1,
                    ),
                )
            assigned[owner].append(cell)
            if original_owner is not None and owner != original_owner:
                reassigned += 1

        compact = []
        for index, original in enumerate(shapes):
            if not assigned[index]:
                return list(shapes), 0
            geometry = unary_union(assigned[index])
            parts = (
                list(geometry.geoms)
                if geometry.geom_type == "MultiPolygon"
                else [geometry]
            )
            if geometry.geom_type not in ("Polygon", "MultiPolygon") or len(parts) != 1:
                # Never introduce an exclave while removing a panhandle.
                feedback.pushWarning(
                    f"Blokvorm voor {clusters[index]} zou een exclave maken; "
                    "de veilige rechte vorm blijft behouden."
                )
                return list(shapes), 0
            compact.append(geometry)
        return compact, reassigned

    @staticmethod
    def _rectangular_partition(shapes, clusters, points_by_cluster, minimum_width, feedback):
        """Build a compact axis-aligned decision partition from labelled points."""
        from collections import Counter
        from shapely.geometry import LineString, box
        from shapely.ops import nearest_points, unary_union

        combined = unary_union(shapes)
        minx, miny, maxx, maxy = combined.bounds
        records = []
        for cluster in clusters:
            cluster_points = list(points_by_cluster.get(cluster, []))
            if not cluster_points:
                source = shapes[clusters.index(cluster)].representative_point()
                cluster_points = [source]
            records.extend((point.x, point.y, cluster) for point in cluster_points)
        if not records:
            return None
        # Coincident points with different labels cannot be separated by any
        # polygon boundary, rectangular or otherwise.
        coordinate_labels = defaultdict(set)
        for x_value, y_value, cluster in records:
            coordinate_labels[(round(x_value, 6), round(y_value, 6))].add(cluster)
        if any(len(values) > 1 for values in coordinate_labels.values()):
            return None

        leaves = []

        def impurity(counts, total):
            if total <= 0:
                return 0.0
            return total * (
                1.0 - sum((amount / total) ** 2 for amount in counts.values())
            )

        def recurse(indices, bounds, depth=0):
            labels = {records[index][2] for index in indices}
            if len(labels) == 1:
                leaves.append((bounds, next(iter(labels))))
                return True
            if depth >= 64:
                return False
            bx0, by0, bx1, by1 = bounds
            choices = []
            relaxed_choices = []
            for axis in (0, 1):
                ordered = sorted(indices, key=lambda index: records[index][axis])
                total_counts = Counter(records[index][2] for index in ordered)
                left_counts = Counter()
                for position in range(len(ordered) - 1):
                    current = ordered[position]
                    left_counts[records[current][2]] += 1
                    current_value = records[current][axis]
                    next_value = records[ordered[position + 1]][axis]
                    if next_value - current_value <= 1e-8:
                        continue
                    threshold = (current_value + next_value) / 2.0
                    left_size = position + 1
                    right_size = len(ordered) - left_size
                    right_counts = total_counts - left_counts
                    score = (
                        impurity(left_counts, left_size)
                        + impurity(right_counts, right_size),
                        int(len(left_counts) > 1) + int(len(right_counts) > 1),
                        abs(left_size - right_size),
                        -(next_value - current_value),
                    )
                    choice = (score, axis, threshold, ordered[:left_size], ordered[left_size:])
                    relaxed_choices.append(choice)
                    width_ok = (
                        threshold - bx0 >= minimum_width
                        and bx1 - threshold >= minimum_width
                        if axis == 0
                        else threshold - by0 >= minimum_width
                        and by1 - threshold >= minimum_width
                    )
                    if width_ok:
                        choices.append(choice)
            candidates = choices or relaxed_choices
            if not candidates:
                return False
            _, axis, threshold, left, right = min(candidates, key=lambda item: item[0])
            if axis == 0:
                left_bounds = (bx0, by0, threshold, by1)
                right_bounds = (threshold, by0, bx1, by1)
            else:
                left_bounds = (bx0, by0, bx1, threshold)
                right_bounds = (bx0, threshold, bx1, by1)
            return recurse(left, left_bounds, depth + 1) and recurse(
                right, right_bounds, depth + 1
            )

        all_indices = list(range(len(records)))
        if not recurse(all_indices, (minx, miny, maxx, maxy)):
            return None
        assigned = defaultdict(list)
        for bounds, cluster in leaves:
            cell = box(*bounds).intersection(combined)
            if not cell.is_empty and cell.area > 1e-6:
                assigned[cluster].append(cell)
        raw = {
            cluster: unary_union(assigned[cluster])
            for cluster in clusters
            if assigned[cluster]
        }
        if len(raw) != len(clusters):
            return None

        def parts_of(geometry):
            return (
                list(geometry.geoms)
                if geometry.geom_type == "MultiPolygon"
                else [geometry]
            )

        def protected_parts(cluster, geometry):
            return [
                part
                for part in parts_of(geometry)
                if any(
                    part.covers(point)
                    for point in points_by_cluster.get(cluster, [])
                )
            ]

        # Connect separated point-bearing blocks with a broad rectangular
        # corridor. Unlike a panhandle copied from the source polygon, this
        # bridge is never narrower than the configured block width.
        for cluster in clusters:
            for _attempt in range(8):
                protected = protected_parts(cluster, raw[cluster])
                if len(protected) <= 1:
                    break
                base = max(protected, key=lambda part: part.area)
                other = min(
                    (part for part in protected if not part.equals(base)),
                    key=lambda part: part.distance(base),
                )
                start_point, end_point = nearest_points(base, other)
                sx, sy = start_point.x, start_point.y
                ex, ey = end_point.x, end_point.y
                paths = [
                    [(sx, sy), (ex, sy), (ex, ey)],
                    [(sx, sy), (sx, ey), (ex, ey)],
                ]
                for fraction in (0.25, 0.5, 0.75):
                    middle_x = sx + (ex - sx) * fraction
                    middle_y = sy + (ey - sy) * fraction
                    paths.extend(
                        [
                            [(sx, sy), (middle_x, sy), (middle_x, ey), (ex, ey)],
                            [(sx, sy), (sx, middle_y), (ex, middle_y), (ex, ey)],
                        ]
                    )
                valid_bridges = []
                before_components = len(protected)
                for path in paths:
                    cleaned = [path[0]]
                    for coordinate in path[1:]:
                        if coordinate != cleaned[-1]:
                            cleaned.append(coordinate)
                    if len(cleaned) < 2:
                        continue
                    corridor = LineString(cleaned).buffer(
                        minimum_width / 2.0,
                        cap_style="square",
                        join_style="mitre",
                    ).intersection(combined)
                    tentative = {}
                    for candidate_cluster in clusters:
                        tentative[candidate_cluster] = (
                            unary_union([raw[candidate_cluster], corridor])
                            if candidate_cluster == cluster
                            else raw[candidate_cluster].difference(corridor)
                        )
                    if any(
                        geometry.is_empty or not geometry.is_valid
                        for geometry in tentative.values()
                    ):
                        continue
                    if any(
                        any(
                            not tentative[candidate_cluster].covers(point)
                            for point in points_by_cluster.get(candidate_cluster, [])
                        )
                        for candidate_cluster in clusters
                    ):
                        continue
                    if len(protected_parts(cluster, tentative[cluster])) >= before_components:
                        continue
                    if any(
                        len(protected_parts(candidate_cluster, tentative[candidate_cluster])) > 1
                        for candidate_cluster in clusters
                        if candidate_cluster != cluster
                    ):
                        continue
                    overlap_area = corridor.difference(raw[cluster]).area
                    valid_bridges.append((overlap_area, len(cleaned), tentative))
                if not valid_bridges:
                    feedback.pushInfo(
                        "Volledig rechthoekige blokverdeling overgeslagen: de "
                        f"losse delen van {cluster} kunnen niet met een brede, "
                        "aansluitingsvrije blokverbinding worden gekoppeld."
                    )
                    return None
                _, _, raw = min(valid_bridges, key=lambda item: item[:2])
            if len(protected_parts(cluster, raw[cluster])) > 1:
                return None

        kept = {}
        orphans = []
        for cluster in clusters:
            geometry = raw[cluster]
            parts = parts_of(geometry)
            if geometry.geom_type not in ("Polygon", "MultiPolygon"):
                return None
            protected = protected_parts(cluster, geometry)
            if len(parts) > 1 and len(protected) > 1:
                feedback.pushInfo(
                    "Volledig rechthoekige blokverdeling overgeslagen: cluster "
                    f"{cluster} heeft aansluitingen in meerdere losse blokken."
                )
                return None
            main = protected[0] if protected else max(parts, key=lambda part: part.area)
            kept[cluster] = main
            orphans.extend((cluster, part) for part in parts if not part.equals(main))

        # Clipped leaf rectangles can leave point-free fragments at a concave
        # plangebied edge. Give such a fragment to the neighbour with which it
        # shares the longest edge; this removes an exclave without moving any
        # connection or changing the total covered area.
        for source_cluster, orphan in sorted(
            orphans, key=lambda item: item[1].area, reverse=True
        ):
            candidates = [cluster for cluster in clusters if cluster != source_cluster]
            target = min(
                candidates,
                key=lambda cluster: (
                    -orphan.boundary.intersection(kept[cluster].boundary).length,
                    orphan.distance(kept[cluster]),
                ),
            )
            kept[target] = unary_union([kept[target], orphan])

        result = []
        for cluster in clusters:
            geometry = kept[cluster]
            parts = (
                list(geometry.geoms)
                if geometry.geom_type == "MultiPolygon"
                else [geometry]
            )
            if geometry.geom_type not in ("Polygon", "MultiPolygon") or len(parts) != 1:
                feedback.pushInfo(
                    "Volledig rechthoekige blokverdeling overgeslagen: het "
                    f"herverdelen van randfragmenten maakt {cluster} niet aaneengesloten."
                )
                return None
            result.append(geometry)
        return result

    def processAlgorithm(self, parameters, context, feedback):
        areas = self.parameterAsVectorLayer(parameters, self.GEBIEDEN, context)
        connections = self.parameterAsVectorLayer(parameters, self.AANSLUITINGEN, context)
        area_field = self.parameterAsString(parameters, self.GEBIED_CLUSTER, context)
        connection_field = self.parameterAsString(
            parameters, self.AANSLUITING_CLUSTER, context
        )
        max_tolerance = self.parameterAsDouble(
            parameters, self.MAX_TOLERANTIE_M, context
        )
        right_angles = self.parameterAsBoolean(
            parameters, self.RECHTE_HOEKEN, context
        )
        minimum_width = self.parameterAsDouble(
            parameters, self.MIN_BREEDTE_M, context
        )
        junction_tolerance = self.parameterAsDouble(
            parameters, self.KNOOP_AFSCHUINING_M, context
        )
        if areas is None or connections is None:
            raise QgsProcessingException("De gebieden- of aansluitingenlaag ontbreekt.")
        if areas.fields().lookupField(area_field) < 0:
            raise QgsProcessingException(f"Kolom '{area_field}' ontbreekt in de gebiedenlaag.")
        if connections.fields().lookupField(connection_field) < 0:
            raise QgsProcessingException(
                f"Kolom '{connection_field}' ontbreekt in de aansluitingenlaag."
            )

        from shapely import coverage_is_valid, coverage_simplify, from_wkb

        features = [feature for feature in areas.getFeatures() if feature.hasGeometry()]
        if not features:
            raise QgsProcessingException("De clustergebiedenlaag is leeg.")
        shapes = [from_wkb(bytes(feature.geometry().asWkb())) for feature in features]
        clusters = [self._cluster_text(feature[area_field]) for feature in features]
        if any(not cluster for cluster in clusters):
            raise QgsProcessingException("Ieder clustergebied moet een geldige clusterwaarde hebben.")
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
            points_by_cluster[cluster].append(from_wkb(bytes(point_geometry.asWkb())))

        coverage_valid = bool(coverage_is_valid(shapes))
        if not coverage_valid:
            feedback.pushInfo(
                "Kleine overlap/gaten in de brongebieden topologisch herstellen…"
            )
            shapes = self._repair_coverage(shapes, clusters, points_by_cluster)

        if not self._valid_result(shapes, clusters, points_by_cluster):
            raise QgsProcessingException(
                "Minstens een aansluiting ligt al buiten het brongebied van zijn cluster. "
                "Corrigeer eerst de gewone clustergebieden."
            )

        feedback.pushInfo("Grootste veilige vereenvoudigingstolerantie zoeken…")
        best_shapes = shapes
        best_tolerance = 0.0
        low = 0.0
        high = float(max_tolerance)
        for iteration in range(14):
            if feedback.isCanceled():
                break
            tolerance = high if iteration == 0 else (low + high) / 2.0
            try:
                candidate = list(coverage_simplify(shapes, tolerance))
            except Exception:
                candidate = []
            if candidate and self._valid_result(candidate, clusters, points_by_cluster):
                best_shapes = candidate
                best_tolerance = tolerance
                low = tolerance
            else:
                high = tolerance
            feedback.setProgress(min(90, 5 + int((iteration + 1) * 80 / 14)))
            if high - low < 0.01:
                break

        orthogonal_converted = 0
        orthogonal_skipped = 0
        if right_angles:
            feedback.pushInfo(
                "Interne grenzen met zo weinig mogelijk 90°-hoeken opbouwen…"
            )
            orthogonal_shapes, orthogonal_converted, orthogonal_skipped = (
                self._orthogonalize_boundaries(
                    best_shapes, clusters, points_by_cluster, feedback
                )
            )
            if not self._valid_result(
                orthogonal_shapes, clusters, points_by_cluster
            ):
                feedback.pushInfo(
                    "Kleine numerieke overlap langs de rechte grenzen herstellen…"
                )
                orthogonal_shapes = self._repair_coverage(
                    orthogonal_shapes, clusters, points_by_cluster
                )
            if self._valid_result(orthogonal_shapes, clusters, points_by_cluster):
                best_shapes = orthogonal_shapes
            else:
                feedback.pushWarning(
                    "De rechte-hoekvariant was niet volledig topologisch geldig; "
                    "de veilige gewone vereenvoudiging wordt gebruikt."
                )
                orthogonal_converted = 0

        block_partition_used = False
        if right_angles and minimum_width > 0.0:
            feedback.pushInfo(
                "Volledig rechthoekige blokverdeling vanuit aansluitingen zoeken…"
            )
            rectangular_shapes = self._rectangular_partition(
                best_shapes,
                clusters,
                points_by_cluster,
                minimum_width,
                feedback,
            )
            if rectangular_shapes is not None and self._valid_result(
                rectangular_shapes, clusters, points_by_cluster
            ):
                best_shapes = rectangular_shapes
                block_partition_used = True
            else:
                feedback.pushInfo(
                    "Volledig rechthoekige blokken zijn voor deze puntverdeling "
                    "niet zonder exclaves mogelijk; compacte 90°-gebieden gebruiken."
                )

        panhandle_cells = 0
        if right_angles and minimum_width > 0.0:
            feedback.pushInfo(
                f"Smalle uitlopers onder {minimum_width:.1f} m verwijderen en "
                "compacte blokgebieden maken…"
            )
            compact_working = list(best_shapes)
            compact_failed = False
            for _pass in range(4):
                compact_shapes, changed_cells = self._remove_panhandles(
                    compact_working,
                    clusters,
                    points_by_cluster,
                    minimum_width,
                    feedback,
                )
                if not changed_cells:
                    break
                compact_shapes, compact_right, compact_skipped = (
                    self._orthogonalize_boundaries(
                        compact_shapes, clusters, points_by_cluster, feedback
                    )
                )
                orthogonal_converted += compact_right
                orthogonal_skipped += compact_skipped
                if not self._valid_result(
                    compact_shapes, clusters, points_by_cluster
                ):
                    compact_shapes = self._repair_coverage(
                        compact_shapes, clusters, points_by_cluster
                    )
                if not self._valid_result(
                    compact_shapes, clusters, points_by_cluster
                ):
                    compact_failed = True
                    break
                compact_working = compact_shapes
                panhandle_cells += changed_cells
            if compact_failed:
                panhandle_cells = 0
                feedback.pushWarning(
                    "De compacte blokvariant was niet volledig veilig; de "
                    "topologisch rechte gebieden blijven behouden."
                )
            else:
                best_shapes = compact_working

        junction_count = 0
        junction_removed = 0
        junction_diagonals = 0
        boundary_used_tolerance = 0.0
        if right_angles and junction_tolerance > 0.0:
            feedback.pushInfo(
                "Alle gedeelde grenzen gezamenlijk vereenvoudigen en exact noden…"
            )
            (
                best_shapes,
                junction_count,
                junction_removed,
                junction_diagonals,
                boundary_used_tolerance,
            ) = self._simplify_shared_boundaries_global(
                best_shapes,
                clusters,
                points_by_cluster,
                junction_tolerance,
                feedback,
            )

        fields = QgsFields(areas.fields())
        tolerance_index = fields.lookupField("Simpl_m")
        if tolerance_index < 0:
            fields.append(QgsField("Simpl_m", QVariant.Double, len=12, prec=2))
            tolerance_index = fields.lookupField("Simpl_m")
        vertex_index = fields.lookupField("Vertices")
        if vertex_index < 0:
            fields.append(QgsField("Vertices", QVariant.Int))
            vertex_index = fields.lookupField("Vertices")
        block_index = fields.lookupField("Blok_m")
        if block_index < 0:
            fields.append(QgsField("Blok_m", QVariant.Double, len=12, prec=2))
            block_index = fields.lookupField("Blok_m")
        junction_index = fields.lookupField("Knoop_m")
        if junction_index < 0:
            fields.append(QgsField("Knoop_m", QVariant.Double, len=12, prec=2))
            junction_index = fields.lookupField("Knoop_m")
        sink, destination = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.multiType(areas.wkbType()),
            areas.crs(),
        )
        if sink is None:
            raise QgsProcessingException("De uitvoerlaag kon niet worden gemaakt.")
        original_vertices = 0
        output_vertices = 0
        for feature, shape in zip(features, best_shapes):
            output = QgsFeature(fields)
            output.setAttributes([*feature.attributes(), *([None] * (len(fields) - len(areas.fields())))])
            geometry = QgsGeometry()
            geometry.fromWkb(shape.wkb)
            if not QgsWkbTypes.isMultiType(geometry.wkbType()):
                geometry.convertToMultiType()
            output.setGeometry(geometry)
            values = output.attributes()
            values[tolerance_index] = round(best_tolerance, 2)
            values[vertex_index] = _vertex_count(geometry)
            values[block_index] = round(minimum_width if right_angles else 0.0, 2)
            values[junction_index] = round(
                junction_tolerance if right_angles else 0.0, 2
            )
            output.setAttributes(values)
            if not sink.addFeature(output, QgsFeatureSink.FastInsert):
                raise QgsProcessingException("Een vereenvoudigd gebied kon niet worden opgeslagen.")
            original_vertices += _vertex_count(feature.geometry())
            output_vertices += values[vertex_index]
        feedback.setProgress(100)
        shared_relations, right_relations, diagonal_segments = self._boundary_stats(
            best_shapes
        )
        feedback.pushInfo(
            f"Veilige tolerantie: {best_tolerance:.2f} m; hoekpunten: "
            f"{original_vertices} → {output_vertices}; rechte gedeelde grenzen: "
            f"{right_relations}/{shared_relations}; diagonale interne segmenten: "
            f"{diagonal_segments}; "
            f"rechthoekige blokpartitionering: "
            f"{'ja' if block_partition_used else 'veilige compacte variant'}; "
            f"herverdeelde smalle deelvlakken: {panhandle_cells}; "
            f"exact genode 3+-clusterpunten: {junction_count}; verwijderde "
            f"grenshoekpunten: {junction_removed}; schuine segmenten: "
            f"{junction_diagonals}; gebruikte eindtolerantie: "
            f"{boundary_used_tolerance:.2f} m."
        )
        return {self.OUTPUT: destination}
