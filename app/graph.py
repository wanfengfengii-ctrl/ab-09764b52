"""Calibration graph with exact composition and cycle consistency checking.

Each directed calibration relation ``u -> v`` states that a reading ``x`` on
instrument ``u`` maps to ``y = a*x + b`` on instrument ``v`` with exact rational
``a`` (non-zero) and ``b``.

The graph is treated as a system of equations: every path between two
instruments must induce the same affine transform.  This module composes
transforms with :class:`fractions.Fraction` (never floating point) and detects a
contradiction on *any* cycle, even one unrelated to the requested source and
target, so that conflicting calibration evidence can never be hidden by path
selection or entry order.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional


@dataclass(frozen=True)
class Affine:
    """An exact affine transform ``y = slope * x + intercept``."""

    slope: Fraction
    intercept: Fraction

    def compose(self, other: "Affine") -> "Affine":
        """Return the transform that first applies ``self`` then ``other``.

        If ``z = other.slope*y + other.intercept`` and
        ``y = self.slope*x + self.intercept``, then::

            z = other.slope*self.slope*x
                + other.slope*self.intercept + other.intercept
        """
        return Affine(
            slope=other.slope * self.slope,
            intercept=other.slope * self.intercept + other.intercept,
        )

    def inverse(self) -> "Affine":
        """Invert the transform (valid because every slope is non-zero)."""
        return Affine(
            slope=Fraction(1, 1) / self.slope,
            intercept=-self.intercept / self.slope,
        )

    def apply(self, x: Fraction) -> Fraction:
        return self.slope * x + self.intercept

    def identity() -> "Affine":  # type: ignore[misc]
        return Affine(Fraction(1, 1), Fraction(0, 1))


class CalibrationConflict(ValueError):
    """Raised when calibration relations imply different exact transforms."""

    def __init__(self, cycle: tuple[str, ...]):
        self.cycle = cycle
        instruments = list(dict.fromkeys(cycle))
        self.instruments = instruments
        joined = " -> ".join(cycle)
        super().__init__(
            f"conflicting calibration evidence on cycle {joined}; "
            f"involved instruments: {', '.join(instruments)}"
        )


class CalibrationGraph:
    """Holds calibration relations and validates them as a whole."""

    MIN_INSTRUMENTS = 2
    MAX_INSTRUMENTS = 50
    MAX_RELATIONS = 100

    def __init__(self) -> None:
        self._adjacency: dict[str, list[tuple[str, Affine]]] = {}
        self._instruments: set[str] = set()

    @property
    def instruments(self) -> set[str]:
        return set(self._instruments)

    def add_instrument(self, instrument: str) -> None:
        self._instruments.add(instrument)
        self._adjacency.setdefault(instrument, [])

    def add_relation(self, source: str, target: str, transform: Affine) -> None:
        if transform.slope == 0:
            raise ValueError(f"relation {source} -> {target} has a zero slope and is not invertible")
        if source == target:
            raise ValueError(f"relation {source} -> {source} is a self-loop; calibrations must join two instruments")
        self.add_instrument(source)
        self.add_instrument(target)
        self._adjacency[source].append((target, transform))
        # The reverse edge carries the exact inverse relation, allowing every
        # undirected path to be walked in either direction.
        self._adjacency[target].append((source, transform.inverse()))

    # ------------------------------------------------------------------
    # Whole-graph validation: every cycle must close with the identity.
    # ------------------------------------------------------------------

    def check_consistency(self) -> None:
        """Verify that all paths between any pair agree exactly.

        Raises :class:`CalibrationConflict` naming the instruments on an
        offending cycle.  DFS order does not determine the answer: any
        spanning forest may be used because every non-tree edge is checked
        against it and the edge set is complete.
        """
        # transform_to_root[node]: node coords -> root coords
        transform_to_root: dict[str, Affine] = {}
        parent_edge: dict[str, tuple[str, Affine]] = {}
        visited: set[str] = set()

        def walk(start: str) -> None:
            root = start
            transform_to_root[root] = Affine.identity()
            stack: list[str] = [root]
            visited.add(root)
            while stack:
                node = stack.pop()
                node_to_root = transform_to_root[node]
                for neighbor, node_to_neighbor in self._adjacency[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        parent_edge[neighbor] = (node, node_to_neighbor)
                        # neighbor coords -> node coords (inverse edge),
                        # then node coords -> root coords.
                        transform_to_root[neighbor] = node_to_neighbor.inverse().compose(
                            node_to_root
                        )
                        stack.append(neighbor)
                    else:
                        neighbor_to_root = transform_to_root[neighbor]
                        # Going node -> neighbor then neighbor -> root must
                        # equal node -> root, otherwise this cycle disagrees.
                        via_neighbor = node_to_neighbor.compose(neighbor_to_root)
                        if via_neighbor != node_to_root:
                            cycle = self._cycle_path(node, neighbor, parent_edge, root)
                            raise CalibrationConflict(cycle)

        for instrument in self._adjacency:
            if instrument not in visited:
                walk(instrument)

    @staticmethod
    def _cycle_path(
        node: str,
        neighbor: str,
        parent_edge: dict[str, tuple[str, Affine]],
        root: str,
    ) -> tuple[str, ...]:
        """Rebuild node ... neighbor from tree parents and close the cycle."""

        def ancestors_of(x: str) -> list[str]:
            chain: list[str] = []
            while x != root:
                chain.append(x)
                x = parent_edge[x][0]
            chain.append(root)
            chain.reverse()
            return chain

        chain_node = ancestors_of(node)
        chain_neighbor = ancestors_of(neighbor)

        divergence = 0
        while (
            divergence < len(chain_node)
            and divergence < len(chain_neighbor)
            and chain_node[divergence] == chain_neighbor[divergence]
        ):
            divergence += 1
        divergence -= 1  # common prefix ends at divergence

        # node up to the common ancestor, then down to neighbor.
        up = list(reversed(chain_node[divergence:]))
        down = chain_neighbor[divergence + 1 :]
        path = up + down
        # Close the cycle along the offending edge neighbor -> node.
        return tuple(path + [node])

    # ------------------------------------------------------------------
    # Queries (only valid after check_consistency succeeds).
    # ------------------------------------------------------------------

    def connected(self, source: str, target: str) -> bool:
        if source not in self._instruments or target not in self._instruments:
            return False
        seen = {source}
        stack = [source]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            for neighbor, _ in self._adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        return False

    def transform_between(self, source: str, target: str) -> Optional[Affine]:
        """Return the unique exact transform ``source -> target``.

        Traversal order cannot change the result when the graph is consistent;
        the first path found is the only transform possible.
        """
        if source not in self._instruments or target not in self._instruments:
            return None
        # transform[node] maps source coords -> node coords along the BFS
        # tree.  In a consistent graph every path yields the same transform,
        # so traversal order cannot change the answer.
        transform: dict[str, Affine] = {source: Affine.identity()}
        stack: list[str] = [source]
        while stack:
            node = stack.pop()
            if node == target:
                return transform[node]
            source_to_node = transform[node]
            for neighbor, node_to_neighbor in self._adjacency[node]:
                if neighbor not in transform:
                    # source -> node, then node -> neighbor.
                    transform[neighbor] = source_to_node.compose(node_to_neighbor)
                    stack.append(neighbor)
        return None
