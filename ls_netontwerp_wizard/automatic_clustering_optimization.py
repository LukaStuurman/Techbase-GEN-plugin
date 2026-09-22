from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _qgis_thread_budget(context=None) -> tuple[int, int, int | None]:
    """Return (logical processors, usable QGIS budget, explicit context limit)."""
    logical = max(1, os.cpu_count() or 1)
    limits = [logical, 64]
    context_limit = None
    try:
        context_limit = _positive_int(context.maximumThreads()) if context is not None else None
    except (AttributeError, RuntimeError, TypeError):
        context_limit = None
    if context_limit:
        limits.append(context_limit)
    try:
        from qgis.core import QgsApplication

        app_limit = _positive_int(QgsApplication.maxThreads())
    except (ImportError, AttributeError, RuntimeError, TypeError):
        app_limit = None
    if app_limit:
        limits.append(app_limit)
    return logical, max(1, min(limits)), context_limit


def _install_qgis_thread_budget(workflow_runner_class) -> None:
    original = workflow_runner_class._configure_cpu_threads
    if getattr(original, "_ls_auto_cluster_optimized", False):
        return

    def configured(self):
        logical, qgis_budget, _context_limit = _qgis_thread_budget(
            getattr(self, "context", None)
        )
        if self.v.get("auto_cpu_threads", True):
            # Keep one logical processor free where possible, but never exceed
            # QGIS' own Processing/application thread budget.
            preferred = max(1, logical - 1)
            threads = min(preferred, qgis_budget)
        else:
            requested = max(1, int(self.v.get("cpu_threads", 1)))
            threads = min(requested, logical, qgis_budget, 64)
        threads = max(1, int(threads))
        self.v["effective_cpu_threads"] = threads
        for variable in (
            "LS_NETONTWERP_THREADS",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            os.environ[variable] = str(threads)
        self.progress(
            0,
            f"CPU-versnelling: {threads} thread(s); QGIS-budget {qgis_budget}, "
            f"systeem {logical} logisch",
        )
        return threads

    configured._ls_auto_cluster_optimized = True
    workflow_runner_class._configure_cpu_threads = configured


def _install_engine_loader_patch(workflow_runner_class) -> None:
    original = workflow_runner_class._algorithm
    if getattr(original, "_ls_auto_cluster_optimized", False):
        return

    def algorithm(self, key):
        instance = original(self, key)
        if key != "clustering" or not hasattr(instance, "_load_engine"):
            return instance
        original_loader = instance._load_engine

        def optimized_loader():
            engine = original_loader()
            install_engine_optimizations(engine)
            return engine

        instance._load_engine = optimized_loader
        return instance

    algorithm._ls_auto_cluster_optimized = True
    workflow_runner_class._algorithm = algorithm


def install_workflow_optimizations(workflow_runner_class) -> None:
    """Install safe automatic-clustering accelerations into the wizard runner."""
    if getattr(workflow_runner_class, "_ls_auto_cluster_optimizations_installed", False):
        return
    _install_qgis_thread_budget(workflow_runner_class)
    _install_engine_loader_patch(workflow_runner_class)
    workflow_runner_class._ls_auto_cluster_optimizations_installed = True


def _install_distance_cache(engine) -> None:
    """Cache compact source-to-demand distances for repeated automatic trials."""
    if getattr(engine.network_distance_matrix, "_ls_compact_cache", False):
        return

    cache: dict[tuple[object, bytes, int], np.ndarray] = {}
    cache_lock = Lock()

    def target_signature(target_indices: np.ndarray) -> bytes:
        values = np.ascontiguousarray(target_indices, dtype=np.int64)
        return values.tobytes()

    def cached_network_distance_matrix(adjacency, source_indices, target_indices):
        sources = np.asarray(source_indices, dtype=int).reshape(-1)
        targets = np.asarray(target_indices, dtype=int).reshape(-1)
        if len(sources) == 0:
            return np.empty((len(targets), 0), dtype=float)

        try:
            data_pointer = int(adjacency.data.__array_interface__["data"][0])
        except (AttributeError, KeyError, TypeError):
            data_pointer = id(adjacency)
        graph_key = (
            id(adjacency),
            data_pointer,
            tuple(int(value) for value in adjacency.shape),
            int(adjacency.nnz),
        )
        target_key = target_signature(targets)
        with cache_lock:
            missing = [
                int(source)
                for source in sources
                if (graph_key, target_key, int(source)) not in cache
            ]

        if missing:
            # Dijkstra returns one full graph row per source. Keep peak memory
            # bounded and retain only the demand-node columns needed by the
            # clustering optimizer.
            node_count = max(1, int(adjacency.shape[0]))
            bytes_per_source = max(8, node_count * 8)
            max_batch = max(1, min(len(missing), (192 * 1024 * 1024) // bytes_per_source))
            for start in range(0, len(missing), max_batch):
                batch = missing[start : start + max_batch]
                calculated = dijkstra(
                    adjacency,
                    directed=False,
                    indices=np.asarray(batch, dtype=int),
                    return_predecessors=False,
                )
                calculated = np.asarray(calculated, dtype=float)
                if calculated.ndim == 1:
                    calculated = calculated[None, :]
                compact = np.asarray(calculated[:, targets], dtype=float)
                with cache_lock:
                    for source, row in zip(batch, compact):
                        cache.setdefault(
                            (graph_key, target_key, int(source)), row.copy()
                        )

        with cache_lock:
            columns = [
                cache[(graph_key, target_key, int(source))] for source in sources
            ]
        return np.column_stack(columns)

    cached_network_distance_matrix._ls_compact_cache = True
    cached_network_distance_matrix._ls_cache = cache
    engine.network_distance_matrix = cached_network_distance_matrix


def _make_greedy_solver(engine):
    def solve_greedy_voronoi_connected_assignment(
        adjacency,
        node_list,
        unit_node_indices,
        loads,
        existing_source_indices,
        candidate_source_indices,
        existing_capacities,
        new_capacity,
        regular_node_indices,
        graph_component_by_node_index,
        preferred_candidate_indices=None,
    ):
        """Memory-lean exact equivalent of the automatic Voronoi fallback.

        Candidate scans operate only on source-to-demand distances. Full graph
        ownership is constructed once, after the final candidate set is known.
        Every capacity, route and source-node ownership rule remains enforced.
        """
        node_xy = np.asarray(node_list, dtype=float)
        unit_node_indices_arr = np.asarray(unit_node_indices, dtype=int)
        loads_arr = np.asarray(loads, dtype=float)
        existing_source_indices_arr = np.asarray(existing_source_indices, dtype=int)
        existing_capacities_arr = np.asarray(existing_capacities, dtype=float)
        regular_node_indices_arr = np.asarray(regular_node_indices, dtype=int)
        graph_components = np.asarray(graph_component_by_node_index, dtype=int)

        regular_by_component: dict[int, np.ndarray] = {}
        regular_tree_by_component: dict[int, cKDTree] = {}
        for component_index in np.unique(graph_components):
            indices = regular_node_indices_arr[
                graph_components[regular_node_indices_arr] == component_index
            ]
            if len(indices):
                regular_by_component[int(component_index)] = indices
                regular_tree_by_component[int(component_index)] = cKDTree(node_xy[indices])

        units_by_graph_node: dict[int, np.ndarray] = {}
        for graph_index in np.unique(unit_node_indices_arr):
            units_by_graph_node[int(graph_index)] = np.flatnonzero(
                unit_node_indices_arr == int(graph_index)
            )

        last_overloaded = None
        last_assignment = None
        last_unit_distances = None

        def compact_distances(source_indices):
            return engine.network_distance_matrix(
                adjacency,
                np.asarray(source_indices, dtype=int),
                unit_node_indices_arr,
            )

        def build_node_cluster(source_indices, biases):
            source_indices = np.asarray(source_indices, dtype=int)
            node_count = int(adjacency.shape[0])
            best_distance = np.full(node_count, np.inf, dtype=float)
            owner = np.full(node_count, -1, dtype=int)
            # Keep full-graph Dijkstra peak memory around 192 MiB. This work is
            # done only once for the finally accepted source set.
            bytes_per_source = max(8, node_count * 8)
            batch_size = max(
                1,
                min(len(source_indices), (192 * 1024 * 1024) // bytes_per_source),
            )
            for start in range(0, len(source_indices), batch_size):
                batch = source_indices[start : start + batch_size]
                distances = dijkstra(
                    adjacency,
                    directed=False,
                    indices=batch,
                    return_predecessors=False,
                )
                distances = np.asarray(distances, dtype=float)
                if distances.ndim == 1:
                    distances = distances[None, :]
                for offset, row in enumerate(distances):
                    station_index = start + offset
                    adjusted = row + float(biases[station_index])
                    better = adjusted < best_distance
                    best_distance[better] = adjusted[better]
                    owner[better] = station_index
            # Preserve the original fallback's hard root ownership override.
            for station_index, graph_index in enumerate(source_indices):
                owner[int(graph_index)] = station_index
            return owner

        def evaluate(selected_candidates, record_failure=True, build_full_ownership=False):
            nonlocal last_overloaded, last_assignment, last_unit_distances
            source_indices = np.concatenate(
                [
                    existing_source_indices_arr,
                    np.asarray(
                        [candidate_source_indices[index] for index in selected_candidates],
                        dtype=int,
                    ),
                ]
            )
            if len(np.unique(source_indices)) != len(source_indices):
                return None
            unit_distance_matrix = compact_distances(source_indices)
            if np.any(~np.isfinite(unit_distance_matrix).any(axis=1)):
                return None
            capacities = np.concatenate(
                [
                    existing_capacities_arr,
                    np.full(len(selected_candidates), new_capacity, dtype=float),
                ]
            )
            biases = np.zeros(len(capacities), dtype=float)
            assignment = np.zeros(len(loads_arr), dtype=int)
            unit_distances = np.zeros(len(loads_arr), dtype=float)
            station_loads = np.zeros(len(capacities), dtype=float)
            unit_range = np.arange(len(loads_arr))

            for _balance_iteration in range(10000):
                adjusted = unit_distance_matrix + biases[None, :]
                assignment = np.argmin(adjusted, axis=1)
                unit_distances = unit_distance_matrix[unit_range, assignment]
                if np.any(~np.isfinite(unit_distances)) or np.any(
                    unit_distances > engine.MAX_ROUTE_M + 1e-7
                ):
                    break
                station_loads = np.bincount(
                    assignment, weights=loads_arr, minlength=len(capacities)
                )
                overloaded = np.flatnonzero(station_loads > capacities + 1e-6)
                if not len(overloaded):
                    # The full weighted Voronoi ownership differs from demand
                    # assignment only where a source root is forcibly owned by
                    # itself. Check those demand nodes cheaply during scans.
                    for station_index, graph_index in enumerate(source_indices):
                        root_units = units_by_graph_node.get(int(graph_index))
                        if root_units is not None and np.any(
                            assignment[root_units] != station_index
                        ):
                            return None
                    node_cluster = None
                    if build_full_ownership:
                        node_cluster = build_node_cluster(source_indices, biases)
                        if np.any(node_cluster[unit_node_indices_arr] != assignment):
                            return None
                    utilization = station_loads / capacities
                    distance_cost = float(
                        np.sum((loads_arr + 0.5) * unit_distances)
                    )
                    target_cost = float(
                        np.sum(np.abs(utilization - engine.TARGET_UTILIZATION))
                        * engine.TARGET_UTILIZATION_PENALTY
                    )
                    return (
                        assignment,
                        node_cluster,
                        capacities,
                        unit_distances,
                        distance_cost + target_cost,
                    )

                overload_ratio = station_loads[overloaded] / capacities[overloaded]
                station_index = int(overloaded[int(np.argmax(overload_ratio))])
                members = np.flatnonzero(assignment == station_index)
                if not len(members):
                    break
                alternative_cost = adjusted[members].copy()
                alternative_cost[:, station_index] = np.inf
                alternative_station = np.argmin(alternative_cost, axis=1)
                alternative_distance = unit_distance_matrix[
                    members, alternative_station
                ]
                transferable = np.isfinite(alternative_distance) & (
                    alternative_distance <= engine.MAX_ROUTE_M + 1e-7
                )
                if not np.any(transferable):
                    break
                margins = (
                    alternative_cost[np.arange(len(members)), alternative_station]
                    - adjusted[members, station_index]
                )
                margins[~transferable] = np.inf
                required_increase = float(np.min(margins))
                if not np.isfinite(required_increase):
                    break
                biases[station_index] += max(0.0, required_increase) + 0.05
                # A common shift changes no argmin. Keep values numerically
                # bounded only when every bias has become positive.
                minimum_bias = float(np.min(biases))
                if minimum_bias > 0.0:
                    biases -= minimum_bias

            if record_failure:
                last_overloaded = np.flatnonzero(
                    station_loads > capacities + 1e-6
                )
                last_assignment = assignment
                last_unit_distances = unit_distances
            return None

        selected = (
            list(preferred_candidate_indices)
            if preferred_candidate_indices is not None
            else list(range(len(candidate_source_indices)))
        )
        current = evaluate(selected)
        added_for_capacity = 0
        while current is None and last_overloaded is not None:
            if added_for_capacity >= 50:
                break
            existing_sources = set(int(value) for value in existing_source_indices_arr)
            candidate_sources = set(int(value) for value in candidate_source_indices)
            chosen_graph_index = None
            for overloaded_station in last_overloaded:
                members = np.flatnonzero(last_assignment == int(overloaded_station))
                scores = (last_unit_distances[members] + 10.0) * (
                    loads_arr[members] + 0.5
                )
                for member in members[np.argsort(scores)[::-1]]:
                    unit_graph_index = int(unit_node_indices_arr[int(member)])
                    component_index = int(graph_components[unit_graph_index])
                    component_regular = regular_by_component.get(component_index)
                    component_tree = regular_tree_by_component.get(component_index)
                    if component_regular is None or component_tree is None:
                        continue
                    _distance, local_indices = component_tree.query(
                        node_xy[unit_graph_index],
                        k=min(25, len(component_regular)),
                    )
                    for local_index in np.atleast_1d(local_indices):
                        graph_index = int(component_regular[int(local_index)])
                        if graph_index in existing_sources or graph_index in candidate_sources:
                            continue
                        chosen_graph_index = graph_index
                        break
                    if chosen_graph_index is not None:
                        break
                if chosen_graph_index is not None:
                    break
            if chosen_graph_index is None:
                break
            candidate_source_indices.append(chosen_graph_index)
            selected.append(len(candidate_source_indices) - 1)
            added_for_capacity += 1
            engine.log(
                f"Capaciteitskandidaat {added_for_capacity} toegevoegd op "
                f"kabelknoop {node_list[chosen_graph_index]}."
            )
            last_overloaded = None
            last_assignment = None
            last_unit_distances = None
            current = evaluate(selected)
        if current is None:
            raise RuntimeError(
                "Ook met alle beschikbare kandidaatstations ontstaat geen "
                "capaciteitsgeldige kabel-Voronoi-verdeling"
            )

        def evaluate_removal(candidate_index):
            trial = [index for index in selected if index != candidate_index]
            evaluated = evaluate(trial, record_failure=False)
            if evaluated is not None:
                return (evaluated[4], candidate_index, trial, evaluated)
            return None

        pending_removals: list[int] = []
        existing_count = len(existing_source_indices_arr)
        while selected:
            # Empty candidates can usually be discarded together. The same full
            # feasibility evaluation still validates the batch, so no rule is
            # relaxed and interacting candidates fall back to the normal scan.
            assignment_now = current[0]
            station_counts = np.bincount(
                assignment_now,
                minlength=existing_count + len(selected),
            )
            empty_candidates = [
                selected[position]
                for position in range(len(selected))
                if station_counts[existing_count + position] == 0
            ]
            if empty_candidates:
                empty_set = set(empty_candidates)
                trial = [index for index in selected if index not in empty_set]
                evaluated = evaluate(trial, record_failure=False)
                if evaluated is not None:
                    selected = trial
                    current = evaluated
                    pending_removals = []
                    engine.log(
                        f"{len(empty_candidates)} lege automatische "
                        "stationskandidaat/kandidaten in één controle verwijderd."
                    )
                    continue

            if pending_removals:
                ordered_pending = [
                    index for index in pending_removals if index in selected
                ]
                carried_valid = []
                carry_workers = min(
                    max(1, int(engine.CPU_THREADS)), len(ordered_pending), 24
                )
                if carry_workers > 1:
                    with ThreadPoolExecutor(max_workers=carry_workers) as executor:
                        for result in executor.map(evaluate_removal, ordered_pending):
                            if result is not None:
                                carried_valid.append(result)
                else:
                    for candidate_index in ordered_pending:
                        result = evaluate_removal(candidate_index)
                        if result is not None:
                            carried_valid.append(result)
                if carried_valid:
                    ordered_carried = [
                        value[1]
                        for value in sorted(
                            carried_valid, key=lambda value: (value[0], value[1])
                        )
                    ]
                    accelerated_removed = []
                    batch_size = len(ordered_carried)
                    while batch_size >= 2:
                        trial_removed = set(ordered_carried[:batch_size])
                        trial = [
                            index for index in selected if index not in trial_removed
                        ]
                        evaluated = evaluate(trial, record_failure=False)
                        if evaluated is not None:
                            accelerated_removed = ordered_carried[:batch_size]
                            selected = trial
                            current = evaluated
                            break
                        batch_size //= 2
                    if not accelerated_removed:
                        _score, removed, selected, current = min(
                            carried_valid, key=lambda value: (value[0], value[1])
                        )
                        accelerated_removed = [removed]
                    removed_set = set(accelerated_removed)
                    pending_removals = [
                        index
                        for index in ordered_carried
                        if index not in removed_set and index in selected
                    ]
                    engine.log(
                        "Overbodige kabel-Voronoi-kandidaat/kandidaten via "
                        "versnelde herscan verwijderd: "
                        + ", ".join(
                            str(index + 1) for index in sorted(accelerated_removed)
                        )
                        + "."
                    )
                    continue
                pending_removals = []

            valid_removals = []
            removal_workers = min(
                max(1, int(engine.CPU_THREADS)), len(selected), 24
            )
            if removal_workers > 1 and len(selected) > 1:
                engine.log(
                    f"{len(selected)} onafhankelijke kandidaatcontroles met "
                    f"{removal_workers} CPU-threads uitvoeren..."
                )
                with ThreadPoolExecutor(max_workers=removal_workers) as executor:
                    futures = {
                        executor.submit(evaluate_removal, candidate_index): candidate_index
                        for candidate_index in selected
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        if result is not None:
                            valid_removals.append(result)
            else:
                for candidate_index in selected:
                    result = evaluate_removal(candidate_index)
                    if result is not None:
                        valid_removals.append(result)
            if not valid_removals:
                break

            ordered_removals = [
                value[1]
                for value in sorted(
                    valid_removals, key=lambda value: (value[0], value[1])
                )
            ]
            removed_batch = []
            batch_size = len(ordered_removals)
            while batch_size >= 2:
                trial_removed = set(ordered_removals[:batch_size])
                trial = [index for index in selected if index not in trial_removed]
                evaluated = evaluate(trial, record_failure=False)
                if evaluated is not None:
                    removed_batch = ordered_removals[:batch_size]
                    selected = trial
                    current = evaluated
                    break
                batch_size //= 2
            if not removed_batch:
                _score, removed, selected, current = min(
                    valid_removals, key=lambda value: (value[0], value[1])
                )
                removed_batch = [removed]
            removed_set = set(removed_batch)
            pending_removals = [
                index
                for index in ordered_removals
                if index not in removed_set and index in selected
            ]
            engine.log(
                "Overbodige kabel-Voronoi-kandidaat/kandidaten verwijderd: "
                + ", ".join(str(index + 1) for index in sorted(removed_batch))
                + "."
            )

        # Full node ownership is needed only for the final accepted candidate
        # set. Candidate trials have already checked the equivalent demand-node
        # ownership condition without materialising source x graph matrices.
        final_current = evaluate(
            selected, record_failure=False, build_full_ownership=True
        )
        if final_current is None or final_current[1] is None:
            raise RuntimeError(
                "De uiteindelijke kabel-Voronoi-verdeling kon niet worden bevestigd"
            )
        assignment, node_cluster, capacities, unit_distances, _score = final_current
        min_utilization = float(
            np.min(
                np.bincount(
                    assignment, weights=loads_arr, minlength=len(capacities)
                )
                / capacities
            )
        )
        engine.log(
            f"Kabel-Voronoi-terugval geldig met {len(selected)} nieuw(e) "
            "station(s); compacte afstandscache en eenmalige "
            "netwerkeigendomcontrole gebruikt."
        )
        return assignment, min_utilization, node_cluster, selected, unit_distances

    return solve_greedy_voronoi_connected_assignment


def _wrap_timed(engine, name: str, label: str) -> None:
    original = getattr(engine, name, None)
    if original is None or getattr(original, "_ls_timed", False):
        return

    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            engine.log(f"Snelheidsprofiel {label}: {elapsed:.2f} s")

    timed._ls_timed = True
    setattr(engine, name, timed)


def install_engine_optimizations(engine) -> None:
    """Patch only the pure NumPy/SciPy automatic-clustering calculation core."""
    if getattr(engine, "_LS_AUTO_CLUSTER_OPTIMIZED", False):
        return
    _install_distance_cache(engine)
    engine.solve_greedy_voronoi_connected_assignment = _make_greedy_solver(engine)
    engine.solve_greedy_voronoi_connected_assignment._ls_optimized = True
    for name, label in (
        ("solve_facility_selection", "stationskeuze MILP"),
        ("solve_fixed_assignment", "definitieve toedeling MILP"),
        ("solve_cable_connected_assignment", "kabelverbonden toedeling"),
        ("solve_greedy_voronoi_connected_assignment", "kabel-Voronoi terugval"),
        ("build_exclusive_routes", "exclusieve routes"),
    ):
        _wrap_timed(engine, name, label)
    engine._LS_AUTO_CLUSTER_OPTIMIZED = True
    engine.log(
        "Automatische clustering optimalisatie actief: QGIS-threadbudget, "
        "compacte netwerkafstandscache en memory-lean Voronoi-kandidaatscans."
    )
