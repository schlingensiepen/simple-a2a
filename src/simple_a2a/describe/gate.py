"""The one gate: nothing is described nowhere, and no example contradicts itself.

There is **one** gate, not one per surface, and that is the whole point of it. It
takes a rule parameter saying which surface it is checking, because what counts as
complete differs a little between them — but the walk, the rules and the failure
message are written once. Two gates drift the moment somebody fixes one of them.

What it insists on:

- **Every route has a description.** A route nobody described is a route an agent
  has to guess at, and guessing is what the whole self-description exists to
  replace.
- **Every field has a description and an example.** The example is the load-bearing
  half: a field described as "the recipient" and a field with `"Anna"` next to it
  are different amounts of help, and only the second survives being read by
  something that has never seen this service.
- **No example that looks like a real secret.** An agent reads an example and
  sends it. Examples of secrets are obvious placeholders or they are absent.
- **No placeholder left in a rendered text**, and outside the entry, no `http` in
  any part of the guide. The base address belongs in exactly one place; a part
  that carries one is a part that is wrong the moment it is served from a second
  host name.
- **An operation behind a token says so.** Every operation that reads the token
  header declares the bearer scheme, and none that does not read it declares any;
  a client generated from the description would otherwise send a token nowhere or
  everywhere.
- **A text for every rejection an operation can give.** Checked against the
  register rather than at the moment of failure, so a missing text is a red build
  and not a caller's afternoon.

Prose answers have no fields. The gate grips them **at the address**: the
description has to say what stands in the prose and where it branches to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from simple_a2a.describe.teaching import Register

#: What a description must not be. An empty string, a placeholder somebody meant
#: to come back to, or the name of the thing again — all three pass a "is there a
#: description" check and help nobody.
EMPTY = ("", "TODO", "TBD", "...", "-")

#: Strings that mean somebody left a template behind.
PLACEHOLDER_MARKS = ("%%", "{{", "<<")


@dataclass(frozen=True)
class Rules:
    """The rule parameter: which surface, and what is complete for it.

    One gate, one set of checks, a parameter for the differences. The observation
    surface has no request bodies to check, and the participant surface is the
    only one that may offer a machine-callable extra — differences small enough to
    be arguments and too small to justify a second gate.
    """

    surface: str
    #: Whether this surface offers anything beyond the three static forms. Only
    #: the participant surface does, and only from the second release on.
    offers_extra_form: bool = False


@dataclass
class Findings:
    """What the gate found. Empty means the description is complete."""

    problems: list[str] = field(default_factory=list)

    def note(self, problem: str) -> None:
        self.problems.append(problem)

    def __bool__(self) -> bool:
        return not self.problems

    def report(self) -> str:
        return "\n".join(f"  - {problem}" for problem in self.problems)


def _described(value: object) -> bool:
    return isinstance(value, str) and value.strip() not in EMPTY


def check_description(document: dict[str, Any], rules: Rules) -> Findings:
    """Walk a generated interface description and hold it to the rules above."""
    found = Findings()
    paths = document.get("paths") or {}
    if not paths:
        found.note(f"{rules.surface}: the description has no routes at all")

    for path, verbs in sorted(paths.items()):
        for verb, operation in sorted(verbs.items()):
            if verb.startswith("x-") or not isinstance(operation, dict):
                continue
            where = f"{rules.surface} {verb.upper()} {path}"
            if not _described(operation.get("summary")) and not _described(
                operation.get("description")
            ):
                found.note(f"{where}: no description")
            for problem in _check_schemas(operation, where):
                found.note(problem)
            for problem in _check_security(document, operation, where):
                found.note(problem)

    for name, schema in sorted((document.get("components", {}).get("schemas") or {}).items()):
        for problem in _check_fields(schema, f"{rules.surface} schema {name}"):
            found.note(problem)

    return found


def _check_schemas(operation: dict[str, Any], where: str) -> list[str]:
    problems: list[str] = []
    for parameter in operation.get("parameters") or []:
        if not _described(parameter.get("description")):
            problems.append(f"{where}: parameter {parameter.get('name')!r} has no description")
        schema = parameter.get("schema") or {}
        if not any(
            key in place for place in (parameter, schema) for key in ("example", "examples")
        ):
            # Both spellings count: OpenAPI 3.1 has `examples` as a list on a schema
            # and `example` as a single value, and pydantic writes whichever it
            # writes. What matters is that there is one, not where it sits.
            problems.append(f"{where}: parameter {parameter.get('name')!r} has no example")
    body = ((operation.get("requestBody") or {}).get("content") or {}).get("application/json") or {}
    if body:
        problems += _check_fields(body.get("schema") or {}, f"{where} request")
    return problems


def _check_security(document: dict[str, Any], operation: dict[str, Any], where: str) -> list[str]:
    """Behind a token exactly when the token header is read, and with a declared scheme."""
    reads_token = any(
        parameter.get("in") == "header"
        and str(parameter.get("name", "")).lower() == "authorization"
        for parameter in operation.get("parameters") or []
    )
    declared = [name for entry in operation.get("security") or [] for name in entry]
    if reads_token and not declared:
        return [f"{where}: reads the token but declares no security"]
    if declared and not reads_token:
        return [f"{where}: declares security but works without a token"]
    schemes = (document.get("components") or {}).get("securitySchemes") or {}
    return [
        f"{where}: security scheme {name!r} is not declared"
        for name in declared
        if (schemes.get(name) or {}).get("scheme") != "bearer"
    ]


def _check_fields(schema: dict[str, Any], where: str) -> list[str]:
    """Every property of a schema, described and exemplified.

    Recursive, because a nested object is where a field hides from a check that
    only looks at the top level — and a nested field is exactly the kind a caller
    gets wrong.
    """
    problems: list[str] = []
    for name, property_schema in sorted((schema.get("properties") or {}).items()):
        if not isinstance(property_schema, dict):
            continue
        spot = f"{where}.{name}"
        if not _described(property_schema.get("description")):
            problems.append(f"{spot}: no description")
        if "example" not in property_schema and "examples" not in property_schema:
            problems.append(f"{spot}: no example")
        problems += _check_fields(property_schema, spot)
        items = property_schema.get("items")
        if isinstance(items, dict):
            problems += _check_fields(items, f"{spot}[]")
    return problems


def check_texts(texts: dict[str, str], *, entry_name: str = "entry") -> Findings:
    """The rendered texts: no placeholder left, and `http` only in the entry.

    Run on what is **served**, not on what is stored. A placeholder is only wrong
    once it has been rendered, and that is the moment nobody is watching.
    """
    found = Findings()
    for name, text in sorted(texts.items()):
        for mark in PLACEHOLDER_MARKS:
            if mark in text:
                found.note(f"{name}: a placeholder is still in the rendered text ({mark})")
        if name != entry_name and "http" in text:
            found.note(
                f"{name}: contains 'http' — the base address belongs in the entry alone, "
                "or a part is wrong as soon as it is served from a second host name"
            )
    return found


def check_teaching(register: Register) -> Findings:
    """Every rejection an operation can give has a text written for it."""
    found = Findings()
    for operation_id, kind in register.missing():
        found.note(f"{operation_id}: no text for {kind}")
    return found
