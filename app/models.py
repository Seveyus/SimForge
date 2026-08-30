"""Shared data contracts for SimForge's AI modelling and UI boundary.

The models in this module deliberately describe JSON payloads rather than
simulation implementation details.  They are the Python counterpart of the M0
fixtures in ``static/fixtures``.
"""

from __future__ import annotations

from enum import Enum
from math import isclose, isfinite
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ScalarValue = bool | int | float | str
NumericValue = int | float

_PARAMETER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_POSITIVE_PARAMETERS = {
    "collections_per_day",
    "production_rate",
    "tank_capacity",
    "tank_count",
    "tanker_capacity",
}
_EXPECTED_UNITS = {
    "collections_per_day": "collections/day",
    "missed_collection_probability": "fraction",
    "production_rate": "tonnes/hour",
    "tank_capacity": "tonnes",
    "tank_count": None,
    "tanker_capacity": "tonnes",
}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _ensure_finite(value: object, *, field_name: str) -> None:
    if _is_number(value) and not isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _validate_parameter_key(key: str) -> str:
    if not _PARAMETER_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "parameter keys must use lower_snake_case and start with a letter"
        )
    return key


def _validate_parameter_mapping(
    parameters: dict[str, ParameterValue],
) -> dict[str, ParameterValue]:
    for key, parameter in parameters.items():
        _validate_parameter_key(key)
        value = parameter.value

        if key in _POSITIVE_PARAMETERS:
            if not _is_number(value) or value <= 0:
                raise ValueError(f"{key} must be a number greater than zero")

        if key == "tank_count" and not isinstance(value, int):
            raise ValueError("tank_count must be an integer")

        if key.endswith("_probability"):
            if not _is_number(value) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be a number between 0 and 1")

        if key in _EXPECTED_UNITS and parameter.unit != _EXPECTED_UNITS[key]:
            expected_unit = _EXPECTED_UNITS[key] or "no unit"
            raise ValueError(f"{key} must use {expected_unit}")

    return parameters


