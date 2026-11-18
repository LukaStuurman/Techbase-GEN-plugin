"""Regressions for Scope color separation, stability and preservation."""
from scope_contrast_colors import choose_scope_colors, neighbour_graph, perceptual_distance


def test_contrast_next_to_each_other():
    groups = {f"S{x}-{y}": [(x * 60 + dx, y * 60 + dy)
                           for dx in (0, 15, 30) for dy in (0, 15, 30)]
              for x in range(3) for y in range(3)}
    base = {name: "#8ebbd4" for name in groups}
    out = choose_scope_colors(groups, base)
    graph = neighbour_graph(groups)
    for a, peers in graph.items():
        for b in peers:
            assert perceptual_distance(out[a], out[b]) >= 37, (a, b, out[a], out[b])
    assert out == choose_scope_colors(dict(reversed(list(groups.items()))), base)


def test_keep_distant_original_colors():
    groups = {"near-a": [(0, 0)], "near-b": [(10, 5)],
              "far-a": [(10000, 10000)], "far-b": [(10010, 10020)]}
    original = {"near-a": "#0072b2", "near-b": "#0072b2",
                "far-a": "#e69f00", "far-b": "#e69f00"}
    result = choose_scope_colors(groups, original)
    assert result["near-a"] != result["near-b"]
    assert result["far-a"] != result["far-b"]


def test_lone_station_and_invalid_colors():
    groups = {"s": [(100, 100)], "t": [(200, 200)], "empty": []}
    result = choose_scope_colors(groups, {"s": "#ff0000", "t": "invalid"})
    assert result["s"] == "#ff0000" or result["s"] in choose_scope_colors(groups, {"s": "#ff0000", "t": "invalid"}).values()
    assert len(result) == 3
    assert all(value.startswith("#") and len(value) == 7 for value in result.values())


def test_close_long_corridor():
    groups = {"a": [(x, 0) for x in range(0, 1500, 15)],
              "b": [(x, 30) for x in range(0, 1500, 15)],
              "c": [(x, 100) for x in range(0, 1500, 15)]}
    out = choose_scope_colors(groups, {key: "#3388aa" for key in groups})
    assert all(perceptual_distance(out[a], out[b]) >= 37
               for a, peers in neighbour_graph(groups).items() for b in peers)


if __name__ == "__main__":
    test_contrast_next_to_each_other()
    test_keep_distant_original_colors()
    test_lone_station_and_invalid_colors()
    test_close_long_corridor()
    print("SCOPE_CONTRAST_OK (adjacency, geometry, original style, stable ordering, lone station)")
