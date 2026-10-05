import random

import pytest

from app.graph import Affine, CalibrationConflict, CalibrationGraph
from app.rational import parse_rational


def aff(a: str, b: str) -> Affine:
    return Affine(parse_rational(a), parse_rational(b))


def build(relations):
    graph = CalibrationGraph()
    for source, target, transform in relations:
        graph.add_relation(source, target, transform)
    return graph


def test_simple_chain_composition():
    # A -> B: y = 2x + 1 ; B -> C: y = 3y + 4
    # A -> C: z = 6x + 7
    graph = build([("A", "B", aff("2", "1")), ("B", "C", aff("3", "4"))])
    graph.check_consistency()
    assert graph.transform_between("A", "C") == aff("6", "7")
    assert graph.transform_between("C", "A") == aff("1/6", "-7/6")


def test_two_paths_must_agree_exactly():
    # Direct A -> C and path A -> B -> C induce the same transform.
    graph = build(
        [
            ("A", "B", aff("2", "1")),
            ("B", "C", aff("3", "4")),
            ("A", "C", aff("6", "7")),
        ]
    )
    graph.check_consistency()
    assert graph.transform_between("A", "C") == aff("6", "7")


def test_conflicting_cycle_is_detected_with_instruments():
    # A -> B: 2x+1 ; B -> C: 3x+4 ; A -> C: 6x+8 (intercept contradicts 7)
    graph = build(
        [
            ("A", "B", aff("2", "1")),
            ("B", "C", aff("3", "4")),
            ("A", "C", aff("6", "8")),
        ]
    )
    with pytest.raises(CalibrationConflict) as exc:
        graph.check_consistency()
    assert set(exc.value.instruments) == {"A", "B", "C"}


def test_conflict_unrelated_to_query_still_fails():
    # D -> E -> F cycle conflicts even though query only uses A -> B.
    graph = build(
        [
            ("A", "B", aff("2", "0")),
            ("D", "E", aff("1", "1")),
            ("E", "F", aff("1", "1")),
            ("D", "F", aff("1", "3")),  # should be 1*x + 2
        ]
    )
    with pytest.raises(CalibrationConflict):
        graph.check_consistency()


def test_unreachable():
    graph = build([("A", "B", aff("2", "0")), ("C", "D", aff("3", "0"))])
    graph.check_consistency()
    assert not graph.connected("A", "D")
    assert graph.transform_between("A", "D") is None


def test_slope_one_cycles_with_intercepts():
    # Fahrenheit-like: offsets around a triangle must sum to zero.
    graph = build(
        [
            ("A", "B", aff("1", "10")),
            ("B", "C", aff("1", "20")),
            ("A", "C", aff("1", "30")),
        ]
    )
    graph.check_consistency()


def test_non_unit_slopes_consistent_cycle():
    # A->B 2x ; B->C (1/2)x+3 ; A->C x+3
    graph = build(
        [
            ("A", "B", aff("2", "0")),
            ("B", "C", aff("1/2", "3")),
            ("A", "C", aff("1", "3")),
        ]
    )
    graph.check_consistency()


def test_non_unit_slopes_conflicting_cycle():
    graph = build(
        [
            ("A", "B", aff("2", "0")),
            ("B", "C", aff("1/2", "3")),
            ("A", "C", aff("1", "4")),
        ]
    )
    with pytest.raises(CalibrationConflict):
        graph.check_consistency()


def test_order_independence():
    relations = [
        ("A", "B", aff("2", "1")),
        ("B", "C", aff("3", "4")),
        ("C", "D", aff("-1/2", "5")),
        ("A", "D", None),  # filled below with the composed truth
    ]
    chain = aff("2", "1").compose(aff("3", "4")).compose(aff("-1/2", "5"))
    relations[-1] = ("A", "D", chain)

    seen = set()
    rng = random.Random(1234)
    for _ in range(20):
        shuffled = relations[:]
        rng.shuffle(shuffled)
        graph = build(shuffled)
        graph.check_consistency()
        seen.add(graph.transform_between("A", "D"))
    assert seen == {chain}


def test_inverse_edge_round_trip():
    graph = build([("A", "B", aff("3/2", "-5/7"))])
    graph.check_consistency()
    forward = graph.transform_between("A", "B")
    back = graph.transform_between("B", "A")
    assert forward.compose(back) == Affine.identity()


def test_apply_is_exact():
    t = aff("1/3", "1/6")
    assert t.apply(parse_rational("1/2")) == parse_rational("1/3")


def test_zero_slope_rejected():
    graph = CalibrationGraph()
    with pytest.raises(ValueError):
        graph.add_relation("A", "B", aff("0", "1"))
