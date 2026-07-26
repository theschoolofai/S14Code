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
from dataclasses import dataclass

from .catalog import COMPONENTS, REGISTERED_ACTIONS

# Markup / script / javascript-url smells. A ``text`` or ``binding`` value that
# matches is treated as an attempt to reach execution and is refused.
_MARKUP = re.compile(r"<[a-z!/][^>]*>|</[a-z]+>", re.IGNORECASE)
_JS_URL = re.compile(r"^\s*(javascript|data|vbscript):", re.IGNORECASE)
_HANDLER = re.compile(r"^on[a-z]+$", re.IGNORECASE)  # onclick, onerror, onload, ...
_POINTER = re.compile(r"^/[^\s]*$")  # a JSON Pointer: /rows, /pending/params


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

    @property
    def ok(self) -> bool:
        return not self.rejections


def _looks_like_markup(value) -> bool:
    return isinstance(value, str) and bool(_MARKUP.search(value))


def _looks_like_js_url(value) -> bool:
    return isinstance(value, str) and bool(_JS_URL.match(value))


def _resolve_pointer(data_model, pointer: str) -> tuple[bool, object]:
    """Resolve the same simple JSON Pointer shape the render clients consume.

    Missing pointers preserve the existing nullable-binding behaviour. The
    boolean distinguishes a missing value from a present JSON ``null``.
    """
    current = data_model
    for segment in pointer.split("/")[1:]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index < len(current):
                current = current[index]
                continue
        return False, None
    return True, current


def _unsafe_bound_value(value, seen: set[int] | None = None) -> str | None:
    """Return the data-not-code reason for unsafe referenced data, if any."""
    if isinstance(value, str):
        if _looks_like_markup(value):
            return "bound value carries markup"
        if _looks_like_js_url(value):
            return "bound value is a script/data URL"
        return None
    if not isinstance(value, (dict, list, tuple)):
        return None

    seen = seen or set()
    identity = id(value)
    if identity in seen:
        return None
    seen.add(identity)
    values = value.values() if isinstance(value, dict) else value
    for nested in values:
        reason = _unsafe_bound_value(nested, seen)
        if reason:
            return reason
    return None


def validate_surface(surface: dict) -> ValidationResult:
    """Validate one surface (``{root, components:[...]}``) against the catalog."""
    accepted: list[dict] = []
    rejections: list[Rejection] = []
    components = surface.get("components", [])
    data_model = surface.get("dataModel", {})

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
        for field_name, value in comp.items():
            if field_name in ("id", "type", "children"):
                if field_name == "children":  # children are refs; validated by tree walk elsewhere
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
            if prop.kind == "binding":
                found, bound_value = _resolve_pointer(data_model, value["$bind"])
                reason = _unsafe_bound_value(bound_value) if found else None
                if reason:
                    rejections.append(
                        Rejection(cid, field_name, Invariant.DATA_NOT_CODE, reason)
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

    return ValidationResult(accepted=accepted, rejections=rejections)
