"""Strict numeric request contract for explicitly submitted anonymous computation.

The browser's source project remains local. Only a selected, canonical numerical
problem enters this API. No arbitrary URLs, paths, code, archives or model pickle.
"""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w .:/%()+,\-]+$")]
Vec3 = tuple[Finite, Finite, Finite]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Support(StrictModel):
    id: Label
    kind: Literal["point", "weighted-discrete", "continuous-interval", "continuous-volume"]
    points: Annotated[list[Vec3], Field(min_length=1, max_length=64)]
    weights: Annotated[list[NonNegative], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def valid_measure(self):
        if len(self.points) != len(self.weights):
            raise ValueError("Support point and weight counts differ")
        if not math.isclose(sum(self.weights), 1.0, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("Sampling weights must sum to one")
        if self.kind == "point" and len(self.points) != 1:
            raise ValueError("Point support requires exactly one coordinate")
        return self


class Observation(StrictModel):
    id: Label
    group: Label
    variable: Annotated[int, Field(ge=0, le=2)] = 0
    value: Finite
    errorVariance: NonNegative = 0.0
    support: Support


class Component(StrictModel):
    family: Literal["exponential", "spherical", "gaussian"]
    ranges: tuple[Positive, Positive, Positive]
    sill: Annotated[list[list[Finite]], Field(min_length=1, max_length=3)]
    rotation: tuple[Vec3, Vec3, Vec3] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class Covariance(StrictModel):
    components: Annotated[list[Component], Field(min_length=1, max_length=3)]
    nugget: Annotated[list[list[Finite]], Field(min_length=1, max_length=3)]


class Grid(StrictModel):
    origin: Vec3
    spacing: tuple[Positive, Positive, Positive]
    shape: tuple[Annotated[int, Field(ge=1, le=32)], Annotated[int, Field(ge=1, le=32)], Annotated[int, Field(ge=1, le=32)]]
    support: Literal["point-centre", "continuous-block"] = "point-centre"
    quadratureOrder: Literal[1, 2, 3, 4] = 1


class Search(StrictModel):
    maxSamples: Annotated[int, Field(ge=1, le=64)] = 32
    minSamples: Annotated[int, Field(ge=1, le=64)] = 4
    maxPerGroup: Annotated[int, Field(ge=1, le=64)] = 8
    minGroups: Annotated[int, Field(ge=1, le=64)] = 2
    radius: Positive = 1000.0

    @model_validator(mode="after")
    def consistent(self):
        if self.minSamples > self.maxSamples or self.minGroups > self.maxSamples:
            raise ValueError("Search minimum exceeds maximum observations")
        return self


class Conditioning(StrictModel):
    index: tuple[Annotated[int, Field(ge=0, le=31)], Annotated[int, Field(ge=0, le=31)], Annotated[int, Field(ge=0, le=31)]]
    value: Annotated[int, Field(ge=0, le=255)]


class TrainingImage(StrictModel):
    shape: tuple[Annotated[int, Field(ge=1, le=32)], Annotated[int, Field(ge=1, le=32)], Annotated[int, Field(ge=1, le=32)]]
    values: Annotated[list[Annotated[int, Field(ge=0, le=255)]], Field(min_length=1, max_length=32768)]
    kind: Literal["interpreted-prior", "authored-validation"]

    @model_validator(mode="after")
    def complete(self):
        if math.prod(self.shape) != len(self.values):
            raise ValueError("Training image must contain exactly its x-fast grid cells")
        return self


class JobRequest(StrictModel):
    schema: Literal["sondara.job/v1"]
    projectHash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    frameId: Label
    units: Annotated[list[Label], Field(min_length=1, max_length=3)]
    method: Literal["nn", "idw", "sk", "ok", "uk", "lmc", "mik", "sgs", "snesim", "ds"]
    observations: Annotated[list[Observation], Field(max_length=192)] = Field(default_factory=list)
    grid: Grid
    covariance: Covariance | None = None
    search: Search = Field(default_factory=Search)
    targetVariable: Annotated[int, Field(ge=0, le=2)] = 0
    mean: Annotated[list[Finite], Field(min_length=1, max_length=3)] | None = None
    drift: Literal["linear", "quadratic"] = "linear"
    idwPower: Annotated[float, Field(gt=0, le=8)] = 2.0
    thresholds: Annotated[list[Finite], Field(max_length=12)] = Field(default_factory=list)
    indicatorCovariances: Annotated[list[Covariance], Field(max_length=12)] = Field(default_factory=list)
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 20260910
    realizations: Annotated[int, Field(ge=1, le=8)] = 1
    trainingImage: TrainingImage | None = None
    hardData: Annotated[list[Conditioning], Field(max_length=512)] = Field(default_factory=list)
    patternSize: Annotated[int, Field(ge=1, le=32)] = 16
    matchThreshold: Annotated[float, Field(ge=0, le=1)] = 0.0
    scanFraction: Annotated[float, Field(gt=0, le=1)] = 1.0

    @model_validator(mode="after")
    def scientifically_admissible(self):
        variables = len(self.units)
        if self.targetVariable >= variables:
            raise ValueError("Target variable is outside the declared variables")
        if len({o.id for o in self.observations}) != len(self.observations):
            raise ValueError("Observation IDs must be unique")
        for v in range(variables):
            if sum(o.variable == v for o in self.observations) > 64:
                raise ValueError("Server accepts at most 64 observations per variable; larger jobs run locally")
        if any(o.variable >= variables for o in self.observations):
            raise ValueError("Observation variable is outside the declared variables")
        if self.method in {"snesim", "ds"}:
            if self.trainingImage is None or math.prod(self.grid.shape) > 4096:
                raise ValueError("Categorical jobs require a training image and at most 4096 target cells")
            categories = set(self.trainingImage.values)
            seen = {}
            for datum in self.hardData:
                if any(datum.index[a] >= self.grid.shape[a] for a in range(3)):
                    raise ValueError("Conditioning location lies outside the simulation grid")
                if datum.value not in categories:
                    raise ValueError("Conditioning category is absent from the training image")
                if datum.index in seen and seen[datum.index] != datum.value:
                    raise ValueError("Conflicting categorical conditioning at the same cell")
                seen[datum.index] = datum.value
        else:
            if not self.observations:
                raise ValueError("Continuous estimation requires observations")
            if self.method not in {"nn", "idw"} and self.covariance is None:
                raise ValueError("The selected method requires a covariance model")
            if self.method == "sk" and (self.mean is None or len(self.mean) != variables):
                raise ValueError("Simple kriging requires one explicit fixed mean per variable")
            if self.method != "lmc" and any(o.variable != self.targetVariable for o in self.observations):
                raise ValueError("Use full LMC for multiple observed variables")
            if self.method == "mik":
                if not self.thresholds or self.thresholds != sorted(set(self.thresholds)):
                    raise ValueError("Indicator thresholds must be finite, unique and increasing")
                if len(self.indicatorCovariances) != len(self.thresholds):
                    raise ValueError("Each indicator threshold requires its own fitted covariance")
            if self.method in {"mik", "sgs"} and self.grid.support != "point-centre":
                raise ValueError("Probability/simulation server lane requires declared point-centre support")
        for model in ([self.covariance] if self.covariance else []) + self.indicatorCovariances:
            matrices = [model.nugget] + [c.sill for c in model.components]
            if any(len(m) != variables or any(len(row) != variables for row in m) for m in matrices):
                raise ValueError("Covariance matrix dimensions do not match variable count")
        # Memory/work admission is conservative and explicitly separable from accuracy.
        n = len(self.observations)
        q = self.grid.quadratureOrder ** 3 if self.grid.support == "continuous-block" else 1
        if math.prod(self.grid.shape) * max(n, 1) * q > 50_000_000:
            raise ValueError("Requested support integration exceeds server work budget; use the local recipe")
        return self
