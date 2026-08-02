"""The injection wall: three invariants, enforced deterministically.

Every surface an agent produces passes through :func:`validate_surface`
before it reaches the client. The wall does not ask a model to be careful.
It checks structure:

  1. Catalog invariant      every component ``type`` is in the catalog
  2. Data-not-code invariant no property smuggles markup, a handler, or a URL
  3. Event invariant         every action name is registered

A rejection is specific: it names the component, the offending field, and the
invariant it broke. The safe part of a surface still renders; only the
offending components are dropped, so a single poisoned node cannot blank the
screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import COMPONENTS, REGISTERED_ACTIONS

# Markup / script / javascript-url smells. A ``text`` or ``binding`` value that
# matches is treated as an attempt to reach execution and is refused.
_MARKUP = re.compile(r"<[a-z!/][^>]*>|</[a-z]+>", re.I)
_JS_URL = re.compile(r"^\s*(javascript|data|vbscript):", re.I)
_HANDLER = re.compile(r"^on[a-z]+$", re.I)  # onclick, onerror, onload, ...
# A JSON Pointer: /rows, /pending/params, /gauges/0/label. Deliberately narrow.
# A model asked for a pointer will reach for a template language if the rule
# lets it — one composed `/readings[0].value|toFixed(1)`, a filter call inside
# a value. Nothing evaluates it, so nothing ran; but data-not-code is the claim
# that a bound value is READ and never RUN, and a rule loose enough to accept an
# expression is a rule that only holds because the renderer happens to be dumb.
_POINTER = re.compile(r"^/[A-Za-z0-9_\-./~]*$")


class Invariant:
    CATALOG = "catalog"
    DATA_NOT_CODE = "data-not-code"
    EVENT = "event"


@dataclass(frozen=True)
class Rejection:
    component_id: str
    field: str
    invariant: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "field": self.field,
            "invariant": self.invariant,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ValidationResult:
    accepted: list[dict]  # components that render
    rejections: list[Rejection]
    #: Structural problems in the ACCEPTED set: a root that no component
    #: carries, a child reference that resolves to nothing. Deliberately not
    #: rejections and deliberately not a fourth invariant — a surface can be
    #: perfectly safe and still not be a tree, and calling that an attack would
    #: make ``ok`` mean two unrelated things at once.
    structure: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Safe: nothing broke one of the three invariants."""
        return not self.rejections

    @property
    def coherent(self) -> bool:
        """Renderable: the accepted components form one reachable tree."""
        return not self.structure


def _looks_like_markup(value) -> bool:
    return isinstance(value, str) and bool(_MARKUP.search(value))


def _looks_like_js_url(value) -> bool:
    return isinstance(value, str) and bool(_JS_URL.match(value))


