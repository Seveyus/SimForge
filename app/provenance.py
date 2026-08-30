"""Pure provenance helpers for model inputs.

This module has no provider, database or simulator dependency.  It makes source
transitions explicit so an estimate or assumption cannot silently become a
user-supplied fact.
"""

from __future__ import annotations

from types import MappingProxyType

from .models import AssumptionRecord, ModelSpec, ParameterValue, ProvenanceSource


PROVENANCE_DISPLAY_LABELS = MappingProxyType(
    {
        ProvenanceSource.USER: "USER",
        ProvenanceSource.RESEARCHED: "RESEARCHED",
        ProvenanceSource.ESTIMATED: "ESTIMATED",
        ProvenanceSource.ASSUMPTION: "ASSUMPTION",
    }
)

_SOURCE_PRIORITY = {
    ProvenanceSource.ASSUMPTION: 0,
    ProvenanceSource.ESTIMATED: 1,
    ProvenanceSource.RESEARCHED: 2,
    ProvenanceSource.USER: 3,
}


def provenance_label(source: ProvenanceSource | str) -> str:
    """Return the stable uppercase UI label for a provenance source."""

    resolved_source = (
        source if isinstance(source, ProvenanceSource) else ProvenanceSource(source)
    )
    return PROVENANCE_DISPLAY_LABELS[resolved_source]


def make_parameter(
    value: bool | int | float | str,
    *,
    source: ProvenanceSource | str,
    unit: str | None = None,
    rationale: str | None = None,
    citation: str | None = None,
) -> ParameterValue:
    """Create a validated parameter without inferring its source."""

    return ParameterValue(
        value=value,
        unit=unit,
        source=source,
        rationale=rationale,
        citation=citation,
    )


def merge_parameter(
    existing: ParameterValue,
    incoming: ParameterValue,
    *,
    user_confirmed: bool = False,
) -> ParameterValue:
    """Merge two versions while respecting provenance priority.

    A transition to ``user`` from any other source requires the caller to state
    that the user actually confirmed the value.  Existing user values cannot be
    replaced by lower-priority sources.
    """

    if (
        incoming.source is ProvenanceSource.USER
        and existing.source is not ProvenanceSource.USER
        and not user_confirmed
    ):
        raise ValueError("upgrading a value to user provenance requires confirmation")

    if _SOURCE_PRIORITY[incoming.source] < _SOURCE_PRIORITY[existing.source]:
        return existing.model_copy(deep=True)
    return incoming.model_copy(deep=True)


def apply_user_value(
    existing: ParameterValue,
    value: bool | int | float | str,
    *,
    unit: str | None = None,
) -> ParameterValue:
    """Apply an explicit clarification answer and mark it as user supplied."""

    user_value = ParameterValue(
        value=value,
        unit=unit if unit is not None else existing.unit,
        source=ProvenanceSource.USER,
        rationale="Confirmed by the user during clarification.",
        citation=None,
    )
    return merge_parameter(existing, user_value, user_confirmed=True)


def parameters_by_source(
    model_spec: ModelSpec,
) -> dict[ProvenanceSource, list[str]]:
    """Group sorted parameter keys by source, including empty groups."""

    grouped = {source: [] for source in ProvenanceSource}
    for key, parameter in model_spec.parameters.items():
        grouped[parameter.source].append(key)
    for keys in grouped.values():
        keys.sort()
    return grouped


def summarise_provenance(model_spec: ModelSpec) -> dict[str, int]:
    """Return JSON-ready counts for each provenance category."""

    grouped = parameters_by_source(model_spec)
    return {source.value: len(grouped[source]) for source in ProvenanceSource}


def list_assumptions(model_spec: ModelSpec) -> list[AssumptionRecord]:
    """Return parameter assumptions in the UI review-list shape."""

    assumptions: list[AssumptionRecord] = []
    for key, parameter in sorted(model_spec.parameters.items()):
        if parameter.source is not ProvenanceSource.ASSUMPTION:
            continue
        assumptions.append(
            AssumptionRecord(
                path=f"parameters.{key}",
                value=parameter.value,
                unit=parameter.unit,
                source=parameter.source,
                rationale=parameter.rationale or "Explicit model assumption.",
            )
        )
    return assumptions


def update_parameter(
    model_spec: ModelSpec,
    key: str,
    parameter: ParameterValue,
    *,
    user_confirmed: bool = False,
) -> ModelSpec:
    """Return a copied spec with one provenance-safe parameter update."""

    updated_parameters: dict[str, ParameterValue] = {
        name: value.model_copy(deep=True)
        for name, value in model_spec.parameters.items()
    }
    if key in updated_parameters:
        updated_parameters[key] = merge_parameter(
            updated_parameters[key],
            parameter,
            user_confirmed=user_confirmed,
        )
    else:
        updated_parameters[key] = parameter.model_copy(deep=True)

    payload = model_spec.model_dump(mode="python")
    payload["parameters"] = updated_parameters
    return ModelSpec.model_validate(payload)
