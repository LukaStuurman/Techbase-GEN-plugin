from __future__ import annotations


def _as_polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [part for part in geometry.geoms if part.geom_type == "Polygon"]
    return []


def _extended_cut_line(line, distance):
    from shapely.geometry import LineString
    from shapely.ops import linemerge

    if line.geom_type == "MultiLineString":
        line = linemerge(line)
    if line.geom_type != "LineString" or len(line.coords) < 2:
        raise ValueError("Teken één doorlopende grenslijn met minimaal twee punten.")
    coordinates = list(line.coords)

    def extend(source, neighbour):
        dx = source[0] - neighbour[0]
        dy = source[1] - neighbour[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 1e-9:
            return source
        return (
            source[0] + dx / length * distance,
            source[1] + dy / length * distance,
        )

    coordinates[0] = extend(coordinates[0], coordinates[1])
    coordinates[-1] = extend(coordinates[-1], coordinates[-2])
    return LineString(coordinates)


def replace_shared_boundary(area_a_wkb, area_b_wkb, cut_wkb, points_a_wkb, points_b_wkb):
    """Return two polygons after replacing only their shared internal boundary.

    The outside of the union is kept exactly. The two returned pieces are
    assigned to A/B only when every supplied connection remains in its own area.
    """
    from shapely import from_wkb
    from shapely.geometry import Point
    from shapely.ops import split, unary_union

    area_a = from_wkb(bytes(area_a_wkb))
    area_b = from_wkb(bytes(area_b_wkb))
    cut = from_wkb(bytes(cut_wkb))
    if area_a.is_empty or area_b.is_empty or not area_a.is_valid or not area_b.is_valid:
        raise ValueError("De twee geselecteerde gebieden hebben geen geldige geometrie.")
    shared = area_a.boundary.intersection(area_b.boundary)
    if shared.length <= 0.001:
        raise ValueError("Selecteer precies twee gebieden met een echte gedeelde grens.")
    combined = unary_union([area_a, area_b])
    if combined.geom_type != "Polygon":
        raise ValueError("De geselecteerde gebieden vormen samen geen aaneengesloten vlak.")
    minx, miny, maxx, maxy = combined.bounds
    diagonal = max(((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5, 1.0)
    cut_coordinates = list(cut.coords) if cut.geom_type == "LineString" else []
    endpoints_on_boundary = (
        len(cut_coordinates) >= 2
        and combined.boundary.distance(Point(cut_coordinates[0])) <= 1e-7
        and combined.boundary.distance(Point(cut_coordinates[-1])) <= 1e-7
    )
    # Do not extend a divider which already terminates exactly on the outer
    # boundary. In a concave union a long extension can leave and re-enter the
    # area and accidentally split it into three or more pieces.
    cutter = cut if endpoints_on_boundary else _extended_cut_line(cut, diagonal * 3.0)
    pieces = _as_polygon_parts(split(combined, cutter))
    pieces = [piece for piece in pieces if piece.area > 0.001]
    if len(pieces) != 2:
        raise ValueError(
            "De getekende lijn verdeelt de twee gebieden niet in precies twee delen. "
            "Teken één eenvoudige grens van buitenrand naar buitenrand."
        )

    points_a = [from_wkb(bytes(value)) for value in points_a_wkb]
    points_b = [from_wkb(bytes(value)) for value in points_b_wkb]

    def contains_all(piece, points):
        return all(piece.covers(point) for point in points)

    mappings = []
    if contains_all(pieces[0], points_a) and contains_all(pieces[1], points_b):
        mappings.append((pieces[0], pieces[1]))
    if contains_all(pieces[1], points_a) and contains_all(pieces[0], points_b):
        mappings.append((pieces[1], pieces[0]))
    if not mappings:
        raise ValueError(
            "Door deze grens zou minstens één aansluiting buiten het gebied van "
            "zijn eigen cluster vallen. De wijziging is niet opgeslagen."
        )
    # When no connections distinguish the sides, preserve the greatest overlap
    # with the original pair so the cluster names do not unexpectedly swap.
    chosen = max(
        mappings,
        key=lambda pair: pair[0].intersection(area_a).area
        + pair[1].intersection(area_b).area,
    )
    if abs((chosen[0].area + chosen[1].area) - combined.area) > max(0.001, combined.area * 1e-9):
        raise ValueError("De nieuwe gebieden bedekken niet exact hetzelfde gezamenlijke vlak.")
    return chosen[0].wkb, chosen[1].wkb
