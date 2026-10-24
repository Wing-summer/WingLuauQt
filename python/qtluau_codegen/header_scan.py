#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Conservative public-header scanner using clang's JSON AST.

It emits one registration .cpp and one Luau .d.luau file per input header.
Only scalar/string signatures understood by LuaBridge3 are emitted. Unsupported
members are reported instead of silently producing ill-formed C++.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

from .models import JsonObject, object_field, object_list_field, string_list_field

EXTS = {".h", ".hpp"}
CPP_TO_LUA = {
    "void": "()",
    "bool": "boolean",
    "char": "number",
    "signed char": "number",
    "unsigned char": "number",
    "short": "number",
    "short int": "number",
    "unsigned short": "number",
    "unsigned short int": "number",
    "int": "number",
    "unsigned": "number",
    "unsigned int": "number",
    "long": "number",
    "long int": "number",
    "unsigned long": "number",
    "long long": "number",
    "unsigned long long": "number",
    "float": "number",
    "double": "number",
    "std::string": "string",
    "string": "string",
    "const std::string&": "string",
    "std::string const&": "string",
}


def norm_type(s: str) -> str:
    """Normalize a native type spelling for signature comparisons."""
    s = re.sub(r"\s+", " ", s.strip())
    s = s.replace("std::__cxx11::basic_string<char>", "std::string")
    s = re.sub(r"\bconst\s+std::string\s*&", "const std::string&", s)
    s = re.sub(r"\bstd::string\s+const\s*&", "const std::string&", s)
    s = re.sub(r"\bstd::string\s*&", "std::string&", s)
    return s


def supported_type(s: str, allow_void: bool = True) -> str | None:
    """Return whether the native spelling has a known binding conversion."""
    t = norm_type(s)
    if t in CPP_TO_LUA and (allow_void or t != "void"):
        return t
    return None


def lua_type(s: str) -> str:
    """Map a supported C++ spelling to its Luau declaration type."""
    t = norm_type(s)
    return CPP_TO_LUA.get(t, "any")


def children(node: JsonObject) -> list[JsonObject]:
    """Return typed child declarations from a parsed translation unit."""
    return object_list_field(node, "inner")


def get_name_path(namespaces: list[str], name: str) -> str:
    """Build the qualified declaration name from parent scopes."""
    return "::".join(namespaces + [name]) if namespaces else name


def parse_type_signature(qual_type: str) -> tuple[str, list[str], bool] | None:
    # Clang prints method types as `Return (Args...) const`; accept only regular
    # methods without ref qualifiers, noexcept, templates or function-pointer types.
    """Split a function type into its result and argument spellings."""
    m = re.match(r"^(.+?)\s*\((.*)\)(\s+const)?$", qual_type)
    if not m:
        return None
    result = norm_type(m.group(1))
    suffix = (m.group(3) or "").strip()
    args_text = m.group(2).strip()
    args = (
        [] if not args_text or args_text == "void" else [norm_type(x) for x in args_text.split(",")]
    )
    if any("..." in a or "(" in a or "<" in a for a in args):
        return None
    if suffix not in ("", "const"):
        return None
    return result, args, bool(suffix)


