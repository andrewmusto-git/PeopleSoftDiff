"""AST-based analyzer for OAA connector scripts.

Walks a connector .py file and emits a structured inventory of:

1. Every oaaclient class instantiation (CustomApplication(...), OAAClient(...),
   HRISProvider(...), etc.) — with the local variable bound to the result.
2. Every method call on those instances — with positional/keyword arg counts.
3. Every attribute reference on oaaclient enum-like classes (OAAPermission.DataRead).
4. Every column-string literal that looks like it indexes a CSV row
   (row["FOO"], row.get("FOO"), df["FOO"]) for schema-contract tests.

The analyzer is conservative: when it cannot trace a variable's class, it
records "unknown" and skips it for signature assertions. This avoids false
positives at the cost of slightly weaker coverage.
"""
from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Class names we recognize as oaaclient entry points. Anything constructed from
# these (or their attribute returns) is tracked. The full set is loaded from the
# SDK spec at runtime; this is the fallback when no spec is provided.
DEFAULT_TRACKED = {
    "OAAClient",
    "CustomApplication",
    "CustomIdPProvider",
    "HRISProvider",
    "OAAPermission",
    "OAAIdentityType",
    "IdPProviderType",
}


@dataclass
class CallSite:
    """One call against an oaaclient object."""
    lineno: int
    col: int
    target_class: str        # e.g. "CustomApplication"
    method: str              # e.g. "add_resource"
    positional_args: int
    keyword_args: list[str] = field(default_factory=list)
    receiver_expr: str = ""  # source-level expression for diagnostics


@dataclass
class Construction:
    lineno: int
    col: int
    var_name: str | None
    class_name: str
    keyword_args: list[str]
    positional_args: int


@dataclass
class AttrRef:
    lineno: int
    col: int
    class_name: str          # e.g. "OAAPermission"
    attr: str                # e.g. "DataRead"


@dataclass
class ColumnRef:
    lineno: int
    col: int
    column: str
    receiver: str            # e.g. "row", "df"