def validate_surface(surface: dict) -> ValidationResult:
    """Validate one surface (``{root, components:[...]}``) against the catalog."""
    accepted: list[dict] = []
    rejections: list[Rejection] = []
    components = surface.get("components", [])

    for comp in components:
        cid = comp.get("id", "<no id>")
        ctype = comp.get("type")

        # 1. Catalog invariant.
        if ctype not in COMPONENTS:
            rejections.append(
                Rejection(cid, "type", Invariant.CATALOG, f"unknown component type {ctype!r}")
            )
            continue

        spec = COMPONENTS[ctype]
        bad = False
        # An explicit null means "this prop was not set". It is not markup, not
        # a handler and not an unregistered action, so it breaks no invariant —
        # but compared against an enum's allowed values it would look like one,
        # and cost the whole component. Stripped here so nothing downstream has
        # to decide whether `null` means absent or means something.
        comp = {key: value for key, value in comp.items() if value is not None}
        for field_name, value in comp.items():
            if field_name in ("id", "type", "children"):
                if field_name == "children":  # refs; resolved by _structural_problems below
                    continue
                continue

            # 2. Data-not-code: the property must be one the schema declares.
            # An unknown property shaped like a DOM handler (onclick, onerror)
            # gets a specific message; both cases break data-not-code.
            if field_name not in spec.props:
                reason = (
                    "event-handler property is never allowed"
                    if _HANDLER.match(field_name)
                    else f"unknown property {field_name!r} on {ctype}"
                )
                rejections.append(Rejection(cid, field_name, Invariant.DATA_NOT_CODE, reason))
                bad = True
                break

            prop = spec.props[field_name]
            if prop.kind in ("text", "binding") and _looks_like_markup(value):
                rejections.append(
                    Rejection(cid, field_name, Invariant.DATA_NOT_CODE, "value carries markup")
                )
                bad = True
                break
            if _looks_like_js_url(value):
                rejections.append(
                    Rejection(cid, field_name, Invariant.DATA_NOT_CODE, "value is a script/data URL")
                )
                bad = True
                break
            if prop.kind == "binding" and not (isinstance(value, dict) and "$bind" in value):
                # A binding must be an explicit {"$bind": "/pointer"}. Inline
                # text where a binding belongs is how markup sneaks in.
                rejections.append(
                    Rejection(cid, field_name, Invariant.DATA_NOT_CODE, "binding must be {'$bind': '/pointer'}")
                )
                bad = True
                break
            if prop.kind == "binding" and not _POINTER.match(value["$bind"]):
                rejections.append(
                    Rejection(cid, field_name, Invariant.DATA_NOT_CODE, f"invalid JSON Pointer {value['$bind']!r}")
                )
                bad = True
                break
            if prop.kind == "enum" and value not in prop.values:
                rejections.append(
                    Rejection(cid, field_name, Invariant.DATA_NOT_CODE, f"{value!r} not in {prop.values}")
                )
                bad = True
                break

            # 3. Event invariant: an action references a registered name only.
            if prop.kind == "action":
                action_name = value.get("action") if isinstance(value, dict) else None
                if action_name not in REGISTERED_ACTIONS:
                    rejections.append(
                        Rejection(cid, field_name, Invariant.EVENT, f"unregistered action {action_name!r}")
                    )
                    bad = True
                    break

        if not bad:
            accepted.append(comp)

    return ValidationResult(accepted=accepted, rejections=rejections,
                            structure=_structural_problems(surface, accepted))


def _structural_problems(surface: dict, accepted: list[dict]) -> list[str]:
    """Whether the ACCEPTED components still form a tree someone can render.

    Checked against what survived the wall, not against what arrived: a
    component dropped for an invariant leaves a hole in whatever named it as a
    child, and the caller is holding the pruned surface, not the original one.
    """
    problems: list[str] = []
    if not accepted:
        problems.append("no components survived; there is nothing to render")
        return problems

    ids = {comp.get("id") for comp in accepted}
    root = surface.get("root")
    if root not in ids:
        problems.append(f"root {root!r} is not among the components")
    for comp in accepted:
        for child in comp.get("children", []) or []:
            if child not in ids:
                problems.append(f"{comp.get('id')!r} names a child {child!r} that is not present")

    # A binding whose pointer leads nowhere draws an empty widget, which reads
    # as missing data rather than as a broken interface. Only checked when a
    # dataModel was actually supplied: callers validate bare component trees in
    # places, and flagging every binding there would be noise, not a finding.
    data_model = surface.get("dataModel")
    if isinstance(data_model, dict):
        for comp in accepted:
            for field_name, value in comp.items():
                if not (isinstance(value, dict) and "$bind" in value):
                    continue
                if not _resolves(str(value["$bind"]), data_model):
                    problems.append(
                        f"{comp.get('id')!r} binds {field_name} to {value['$bind']!r}, "
                        "which resolves to nothing in the data model")
    return problems


def _resolves(pointer: str, data_model: dict) -> bool:
    """Whether a JSON Pointer reaches something in the data model.

    Deliberately strict about the syntax: a model that writes ``/metrics[0].alarm``
    has written JavaScript member access, not a pointer, and the value it wanted
    is not going to arrive.
    """
    if pointer == "":
        return True
    if not pointer.startswith("/"):
        return False
    node: object = data_model
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return False
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return False
            node = node[int(token)]
        else:
            return False
    return True