def run_clang(header: pathlib.Path, clang: str, args: list[str]) -> JsonObject:
    """Parse configured headers with Clang and return validated AST records."""
    cmd = [
        clang,
        "-x",
        "c++",
        "-std=c++17",
        "-fsyntax-only",
        "-Xclang",
        "-ast-dump=json",
        *args,
        str(header),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("Clang could not parse header:\n" + proc.stderr[-6000:])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid clang AST JSON: {e}") from e


def _node_origin(
    node: JsonObject, inherited_file: pathlib.Path, inherited_included: bool
) -> tuple[pathlib.Path | None, bool, bool]:
    """Track physical source and include ancestry from Clang's partially elided JSON locations."""
    loc = object_field(node, "loc")
    begin = object_field(object_field(node, "range"), "begin")
    candidates = [
        loc.get("file"),
        begin.get("file"),
        object_field(loc, "spellingLoc").get("file"),
        object_field(begin, "spellingLoc").get("file"),
    ]
    included = inherited_included
    if (
        loc.get("includedFrom")
        or begin.get("includedFrom")
        or object_field(loc, "spellingLoc").get("includedFrom")
        or object_field(begin, "spellingLoc").get("includedFrom")
    ):
        included = True
    for candidate in candidates:
        if candidate and not str(candidate).startswith("<"):
            try:
                file_path = pathlib.Path(candidate).resolve()
                return (
                    file_path,
                    file_path != pathlib.Path(inherited_file).resolve(),
                    file_path != pathlib.Path(inherited_file).resolve(),
                )
            except (OSError, RuntimeError):
                pass
    return None, included, included


def collect_records(
    root: JsonObject, input_header: pathlib.Path
) -> tuple[list[JsonObject], list[str]]:
    """Collect supported native record declarations from the translation unit."""
    records: list[JsonObject] = []
    diagnostics: list[str] = []
    input_header = pathlib.Path(input_header).resolve()

    def visit(
        node: JsonObject,
        namespaces: list[str],
        inherited_file: pathlib.Path | None,
        inherited_included: bool,
    ) -> None:
        """Visit child AST declarations while retaining their qualified scope."""
        explicit_file, from_include, _ = _node_origin(node, input_header, inherited_included)
        source_file = explicit_file or inherited_file
        kind = node.get("kind")
        if kind == "NamespaceDecl":
            nm = node.get("name")
            nested = namespaces + ([nm] if nm else [])
            for c in children(node):
                visit(c, nested, source_file, from_include)
            return

        if (
            kind in ("CXXRecordDecl", "RecordDecl")
            and node.get("completeDefinition")
            and node.get("name")
            and not node.get("isImplicit")
        ):
            # AST JSON contains declarations pulled in through transitive includes. Only emit
            # record definitions belonging to the current input header.
            if from_include or (source_file is not None and source_file != input_header):
                return
            name = node["name"]
            if name.startswith("__anon") or node.get("tagUsed") not in (
                "class",
                "struct",
            ):
                return

            access_default = "private" if node.get("tagUsed") == "class" else "public"
            access = access_default
            methods: list[JsonObject] = []
            constructors: list[list[str]] = []
            properties: list[JsonObject] = []
            explicitly_declared_constructor = False
            has_public_constructor = False
            for member in children(node):
                mk = member.get("kind")
                if mk == "AccessSpecDecl":
                    access = member.get("access", access)
                    continue

                member_access = member.get("access", access)
                if mk == "CXXConstructorDecl" and not member.get("isImplicit"):
                    explicitly_declared_constructor = True
                if member_access != "public" or member.get("isImplicit") or member.get("isDeleted"):
                    continue

                if mk == "CXXConstructorDecl":
                    has_public_constructor = True
                    pts = [
                        norm_type(object_field(x, "type").get("qualType", ""))
                        for x in children(member)
                        if x.get("kind") == "ParmVarDecl"
                    ]
                    if all(supported_type(t, allow_void=False) for t in pts):
                        constructors.append(pts)
                    elif pts:
                        diagnostics.append(
                            f"skip unsupported constructor {get_name_path(namespaces, name)}({', '.join(pts)})"
                        )
                elif mk == "CXXMethodDecl" and member.get("name"):
                    mname = member["name"]
                    if mname in {
                        "begin",
                        "end",
                        "cbegin",
                        "cend",
                        "rbegin",
                        "rend",
                        "crbegin",
                        "crend",
                        "constBegin",
                        "constEnd",
                    } or "iterator" in object_field(member, "type").get("qualType", ""):
                        diagnostics.append(
                            f"{get_name_path(namespaces, name)}::{mname}: C++ iterator API excluded; use Luau table iteration"
                        )
                        continue
                    qtype = object_field(member, "type").get("qualType", "")
                    sig = parse_type_signature(qtype)
                    pts = [
                        norm_type(object_field(x, "type").get("qualType", ""))
                        for x in children(member)
                        if x.get("kind") == "ParmVarDecl"
                    ]
                    if sig is None:
                        diagnostics.append(
                            f"skip unsupported method {get_name_path(namespaces, name)}::{mname}: {qtype}"
                        )
                        continue
                    result, signature_args, const_method = sig
                    if len(pts) != len(signature_args):
                        pts = signature_args
                    static = member.get("storageClass") == "static"
                    if (
                        not supported_type(result)
                        or (result != "void" and not supported_type(result, allow_void=False))
                        or not all(supported_type(t, allow_void=False) for t in pts)
                    ):
                        diagnostics.append(
                            f"skip unsupported method {get_name_path(namespaces, name)}::{mname}: {qtype}"
                        )
                        continue
                    if any("*" in t or "&&" in t for t in pts) or "*" in result or "&&" in result:
                        diagnostics.append(
                            f"skip pointer/rvalue-reference method {get_name_path(namespaces, name)}::{mname}"
                        )
                        continue
                    methods.append(
                        {
                            "name": mname,
                            "return": result,
                            "params": pts,
                            "const": const_method,
                            "static": static,
                        }
                    )
                elif mk == "FieldDecl" and member.get("name") and not member.get("isBitfield"):
                    t = norm_type(object_field(member, "type").get("qualType", ""))
                    if supported_type(t, allow_void=False) and not any(
                        x in t for x in ("*", "&", "const ")
                    ):
                        properties.append({"name": member["name"], "type": t})

            # C++ implicitly declares a default constructor only if no constructor was declared.
            # Never synthesize one for abstract classes or classes with private/deleted constructors.
            is_abstract = bool(object_field(node, "definitionData").get("isAbstract"))
            if not explicitly_declared_constructor and not is_abstract:
                constructors.append([])

            bases: list[str] = []
            for base in object_list_field(node, "bases"):
                if base.get("access", access_default) != "public":
                    continue
                base_name = norm_type(
                    object_field(base, "type").get("desugaredQualType")
                    or object_field(base, "type").get("qualType", "")
                )
                if base_name and not any(
                    x in base_name for x in ("<", "*", "&", "<dependent type>")
                ):
                    bases.append(base_name)
                else:
                    diagnostics.append(
                        f"skip unsupported base of {get_name_path(namespaces, name)}: {base_name}"
                    )

            records.append(
                {
                    "name": name,
                    "cpp": get_name_path(namespaces, name),
                    "namespaces": namespaces,
                    "bases": bases,
                    "methods": methods,
                    "constructors": constructors,
                    "has_public_constructor": has_public_constructor
                    or (not explicitly_declared_constructor and not is_abstract),
                    "properties": properties,
                    "kind": node.get("tagUsed"),
                    "abstract": is_abstract,
                }
            )
            # Do not recurse into nested class definitions in this conservative scanner.
            return

        for c in children(node):
            visit(c, namespaces, source_file, from_include)

    visit(root, [], input_header, False)
    unique: dict[str, JsonObject] = {}
    for rec in records:
        unique[rec["cpp"]] = rec
    return list(unique.values()), diagnostics


def safe_identifier(s: str) -> str:
    """Convert a native name into a deterministic C++ helper identifier."""
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def method_cast(rec: JsonObject, meth: JsonObject) -> str:
    """Render the overload-disambiguating native member pointer expression."""
    args = ", ".join(meth["params"])
    if meth["static"]:
        pointer = f"{meth['return']} (*)({args})"
    else:
        const = " const" if meth["const"] else ""
        pointer = f"{meth['return']} ({rec['cpp']}::*)({args}){const}"
    return f"static_cast<{pointer}>(&{rec['cpp']}::{meth['name']})"


def namespace_chain(namespaces: list[str]) -> str:
    """Return qualified namespace components enclosing a declaration."""
    return "".join(f".beginNamespace({json.dumps(x)})" for x in namespaces)


def emit_cpp(
    header: pathlib.Path,
    records: list[JsonObject],
    function_name: str,
    include_name: str | None = None,
) -> str:
    """Write C++ registrations for supported scanned records."""
    include_name = include_name or header.name
    lines = [
        "// Generated by qtluau_codegen.header_scan; do not edit.",
        '#include "qtluau/bindings.hpp"',
        f'#include "{include_name}"',
        "",
        f"void {function_name}(lua_State *L)",
        "{",
    ]
    for rec in records:
        if not rec["methods"] and not rec["constructors"] and not rec["properties"]:
            continue
        bound_bases = string_list_field(rec, "bound_bases")
        if bound_bases:
            template_args = ", ".join([rec["cpp"], *bound_bases])
            chain = (
                "luabridge::getGlobalNamespace(L)"
                + namespace_chain(rec["namespaces"])
                + f".deriveClass<{template_args}>({json.dumps(rec['name'])})"
            )
        else:
            chain = (
                "luabridge::getGlobalNamespace(L)"
                + namespace_chain(rec["namespaces"])
                + f".beginClass<{rec['cpp']}>({json.dumps(rec['name'])})"
            )
        lines.append("    " + chain)
        if not rec.get("abstract"):
            for ctor in rec["constructors"]:
                types = ", ".join(ctor)
                lines.append(f"        .addConstructor<void (*)({types})>()")
        methods_by_name: dict[str, list[JsonObject]] = {}
        for meth in rec["methods"]:
            if meth["static"]:
                continue
            methods_by_name.setdefault(meth["name"], []).append(meth)
        for name in sorted(methods_by_name):
            group = sorted(
                methods_by_name[name],
                key=lambda x: (x["static"], x["const"], x["params"], x["return"]),
            )
            static_flags = {m["static"] for m in group}
            if len(static_flags) > 1:
                lines.append(
                    f"        // WARNING: mixed static/non-static overload group {name!r} was omitted"
                )
                continue
            api = "addStaticFunction" if group[0]["static"] else "addFunction"
            casts = ", ".join(method_cast(rec, meth) for meth in group)
            lines.append(f"        .{api}({json.dumps(name)}, {casts})")
        for prop in rec["properties"]:
            lines.append(
                f"        .addProperty({json.dumps(prop['name'])}, &{rec['cpp']}::{prop['name']})"
            )
        lines.append("        .endClass()")
        for _ in rec["namespaces"]:
            lines.append("        .endNamespace()")
        lines[-1] += ";"
        lines.append(f"    qtluau::guardClassMethods<{rec['cpp']}>(L);")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def lua_type_name(cpp_name: str) -> str:
    """Return the Luau-facing name of a native record type."""
    return "_cpp_" + safe_identifier(cpp_name)


def can_emit_record(rec: JsonObject) -> bool:
    """Check whether all required record members have supported conversions."""
    return bool(rec["methods"] or rec["constructors"] or rec["properties"])


def record_constructor_type(rec: JsonObject) -> str:
    """Render the Luau constructor signature for a native record."""
    signatures: list[str] = []
    if not rec.get("abstract"):
        for ctor in rec["constructors"]:
            args = ", ".join(f"arg{i + 1}: {lua_type(t)}" for i, t in enumerate(ctor))
            signatures.append(f"(({args}) -> {lua_type_name(rec['cpp'])})")
    fields: list[str] = []
    for method in rec["methods"]:
        if method["static"]:
            args = ", ".join(f"arg{i + 1}: {lua_type(t)}" for i, t in enumerate(method["params"]))
            fields.append(f"{method['name']}: ({args}) -> {lua_type(method['return'])}")
    if fields:
        signatures.append("{ " + ", ".join(fields) + " }")
    return " & ".join(signatures) if signatures else "{}"


def emit_namespace_tree(records: list[JsonObject]) -> str:
    """Emit one merged namespace table declaration for the selected record list."""
    tree: JsonObject = {}
    for rec in records:
        if not can_emit_record(rec):
            continue
        path = rec["namespaces"] + [rec["name"]]
        cursor = tree
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = {"__type__": record_constructor_type(rec)}

    def render(node: JsonObject, indent: int) -> str:
        """Render a supported native declaration into binding source."""
        fields: list[str] = []
        for key in sorted(node):
            child = node[key]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(
                    f"namespace or class name cannot be represented safely in Luau table type: {key}"
                )
            if "__type__" in child:
                value = child["__type__"]
            else:
                value = render(child, indent + 1)
            fields.append("    " * (indent + 1) + f"{key}: {value},")
        if fields:
            fields[-1] = fields[-1].rstrip(",")
        return "{\n" + "\n".join(fields) + "\n" + "    " * indent + "}"

    if not tree:
        return ""
    return "\n".join(
        f"declare {name}: "
        + (tree[name]["__type__"] if "__type__" in tree[name] else render(tree[name], 0))
        for name in sorted(tree)
    )


def emit_def(records: list[JsonObject]) -> str:
    """Write matching Luau definitions for the selected native records."""
    lines = ["-- Generated by qtluau_codegen.header_scan; conservative public API subset."]
    for rec in records:
        if not rec["methods"] and not rec["constructors"] and not rec["properties"]:
            continue
        lua_name = lua_type_name(rec["cpp"])
        bound_bases = string_list_field(rec, "bound_bases")
        base = (
            " extends " + " & ".join(lua_type_name(b) for b in bound_bases) if bound_bases else ""
        )
        lines.append(f"declare extern type {lua_name}{base} with")
        for prop in rec["properties"]:
            lines.append(f"    {prop['name']}: {lua_type(prop['type'])}")
        methods_by_name: dict[str, list[JsonObject]] = {}
        for meth in rec["methods"]:
            if meth["static"]:
                continue
            methods_by_name.setdefault(meth["name"], []).append(meth)
        for method_name in sorted(methods_by_name):
            signatures: list[str] = []
            for meth in sorted(
                methods_by_name[method_name], key=lambda x: (x["params"], x["return"])
            ):
                args = ", ".join(f"arg{i + 1}: {lua_type(t)}" for i, t in enumerate(meth["params"]))
                receiver = "" if meth["static"] else f"self: {lua_name}" + (", " if args else "")
                signatures.append(f"(({receiver}{args}) -> {lua_type(meth['return'])})")
            lines.append(f"    {method_name}: " + " & ".join(signatures))
        lines.append("end\n")
    return "\n".join(lines)


def main() -> int:
    """Parse header-scan arguments and return a generation exit status."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        action="append",
        required=True,
        help="header file or directory; repeatable",
    )
    p.add_argument("--output", type=pathlib.Path, required=True)
    p.add_argument("--clang", default="clang++")
    p.add_argument("-I", dest="includes", action="append", default=[])
    p.add_argument("-D", dest="defines", action="append", default=[])
    p.add_argument("--clang-arg", action="append", default=[])
    p.add_argument("--recursive", action="store_true")
    args = p.parse_args()
    headers: list[pathlib.Path] = []
    for input_path in args.input:
        path = pathlib.Path(input_path)
        if path.is_dir():
            glob = path.rglob("*") if args.recursive else path.glob("*")
            headers.extend(x for x in glob if x.is_file() and x.suffix.lower() in EXTS)
        elif path.is_file() and path.suffix.lower() in EXTS:
            headers.append(path)
        else:
            p.error(f"not a supported header or directory: {input_path}")
    headers = sorted(set(x.resolve() for x in headers))
    if not headers:
        p.error("no .h/.hpp headers found")
    common_root = pathlib.Path(os.path.commonpath([str(h.parent) for h in headers])).resolve()
    clang_args = (
        [f"-I{x}" for x in args.includes] + [f"-D{x}" for x in args.defines] + args.clang_arg
    )
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: JsonObject = {"headers": [], "diagnostics": [], "registration_order": []}
    failed = False
    entries: list[JsonObject] = []

    # Parse every header first so cross-header bases can be resolved and registration ordered.
    for header in headers:
        rel_path = header.relative_to(common_root)
        relative_stem = rel_path.with_suffix("")
        rel_key = relative_stem.as_posix()
        hash_suffix = hashlib.sha1(rel_key.encode("utf-8")).hexdigest()[:8]
        stem = safe_identifier(rel_key)
        function_name = f"register_{stem}_{hash_suffix}_bindings"
        entry: JsonObject = {
            "header_path": header,
            "relative_stem": relative_stem,
            "function": function_name,
            "records": [],
            "diagnostics": [],
        }
        try:
            ast = run_clang(header, args.clang, clang_args)
            entry["records"], entry["diagnostics"] = collect_records(ast, header)
        except Exception as exc:
            print(f"error: {header}: {exc}", file=sys.stderr)
            failed = True
            manifest["diagnostics"].append(f"{header}: {exc}")
        entries.append(entry)

    # Keep one generated registration owner per fully-qualified C++ type.
    record_owner: dict[str, JsonObject] = {}
    entry_records: dict[str, list[JsonObject]] = {}
    for entry in entries:
        retained: list[JsonObject] = []
        for rec in entry["records"]:
            if not can_emit_record(rec):
                continue
            previous = record_owner.get(rec["cpp"])
            if previous is not None:
                entry["diagnostics"].append(
                    f"duplicate binding type {rec['cpp']} also declared by {previous['header_path']}; duplicate registration skipped"
                )
                continue
            record_owner[rec["cpp"]] = entry
            retained.append(rec)
        entry["records"] = retained
        entry_records[entry["function"]] = retained

    # Resolve only bases that will actually be registered by this generation. This prevents
    # deriveClass() from referencing a LuaBridge class key that the user never asked us to bind.
    all_types = set(record_owner)
    for entry in entries:
        for rec in entry["records"]:
            rec["bound_bases"] = []
            for raw_base in string_list_field(rec, "bases"):
                candidates = [raw_base]
                if "::" not in raw_base:
                    for n in range(len(rec["namespaces"]), -1, -1):
                        candidate = "::".join(rec["namespaces"][:n] + [raw_base])
                        if candidate not in candidates:
                            candidates.append(candidate)
                resolved = next((c for c in candidates if c in all_types), None)
                if resolved:
                    rec["bound_bases"].append(resolved)
                else:
                    entry["diagnostics"].append(
                        f"base {raw_base} of {rec['cpp']} was not selected from scanned headers; generated class omits Lua inheritance"
                    )

    # Build dependencies between per-header registration functions using bound inheritance.
    dependencies: dict[str, set[str]] = {
        entry["function"]: set() for entry in entries if entry["records"]
    }
    owner_for_type = {cpp: entry["function"] for cpp, entry in record_owner.items()}
    for entry in entries:
        for rec in entry["records"]:
            for base in string_list_field(rec, "bound_bases"):
                owner = owner_for_type[base]
                if owner != entry["function"]:
                    dependencies[entry["function"]].add(owner)

    remaining = {key: set(value) for key, value in dependencies.items()}
    registration_order: list[str] = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            failed = True
            cycle = ", ".join(sorted(remaining))
            manifest["diagnostics"].append(f"registration dependency cycle detected among: {cycle}")
            break
        for key in ready:
            registration_order.append(key)
            remaining.pop(key)
        for deps in remaining.values():
            deps.difference_update(ready)

    # Emit one source and one definition file per input header, preserving directory structure.
    all_records: list[JsonObject] = []
    for entry in entries:
        header = entry["header_path"]
        rel = entry["relative_stem"]
        target_dir = args.output / rel.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        cpp_path = target_dir / f"{rel.name}_binding.cpp"
        def_path = target_dir / f"{rel.name}.d.luau"
        records = entry["records"]
        include_name = header.relative_to(common_root).as_posix()
        cpp_path.write_text(
            emit_cpp(header, records, entry["function"], include_name), encoding="utf-8"
        )
        def_path.write_text(
            emit_def(records) + ("\n" + emit_namespace_tree(records) if records else "") + "\n",
            encoding="utf-8",
        )
        all_records.extend(records)
        manifest["headers"].append(
            {
                "header": header.as_posix(),
                "cpp": str(cpp_path),
                "definition": str(def_path),
                "registration_function": entry["function"],
                "records": records,
                "dependencies": sorted(dependencies.get(entry["function"], set())),
            }
        )
        manifest["diagnostics"].extend(f"{header}: {message}" for message in entry["diagnostics"])
        print(
            f"generated {cpp_path.relative_to(args.output)} and {def_path.relative_to(args.output)}: {len(records)} public type candidates"
        )

    # A convenient umbrella function calls header-specific registrations in base-first order.
    declarations = [
        "// Generated by qtluau_codegen.header_scan; do not edit.",
        '#include "qtluau/bindings.hpp"',
        "",
    ]
    function_by_name = {entry["function"]: entry for entry in entries if entry["records"]}
    for function_name in registration_order:
        declarations.append(f"void {function_name}(lua_State *L);")
    declarations.extend(["", "void register_all_scanned_bindings(lua_State *L)", "{"])
    for function_name in registration_order:
        declarations.append(f"    {function_name}(L);")
    declarations.append("}")
    (args.output / "register_all_scanned_bindings.cpp").write_text(
        "\n".join(declarations) + "\n", encoding="utf-8"
    )

    # One merged Definition file avoids duplicate namespace-table declarations when loading
    # the per-header Definitions together in a language server.
    all_records = [
        record for name in registration_order for record in function_by_name[name]["records"]
    ]
    aggregate_def = emit_def(all_records)
    namespace_def = emit_namespace_tree(all_records)
    if namespace_def:
        aggregate_def += "\n" + namespace_def
    (args.output / "all.d.luau").write_text(aggregate_def + "\n", encoding="utf-8")
    manifest["registration_order"] = registration_order
    (args.output / "binding_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    for message in manifest["diagnostics"]:
        print("warning: " + message, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
