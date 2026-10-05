"""HTTP API for exact calibration translation."""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from .graph import Affine, CalibrationConflict, CalibrationGraph
from .rational import RationalParseError, format_rational, parse_rational

app = FastAPI(
    title="Calibration Translation Service",
    version="1.0.0",
    description="Exact rational composition of calibration relations between instruments.",
)


class RelationIn(BaseModel):
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    a: str = Field(..., description="non-zero slope as integer or p/q")
    b: str = Field(..., description="intercept as integer or p/q")


class TranslateRequest(BaseModel):
    instruments: list[str] = Field(..., min_length=2, max_length=50)
    relations: list[RelationIn] = Field(..., min_length=1, max_length=100)
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    readings: list[str] = Field(..., min_length=1)

    @field_validator("instruments")
    @classmethod
    def _unique_instruments(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("instruments must be unique")
        return value


class Coefficients(BaseModel):
    a: str
    b: str


class TranslateResponse(BaseModel):
    source: str
    target: str
    coefficients: Coefficients
    readings: list[str]
    results: list[str]


class ErrorBody(BaseModel):
    error: Literal["unreachable", "conflict", "invalid_request"]
    message: str
    instruments: list[str] | None = None


def _error(status: int, code: str, message: str, instruments: list[str] | None = None) -> JSONResponse:
    body: dict[str, object] = {"error": code, "message": message}
    if instruments is not None:
        body["instruments"] = instruments
    return JSONResponse(status_code=status, content=body)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/calibrations/translate", response_model=TranslateResponse)
def translate(request: TranslateRequest) -> TranslateResponse | JSONResponse:
    instruments = set(request.instruments)

    unknown: set[str] = set()
    for endpoint in (request.source, request.target):
        if endpoint not in instruments:
            unknown.add(endpoint)
    for relation in request.relations:
        if relation.source not in instruments:
            unknown.add(relation.source)
        if relation.target not in instruments:
            unknown.add(relation.target)
    if unknown:
        return _error(
            422,
            "invalid_request",
            f"relations reference instruments not declared: {', '.join(sorted(unknown))}",
        )

    graph = CalibrationGraph()
    for instrument in request.instruments:
        graph.add_instrument(instrument)

    try:
        edges: list[tuple[str, str, Affine]] = []
        for relation in request.relations:
            slope = parse_rational(relation.a)
            intercept = parse_rational(relation.b)
            if slope == 0:
                return _error(
                    422,
                    "invalid_request",
                    f"relation {relation.source} -> {relation.target} has a zero slope; "
                    "every relation must be invertible",
                )
            edges.append((relation.source, relation.target, Affine(slope, intercept)))
        parsed_readings = [parse_rational(value) for value in request.readings]
    except RationalParseError as exc:
        return _error(422, "invalid_request", str(exc))

    for source, target, affine in edges:
        try:
            graph.add_relation(source, target, affine)
        except ValueError as exc:
            return _error(422, "invalid_request", str(exc))

    # Validate the whole evidence set first: any contradictory cycle is an
    # error even if source/target do not touch it, and no readings are ever
    # returned from inconsistent data.
    try:
        graph.check_consistency()
    except CalibrationConflict as exc:
        return _error(409, "conflict", str(exc), exc.instruments)

    if not graph.connected(request.source, request.target):
        return _error(
            404,
            "unreachable",
            f"no calibration path connects {request.source} to {request.target}",
            [request.source, request.target],
        )

    transform = graph.transform_between(request.source, request.target)
    assert transform is not None  # connectivity was just established

    results: list[Fraction] = [transform.apply(value) for value in parsed_readings]
    return TranslateResponse(
        source=request.source,
        target=request.target,
        coefficients=Coefficients(
            a=format_rational(transform.slope),
            b=format_rational(transform.intercept),
        ),
        readings=list(request.readings),
        results=[format_rational(value) for value in results],
    )