class ContractModel(BaseModel):
    """Strict base model used by public request and response contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ProvenanceSource(str, Enum):
    USER = "user"
    RESEARCHED = "researched"
    ESTIMATED = "estimated"
    ASSUMPTION = "assumption"


class ParameterValue(ContractModel):
    """A model input together with its unit and source provenance."""

    value: ScalarValue
    unit: str | None = None
    source: ProvenanceSource
    rationale: str | None = None
    citation: str | None = None

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: ScalarValue) -> ScalarValue:
        _ensure_finite(value, field_name="value")
        if isinstance(value, str) and not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("unit", "rationale", "citation", mode="before")
    @classmethod
    def empty_optional_strings_are_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_provenance_context(self) -> ParameterValue:
        if self.source is ProvenanceSource.RESEARCHED and not self.citation:
            raise ValueError("researched values require a citation")
        if self.source in {
            ProvenanceSource.ESTIMATED,
            ProvenanceSource.ASSUMPTION,
        } and not self.rationale:
            raise ValueError(f"{self.source.value} values require a rationale")
        return self


class TimeConfig(ContractModel):
    simulation_days: int = Field(gt=0)
    timestep_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def timestep_must_fit_horizon(self) -> TimeConfig:
        horizon_minutes = self.simulation_days * 24 * 60
        if self.timestep_minutes > horizon_minutes:
            raise ValueError("timestep_minutes must not exceed the simulation horizon")
        return self


class ModelSpec(ContractModel):
    """A complete model specification ready for simulator generation."""

    objective: str = Field(min_length=1, max_length=500)
    process_family: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    time: TimeConfig
    parameters: dict[str, ParameterValue] = Field(min_length=1)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(
        cls, parameters: dict[str, ParameterValue]
    ) -> dict[str, ParameterValue]:
        return _validate_parameter_mapping(parameters)


class ModelSpecDraft(ContractModel):
    """A structurally valid but potentially incomplete specification."""

    objective: str | None = Field(default=None, min_length=1, max_length=500)
    process_family: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    time: TimeConfig | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameter_names(
        cls, parameters: dict[str, ParameterValue]
    ) -> dict[str, ParameterValue]:
        return _validate_parameter_mapping(parameters)


class ClarificationInputType(str, Enum):
    NUMBER = "number"
    TEXT = "text"
    BOOLEAN = "boolean"
    SELECT = "select"


class ClarificationQuestion(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    parameter_key: str
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required: bool = True
    input_type: ClarificationInputType
    unit: str | None = None
    choices: list[ScalarValue] = Field(default_factory=list)

    @field_validator("parameter_key")
    @classmethod
    def validate_parameter_name(cls, value: str) -> str:
        return _validate_parameter_key(value)

    @model_validator(mode="after")
    def select_questions_need_choices(self) -> ClarificationQuestion:
        if self.input_type is ClarificationInputType.SELECT and not self.choices:
            raise ValueError("select questions require at least one choice")
        return self


class AssumptionRecord(ContractModel):
    path: str = Field(min_length=1)
    value: ScalarValue
    unit: str | None = None
    source: ProvenanceSource = ProvenanceSource.ASSUMPTION
    rationale: str = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: ScalarValue) -> ScalarValue:
        _ensure_finite(value, field_name="value")
        return value

    @model_validator(mode="after")
    def source_must_be_assumption(self) -> AssumptionRecord:
        if self.source is not ProvenanceSource.ASSUMPTION:
            raise ValueError("assumption records must use source='assumption'")
        return self


class RequirementsStatus(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    READY = "ready"


class RequirementsMetadata(BaseModel):
    """Provider metadata is extensible and never used as domain input."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class RequirementsResult(ContractModel):
    status: RequirementsStatus
    draft_spec: ModelSpecDraft | None = None
    model_spec: ModelSpec | None = None
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    assumptions: list[AssumptionRecord] = Field(default_factory=list)
    metadata: RequirementsMetadata | None = None

    @model_validator(mode="after")
    def validate_state(self) -> RequirementsResult:
        if self.status is RequirementsStatus.NEEDS_CLARIFICATION:
            if self.draft_spec is None:
                raise ValueError("needs_clarification requires draft_spec")
            if self.model_spec is not None:
                raise ValueError("needs_clarification must not include model_spec")
            if not self.questions:
                raise ValueError("needs_clarification requires at least one question")

        if self.status is RequirementsStatus.READY:
            if self.model_spec is None:
                raise ValueError("ready requires model_spec")
            if self.draft_spec is not None:
                raise ValueError("ready must not include draft_spec")
            if self.questions:
                raise ValueError("ready must not include clarification questions")

        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification question ids must be unique")

        assumption_paths = [assumption.path for assumption in self.assumptions]
        if len(assumption_paths) != len(set(assumption_paths)):
            raise ValueError("assumption paths must be unique")

        active_spec = self.model_spec or self.draft_spec
        if active_spec is not None:
            required_assumptions = {
                f"parameters.{key}"
                for key, parameter in active_spec.parameters.items()
                if parameter.source is ProvenanceSource.ASSUMPTION
            }
            missing_assumptions = required_assumptions - set(assumption_paths)
            if missing_assumptions:
                missing = ", ".join(sorted(missing_assumptions))
                raise ValueError(f"assumption review is missing: {missing}")
        return self


class RequirementsRequest(ContractModel):
    description: str | None = Field(default=None, min_length=1)
    draft_spec: ModelSpecDraft | None = None
    answers: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_conversation_input(self) -> RequirementsRequest:
        if self.description is None and self.draft_spec is None and not self.answers:
            raise ValueError("description, draft_spec or answers is required")
        for question_id in self.answers:
            if not _ID_PATTERN.fullmatch(question_id):
                raise ValueError(f"invalid clarification question id: {question_id}")
        return self


