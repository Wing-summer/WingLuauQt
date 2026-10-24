# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Resolve binding policy: inheritance, exclusions, aliases and dependencies."""

from __future__ import annotations

import copy
import fnmatch

from .catalog import EXCLUDED_ALWAYS, WIDGETS
from .discovery import scan
from .models import DiscoveryReport, JsonObject, NativeClass, object_field, string_list_field
from .type_mapping import is_table_container
from .type_policy import common_types


def matches(name: str, patterns: list[str] | set[str]) -> bool:
    """Match a class name against configured glob patterns."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def resolve(
    config: JsonObject,
) -> tuple[JsonObject, dict[str, NativeClass], list[str], DiscoveryReport]:
    """Resolve selected classes, dependency closure and rejection diagnostics."""
    if config.get("schema_version", 1) != 1:
        raise ValueError("unsupported schema_version; expected 1")
    config = copy.deepcopy(config)
    widgets = object_field(object_field(config, "qt"), "widgets")
    for name in string_list_field(widgets, "include") + string_list_field(widgets, "extra_types"):
        if is_table_container(name):
            raise ValueError(
                f"{name} converts directly to a Luau table; do not select it as a Qt class"
            )
    common_types(config)
    policy = object_field(object_field(config, "qt"), "discovery")
    if not policy.get("enabled", False):
        classes, flags = scan(
            string_list_field(policy, "modules", ["QtCore", "QtGui", "QtWidgets"])
        )
        return config, classes, flags, {}
    if "source" in policy or "path" in policy:
        raise ValueError(
            "qt.discovery accepts policy only; SDK source/path are discovered automatically"
        )
    unknown = set(policy) - {"enabled", "modules", "bases", "blacklist", "dependencies"}
    if unknown:
        raise ValueError("unknown qt.discovery option(s): " + ", ".join(sorted(unknown)))
    if policy.get("dependencies", "transitive") != "transitive":
        raise ValueError("qt.discovery.dependencies currently requires transitive")
    for key in ("modules", "bases", "blacklist"):
        if key in policy and (
            not isinstance(policy[key], list) or not all(isinstance(x, str) for x in policy[key])
        ):
            raise ValueError("qt.discovery." + key + " must be an array of strings")
    modules = policy.get("modules", ["QtCore", "QtGui", "QtWidgets"])
    classes, flags = scan(modules)
    blacklist = (
        list(EXCLUDED_ALWAYS)
        + string_list_field(object_field(config, "exclude"), "classes")
        + string_list_field(policy, "blacklist")
        + [name for name, entry in common_types(config).items() if not entry["enabled"]]
    )
    roots = policy.get("bases", ["QWidget"])

    def ancestors(name: str, seen: set[str] | None = None) -> set[str]:
        """Collect native ancestors without visiting a class twice."""
        seen = set() if seen is None else seen
        if name in seen:
            return set()
        seen.add(name)
        out = {name}
        record = classes.get(name)
        for base in record["bases"] if record is not None else []:
            out.update(ancestors(base, seen))
        return out

    selected: list[str] = []
    rejected: dict[str, str] = {}
    for name, data in sorted(classes.items()):
        lineage = ancestors(name)
        if not lineage.intersection(roots):
            continue
        if any(matches(base, blacklist) for base in lineage):
            rejected[name] = "blacklisted class or ancestor"
        elif data["abstract"]:
            rejected[name] = "abstract class"
        else:
            selected.append(name)
    exclusions = config.setdefault("exclude", {})
    exclusions["classes"] = sorted(
        set(string_list_field(exclusions, "classes") + string_list_field(policy, "blacklist"))
    )
    widgets = config["qt"].setdefault("widgets", {})
    # Explicit includes supplement automatic discovery, and still obey exclusions.
    selected = sorted(
        set(
            selected
            + string_list_field(widgets, "include")
            + string_list_field(widgets, "extra_types")
        )
    )
    selected = [n for n in selected if not any(matches(a, blacklist) for a in ancestors(n))]
    aliases = common_types(config)
    for name, policy in aliases.items():
        if (
            policy["kind"] == "qt"
            and name not in WIDGETS
            and name not in ("QColor", "QFont")
            and not ancestors(name).intersection(roots)
        ):
            raise ValueError(f"No binding backend for common.types.{name}")
    selected = sorted(
        set(selected)
        | {
            name
            for name, p in aliases.items()
            if p["kind"] == "qt"
            and p["enabled"]
            and not any(matches(a, blacklist) for a in ancestors(name))
        }
    )
    exclusions["classes"] = sorted(
        set(exclusions["classes"])
        | {name for name in classes if any(matches(a, blacklist) for a in ancestors(name))}
    )
    widgets["include"] = selected
    dependencies: set[str] = set()
    pending = list(selected)
    while pending:
        name = pending.pop()
        record = classes.get(name)
        for dep in record["dependencies"] if record is not None else []:
            if dep not in dependencies and not matches(dep, blacklist):
                dependencies.add(dep)
                pending.append(dep)
    return (
        config,
        classes,
        flags,
        {
            "selected": selected,
            "rejected": rejected,
            "dependencies": sorted(dependencies),
        },
    )
