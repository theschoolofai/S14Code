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


def _resolve_pointer(data_model: dict, pointer: str):
    """A minimal JSON Pointer reader: /a/b/0 -> data_model['a']['b'][0].

    Returns None on any miss (unknown key, index, or non-container in the
    path) rather than raising -- an unresolved pointer is a "can't check it"
    case for the caller, not a validator crash.
    """
    node = data_model
    for part in pointer.split("/")[1:]:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.lstrip("-").isdigit() and 0 <= int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def validate_surface(surface: dict, data_model: dict | None = None) -> ValidationResult:
    """Validate one surface (``{root, components:[...]}``) against the catalog.

    ``data_model`` is optional and additive: when supplied, a bindable text
    prop's resolved value is checked for markup too, not just its shape.
    Every existing caller that omits it keeps exactly its prior behavior.
    """
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
            # A ``text`` prop is a literal UI string the developer's schema says
            # is safe to show as-is. Handing it a {"$bind": ...} smuggles agent
            # DATA into a slot that is only ever markup-checked as a literal:
            # _looks_like_markup() sees a dict, not a string, so every content
            # check below silently passes and the client resolves the pointer at
            # render time. Structure and data travel apart — a text prop carries
            # structure, so it must be a scalar.
            if prop.kind == "text" and isinstance(value, (dict, list)):
                well_formed_bind = (isinstance(value, dict) and set(value) == {"$bind"}
                                     and isinstance(value.get("$bind"), str)
                                     and bool(_POINTER.match(value["$bind"])))
                if prop.bindable and well_formed_bind:
                    if data_model is not None:
                        resolved = _resolve_pointer(data_model, value["$bind"])
                        if _looks_like_markup(resolved):
                            rejections.append(Rejection(cid, field_name, Invariant.DATA_NOT_CODE,
                                                         "bound value carries markup"))
                            bad = True
                            break
                    continue  # accepted: a bindable text prop resolves like any binding prop
                reason = (
                    "text property must be a literal string, not a binding"
                    if isinstance(value, dict) and "$bind" in value
                    else "text property must be a literal value"
                )
                rejections.append(Rejection(cid, field_name, Invariant.DATA_NOT_CODE, reason))
                bad = True
                break

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
            # A ``type_ref`` names another catalog type (``fallback``). It must
            # resolve, or an older client following the hop draws nothing and we
            # are back to losing the content the fallback exists to preserve.
            if prop.kind == "type_ref" and value not in COMPONENTS:
                rejections.append(
                    Rejection(cid, field_name, Invariant.CATALOG,
                              f"fallback names unknown component type {value!r}")
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
            # Degrade-gracefully is a harness guarantee, not a hope: a model
            # that remembers to name a fallback and one that doesn't render
            # identically on an older client. New dict, not a mutation of the
            # caller's -- surface["components"] may be read again after this.
            for field_name, prop in spec.props.items():
                if prop.kind == "type_ref" and prop.default and field_name not in comp:
                    comp = {**comp, field_name: prop.default}
            accepted.append(comp)

    return ValidationResult(accepted=accepted, rejections=rejections)
