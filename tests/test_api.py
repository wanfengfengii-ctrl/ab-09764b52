from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def base_payload(**overrides):
    payload = {
        "instruments": ["A", "B", "C"],
        "relations": [
            {"source": "A", "target": "B", "a": "2", "b": "1"},
            {"source": "B", "target": "C", "a": "3", "b": "4"},
        ],
        "source": "A",
        "target": "C",
        "readings": ["0", "1", "1/2"],
    }
    payload.update(overrides)
    return payload


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_translate_chain_exact():
    response = client.post("/api/calibrations/translate", json=base_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    # A -> C: 3*(2x+1)+4 = 6x+7
    assert body["coefficients"] == {"a": "6", "b": "7"}
    assert body["results"] == ["7", "13", "10"]


def test_reverse_direction_uses_inverse():
    payload = base_payload(source="C", target="A", readings=["7"])
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["coefficients"] == {"a": "1/6", "b": "-7/6"}
    assert response.json()["results"] == ["0"]


def test_unreachable_identified():
    payload = base_payload(
        instruments=["A", "B", "C", "X"],
        source="A",
        target="X",
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "unreachable"
    assert set(body["instruments"]) == {"A", "X"}


def test_conflict_identified_with_instruments_and_no_results():
    payload = base_payload(
        relations=[
            {"source": "A", "target": "B", "a": "2", "b": "1"},
            {"source": "B", "target": "C", "a": "3", "b": "4"},
            {"source": "A", "target": "C", "a": "6", "b": "999"},
        ]
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "conflict"
    assert set(body["instruments"]) == {"A", "B", "C"}
    assert "results" not in body
    assert "coefficients" not in body


def test_conflict_on_unrelated_cycle_rejected():
    payload = base_payload(
        instruments=["A", "B", "D", "E", "F"],
        relations=[
            {"source": "A", "target": "B", "a": "2", "b": "0"},
            {"source": "D", "target": "E", "a": "1", "b": "1"},
            {"source": "E", "target": "F", "a": "1", "b": "1"},
            {"source": "D", "target": "F", "a": "1", "b": "3"},
        ],
        source="A",
        target="B",
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


def test_zero_slope_rejected():
    payload = base_payload(
        relations=[{"source": "A", "target": "B", "a": "0", "b": "1"}]
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 422


def test_decimal_input_rejected():
    payload = base_payload(
        relations=[{"source": "A", "target": "B", "a": "1.5", "b": "1"}]
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 422


def test_duplicate_instruments_rejected():
    payload = base_payload(instruments=["A", "A", "B"])
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 422


def test_self_loop_rejected():
    payload = base_payload(
        relations=[{"source": "A", "target": "A", "a": "1", "b": "0"}]
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 422


def test_undeclared_instrument_rejected():
    payload = base_payload(
        relations=[{"source": "A", "target": "Z", "a": "1", "b": "0"}]
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_cardinality_limits_enforced():
    too_few = base_payload(instruments=["A"])
    assert client.post("/api/calibrations/translate", json=too_few).status_code == 422

    fifty_one = base_payload(instruments=[f"I{i}" for i in range(51)])
    assert client.post("/api/calibrations/translate", json=fifty_one).status_code == 422

    no_relations = base_payload(relations=[])
    assert client.post("/api/calibrations/translate", json=no_relations).status_code == 422

    no_readings = base_payload(readings=[])
    assert client.post("/api/calibrations/translate", json=no_readings).status_code == 422


def test_negative_fraction_round_trip():
    payload = base_payload(
        instruments=["A", "B"],
        relations=[{"source": "A", "target": "B", "a": "-3/2", "b": "1/4"}],
        target="B",
        readings=["2/3"],
    )
    response = client.post("/api/calibrations/translate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # -3/2 * 2/3 + 1/4 = -1 + 1/4 = -3/4
    assert body["results"] == ["-3/4"]

    reverse = client.post(
        "/api/calibrations/translate",
        json=base_payload(
            relations=[{"source": "A", "target": "B", "a": "-3/2", "b": "1/4"}],
            source="B",
            target="A",
            readings=["-3/4"],
        ),
    )
    assert reverse.status_code == 200, reverse.text
    assert reverse.json()["results"] == ["2/3"]

