"""Introspect the installed oaaclient package and emit a structured SDK spec.

The spec drives test generation. It captures every public class, its methods,
their signatures (parameter names, kinds, defaults), and class attributes that
function as enum-like vocabularies (e.g. OAAPermission.DataRead).

Output schema (JSON):

{
  "version": "<oaaclient.__version__ or 'unknown'>",
  "modules": {
    "<module>": {
      "classes": {
        "<ClassName>": {
          "bases": ["..."],
          "methods": {
            "<method>": {
              "params": [
                {"name": "...", "kind": "POSITIONAL_OR_KEYWORD",
                 "has_default": true, "default": "..."}
              ],
              "returns": "<annotation or null>",
              "is_classmethod": false,
              "is_staticmethod": false,
              "doc_first_line": "..."
            }
          },
          "attrs": {"<NAME>": "<repr>"}
        }
      }
    }
  }
}
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

TARGET_MODULES = ["oaaclient.client", "oaaclient.templates", "oaaclient.structures"]


def _param_to_dict(p: inspect.Parameter) -> dict[str, Any]:
    has_default = p.default is not inspect.Parameter.empty
    default_repr: Any = None
    if has_default:
        try:
            default_repr = repr(p.default)
        except Exception:
            default_repr = "<unrepresentable>"
    return {
        "name": p.name,
        "kind": p.kind.name,
        "has_default": has_default,
        "default": default_repr,
        "annotation": (
            str(p.annotation) if p.annotation is not inspect.Parameter.empty else None
        ),
    }


def _method_to_dict(func: Any) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        params = [_param_to_dict(p) for p in sig.parameters.values()]
        returns = (
            str(sig.return_annotation)
            if sig.return_annotation is not inspect.Signature.empty
            else None
        )
    except (TypeError, ValueError):
        params, returns = [], None
    doc = (inspect.getdoc(func) or "").strip().splitlines()
    return {
        "params": params,
        "returns": returns,
        "is_classmethod": isinstance(
            inspect.getattr_static(_owner_for(func), func.__name__, None),
            classmethod,
        )
        if _owner_for(func) is not None
        else False,
        "is_staticmethod": isinstance(
            inspect.getattr_static(_owner_for(func), func.__name__, None),
            staticmethod,
        )
        if _owner_for(func) is not None
        else False,
        "doc_first_line": doc[0] if doc else "",
    }


def _owner_for(func: Any) -> Any:
    qn = getattr(func, "__qualname__", "")
    if "." not in qn:
        return None
    owner_name = qn.rsplit(".", 1)[0]
    mod = sys.modules.get(getattr(func, "__module__", ""))
    return getattr(mod, owner_name, None) if mod else None


def _class_to_dict(cls: type) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for name, member in inspect.getmembers(cls):
        if name.startswith("_") and name not in ("__init__",):
            continue
        if not (inspect.isfunction(member) or inspect.ismethod(member)):
            continue
        # Only methods defined on this class or inherited from another oaaclient class
        defining_mod = getattr(member, "__module__", "")
        if not defining_mod.startswith("oaaclient"):
            continue
        methods[name] = _method_to_dict(member)
    # Class-level constants (e.g. OAAPermission.DataRead). Capture simple scalars.
    attrs: dict[str, str] = {}
    for name, value in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if inspect.isfunction(value) or inspect.ismethod(value) or inspect.isclass(value):
            continue
        if isinstance(value, (str, int, float, bool)):
            attrs[name] = repr(value)
    return {
        "bases": [
            b.__name__ for b in cls.__bases__ if b is not object
        ],
        "methods": methods,
        "attrs": attrs,
    }


def build_spec() -> dict[str, Any]:
    import oaaclient  # noqa: F401

    spec: dict[str, Any] = {
        "version": getattr(sys.modules.get("oaaclient"), "__version__", "unknown"),
        "modules": {},
    }
    for mod_name in TARGET_MODULES:
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except ImportError:
            continue
        classes: dict[str, Any] = {}
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if name.startswith("_"):
                continue
            if obj.__module__ != mod_name:
                continue
            classes[name] = _class_to_dict(obj)
        spec["modules"][mod_name] = {"classes": classes}
    return spec


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else Path("oaa_api.json")
    spec = build_spec()
    out_path.write_text(json.dumps(spec, indent=2, sort_keys=True))
    n_classes = sum(len(m["classes"]) for m in spec["modules"].values())
    n_methods = sum(
        len(c["methods"])
        for m in spec["modules"].values()
        for c in m["classes"].values()
    )
    print(
        f"Wrote {out_path}: oaaclient={spec['version']} "
        f"modules={len(spec['modules'])} classes={n_classes} methods={n_methods}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