class TimeseriesPoint(BaseModel):
    """A time coordinate plus simulator-defined numeric series values."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    time_hours: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_series_values(self) -> TimeseriesPoint:
        for key, value in (self.__pydantic_extra__ or {}).items():
            _validate_parameter_key(key)
            if not _is_number(value) or not isfinite(value):
                raise ValueError(f"time-series value {key} must be a finite number")
        return self


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SimulationEvent(ContractModel):
    time_hours: float = Field(ge=0)
    type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    severity: EventSeverity
    details: dict[str, Any] = Field(default_factory=dict)


class SimulationResult(ContractModel):
    timeseries: list[TimeseriesPoint]
    metrics: dict[str, NumericValue]
    events: list[SimulationEvent]
    metadata: dict[str, Any] | None = None

    @field_validator("metrics")
    @classmethod
    def validate_metrics(
        cls, metrics: dict[str, NumericValue]
    ) -> dict[str, NumericValue]:
        for key, value in metrics.items():
            _validate_parameter_key(key)
            if not _is_number(value) or not isfinite(value):
                raise ValueError(f"metric {key} must be a finite number")
        return metrics

    @model_validator(mode="after")
    def timeseries_must_be_chronological(self) -> SimulationResult:
        times = [point.time_hours for point in self.timeseries]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("time-series points must have unique ascending time_hours")
        return self


class SimulationRequest(ContractModel):
    model_spec: ModelSpec
    seed: int | None = None
    rollout_count: int = Field(default=1, gt=0)


class ScenarioDefinition(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1)
    parameter_overrides: dict[str, ScalarValue] = Field(min_length=1)

    @field_validator("parameter_overrides")
    @classmethod
    def validate_overrides(
        cls, overrides: dict[str, ScalarValue]
    ) -> dict[str, ScalarValue]:
        for key, value in overrides.items():
            _validate_parameter_key(key)
            _ensure_finite(value, field_name=key)
        return overrides


class ScenarioComparisonRequest(ContractModel):
    model_spec: ModelSpec
    scenarios: list[ScenarioDefinition] = Field(min_length=1)
    seed: int | None = None
    rollout_count: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def scenario_ids_must_be_unique(self) -> ScenarioComparisonRequest:
        scenario_ids = [scenario.id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario ids must be unique")
        return self


class ScenarioStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class ScenarioError(ContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    retryable: bool


class ScenarioRun(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1)
    status: ScenarioStatus
    parameter_overrides: dict[str, ScalarValue] | None = None
    result: SimulationResult | None = None
    error: ScenarioError | None = None

    @field_validator("parameter_overrides")
    @classmethod
    def validate_parameter_overrides(
        cls, overrides: dict[str, ScalarValue] | None
    ) -> dict[str, ScalarValue] | None:
        if overrides is not None:
            for key, value in overrides.items():
                _validate_parameter_key(key)
                _ensure_finite(value, field_name=key)
        return overrides

    @model_validator(mode="after")
    def validate_status_payload(self) -> ScenarioRun:
        if self.status is ScenarioStatus.COMPLETED:
            if self.result is None or self.error is not None:
                raise ValueError("completed scenarios require result and no error")
        if self.status is ScenarioStatus.FAILED:
            if self.result is not None or self.error is None:
                raise ValueError("failed scenarios require error and no result")
        return self


class MetricDelta(ContractModel):
    baseline: float
    scenario: float
    absolute_change: float
    percentage_change: float | None = None
    unit: str | None = None

    @field_validator(
        "baseline",
        "scenario",
        "absolute_change",
        "percentage_change",
    )
    @classmethod
    def metric_values_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("metric delta values must be finite")
        return value

    @model_validator(mode="after")
    def absolute_change_must_match_values(self) -> MetricDelta:
        expected_change = self.scenario - self.baseline
        if not isclose(self.absolute_change, expected_change, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("absolute_change must equal scenario minus baseline")
        return self


class Recommendation(ContractModel):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    metric_deltas: dict[str, MetricDelta]
    financials: dict[str, NumericValue] = Field(default_factory=dict)

    @field_validator("metric_deltas")
    @classmethod
    def validate_metric_delta_names(
        cls, deltas: dict[str, MetricDelta]
    ) -> dict[str, MetricDelta]:
        for key in deltas:
            _validate_parameter_key(key)
        return deltas

    @field_validator("financials")
    @classmethod
    def validate_financials(
        cls, financials: dict[str, NumericValue]
    ) -> dict[str, NumericValue]:
        for key, value in financials.items():
            _validate_parameter_key(key)
            if not _is_number(value) or not isfinite(value):
                raise ValueError(f"financial value {key} must be a finite number")
        return financials


class ScenarioComparison(ContractModel):
    baseline: ScenarioRun
    scenarios: list[ScenarioRun] = Field(min_length=1)
    recommendation: Recommendation | None = None

    @model_validator(mode="after")
    def validate_comparison(self) -> ScenarioComparison:
        if self.baseline.status is not ScenarioStatus.COMPLETED:
            raise ValueError("baseline must be completed in a successful comparison")

        scenario_ids = [scenario.id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario ids must be unique")
        if self.baseline.id in scenario_ids:
            raise ValueError("baseline id must not be reused by a scenario")

        if self.recommendation is not None:
            completed_ids = {
                scenario.id
                for scenario in self.scenarios
                if scenario.status is ScenarioStatus.COMPLETED
            }
            if self.recommendation.scenario_id not in completed_ids:
                raise ValueError("recommendation must reference a completed scenario")
        return self


class FieldError(ContractModel):
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ApiErrorDetail(ContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    retryable: bool
    field_errors: list[FieldError] = Field(default_factory=list)
    request_id: str | None = None


class ApiErrorResponse(ContractModel):
    error: ApiErrorDetail
