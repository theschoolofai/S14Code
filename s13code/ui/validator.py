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
_MARKUP = re.compile(r"<[a-z!/][^>]*>|</[a-z]+>", re.I)
_JS_URL = re.compile(r"^\s*(javascript|data|vbscript):", re.I)
_HANDLER = re.compile(r"^on[a-z]+$", re.I)  # onclick, onerror, onload, ...
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


def _resolve_ptr(data_model: dict, pointer: str):
    """Walk a JSON Pointer (e.g. /rows/0/label) into data_model."""
    node = data_model
    for key in pointer.split("/")[1:]:
        if not isinstance(node, (dict, list)):
            return None
        try:
            node = node[int(key)] if isinstance(node, list) else node[key]
        except (KeyError, IndexError, ValueError):
            return None
    return node


def validate_surface(surface: dict) -> ValidationResult:
    """Validate one surface (``{root, components:[...]}``) against the catalog."""
    accepted: list[dict] = []
    rejections: list[Rejection] = []
    data_model: dict = surface.get("dataModel") or {}
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
            # A text-kind prop may carry a {"$bind": "/pointer"} dict instead of a
            # literal string — the renderer resolves it at display time.  Check the
            # bound dataModel value now; markup there is the same invariant violation.
            if (prop.kind == "text"
                    and isinstance(value, dict) and "$bind" in value
                    and isinstance(value["$bind"], str)):
                bound = _resolve_ptr(data_model, value["$bind"])
                if _looks_like_markup(bound):
                    rejections.append(
                        Rejection(cid, field_name, Invariant.DATA_NOT_CODE,
                                  f"dataModel[{value['$bind']!r}] carries markup")
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

    return ValidationResult(accepted=accepted, rejections=rejections)