@dataclass
class Inventory:
    script: str
    imports: dict[str, str] = field(default_factory=dict)   # local_name -> dotted SDK name
    constructions: list[Construction] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    attr_refs: list[AttrRef] = field(default_factory=list)
    column_refs: list[ColumnRef] = field(default_factory=list)
    unresolved_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _src(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


class ConnectorAnalyzer(ast.NodeVisitor):
    def __init__(self, source: str, tracked_classes: set[str]):
        self.tree = ast.parse(source)
        self.tracked = tracked_classes
        self.inv = Inventory(script="")
        # local-var -> oaaclient class name (best-effort, no scope tracking)
        self.var_types: dict[str, str] = {}

    # ---- import handling ----

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module or not node.module.startswith("oaaclient"):
            return self.generic_visit(node)
        for alias in node.names:
            local = alias.asname or alias.name
            self.inv.imports[local] = f"{node.module}.{alias.name}"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.startswith("oaaclient"):
                local = alias.asname or alias.name
                self.inv.imports[local] = alias.name

    # ---- class-name resolution ----

    def _resolve_class(self, expr: ast.AST) -> str | None:
        """Resolve an expression to an oaaclient class name if possible."""
        if isinstance(expr, ast.Name):
            local = expr.id
            if local in self.inv.imports:
                dotted = self.inv.imports[local]
                short = dotted.split(".")[-1]
                if short in self.tracked:
                    return short
            if local in self.tracked:
                return local
            return None
        if isinstance(expr, ast.Attribute):
            # oaaclient.templates.CustomApplication or templates.CustomApplication
            if isinstance(expr.value, ast.Name) and expr.value.id in self.inv.imports:
                base = self.inv.imports[expr.value.id]
                short = expr.attr
                if short in self.tracked:
                    return short
        return None

    def _resolve_receiver(self, receiver: ast.AST) -> str | None:
        if isinstance(receiver, ast.Name):
            if receiver.id in self.var_types:
                return self.var_types[receiver.id]
            return self._resolve_class(receiver)
        # Chained calls (foo.add_user().add_perm()) — track the immediate class only.
        if isinstance(receiver, ast.Call):
            return self._resolve_receiver(receiver.func) if isinstance(receiver.func, ast.Attribute) else None
        return None

    # ---- assignments establish var_types ----

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            cls = self._resolve_class(node.value.func)
            if cls:
                pos = len(node.value.args)
                kw = [k.arg for k in node.value.keywords if k.arg]
                self.inv.constructions.append(
                    Construction(
                        lineno=node.lineno,
                        col=node.col_offset,
                        var_name=node.targets[0].id if isinstance(node.targets[0], ast.Name) else None,
                        class_name=cls,
                        keyword_args=kw,
                        positional_args=pos,
                    )
                )
                # Bind var to class
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        self.var_types[tgt.id] = cls
            else:
                # Could be result of a method call returning a tracked object
                # (e.g. user = app.add_local_user(...)). Track if receiver is known.
                if isinstance(node.value.func, ast.Attribute):
                    recv_cls = self._resolve_receiver(node.value.func.value)
                    method = node.value.func.attr
                    if recv_cls:
                        # We can't know the return type without consulting the spec.
                        # Mark as unknown; the SDK-call check still records the call.
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name):
                                # Heuristic: if method is add_local_user -> LocalUser, etc.
                                guess = _guess_return_type(recv_cls, method)
                                if guess:
                                    self.var_types[tgt.id] = guess
        self.generic_visit(node)

    # ---- method calls and attribute references ----

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            recv = node.func.value
            method = node.func.attr
            cls = self._resolve_receiver(recv)
            if cls:
                self.inv.calls.append(
                    CallSite(
                        lineno=node.lineno,
                        col=node.col_offset,
                        target_class=cls,
                        method=method,
                        positional_args=len(node.args),
                        keyword_args=[k.arg for k in node.keywords if k.arg],
                        receiver_expr=_src(recv),
                    )
                )
            elif isinstance(recv, ast.Name) and recv.id not in self.var_types:
                # Could be an oaaclient call we missed. Record for diagnostic.
                if any(method.startswith(p) for p in ("add_", "set_", "push_", "create_", "get_payload", "define_")):
                    self.inv.unresolved_calls.append({
                        "lineno": node.lineno,
                        "method": method,
                        "receiver_expr": _src(recv),
                    })
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            cls = self._resolve_class(node.value)
            if cls and cls in self.tracked:
                # OAAPermission.DataRead style
                self.inv.attr_refs.append(
                    AttrRef(
                        lineno=node.lineno,
                        col=node.col_offset,
                        class_name=cls,
                        attr=node.attr,
                    )
                )
        self.generic_visit(node)

    # ---- column references: row["X"], row.get("X"), df["X"] ----

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            self.inv.column_refs.append(
                ColumnRef(
                    lineno=node.lineno,
                    col=node.col_offset,
                    column=node.slice.value,
                    receiver=node.value.id,
                )
            )
        self.generic_visit(node)

    def analyze(self, path: Path) -> Inventory:
        self.inv.script = str(path)
        self.visit(self.tree)
        # Pick up row.get("X") calls — they appear as Call(func=Attribute(value=Name, attr='get'), args=[Constant])
        for n in ast.walk(self.tree):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name)
                and n.args
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
            ):
                self.inv.column_refs.append(
                    ColumnRef(
                        lineno=n.lineno,
                        col=n.col_offset,
                        column=n.args[0].value,
                        receiver=n.func.value.id,
                    )
                )
        return self.inv


def _guess_return_type(receiver_cls: str, method: str) -> str | None:
    """Heuristic mapping of add_* return values to their template class."""
    table = {
        ("CustomApplication", "add_local_user"): "LocalUser",
        ("CustomApplication", "add_local_group"): "LocalGroup",
        ("CustomApplication", "add_local_role"): "LocalRole",
        ("CustomApplication", "add_resource"): "CustomResource",
        ("CustomApplication", "add_custom_permission"): "CustomPermission",
        ("CustomResource", "add_sub_resource"): "CustomResource",
        ("HRISProvider", "add_employee"): "HRISEmployee",
        ("HRISProvider", "add_group"): "HRISGroup",
        ("CustomIdPProvider", "add_user"): "CustomIdPUser",
        ("CustomIdPProvider", "add_group"): "CustomIdPGroup",
        ("CustomIdPProvider", "add_domain"): "CustomIdPDomain",
    }
    return table.get((receiver_cls, method))


def analyze_file(script: Path, spec: dict[str, Any] | None = None) -> Inventory:
    tracked = set(DEFAULT_TRACKED)
    if spec:
        for mod in spec.get("modules", {}).values():
            tracked.update(mod.get("classes", {}).keys())
    source = script.read_text()
    return ConnectorAnalyzer(source, tracked).analyze(script)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: analyze.py <script.py> [oaa_api.json]", file=sys.stderr)
        return 2
    script = Path(argv[1])
    spec = json.loads(Path(argv[2]).read_text()) if len(argv) > 2 else None
    inv = analyze_file(script, spec)
    print(json.dumps(inv.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
