# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Compile member exclusions once rather than normalizing every pattern per call."""

from __future__ import annotations

import fnmatch
import functools
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MemberExclusions:
    """Index literal exclusions and compile the remaining shell-style patterns."""

    #: Exact class/member names.
    names: frozenset[str]
    #: Exact normalized overload signatures.
    signatures: frozenset[str]
    #: Signature heads used by convenience adapters without overload metadata.
    adapters: frozenset[str]
    #: Broad wildcard exclusions.
    name_patterns: tuple[re.Pattern[str], ...]
    #: Normalized signature wildcard exclusions.
    signature_patterns: tuple[re.Pattern[str], ...]
    #: Signature-head wildcard exclusions for convenience adapters.
    adapter_patterns: tuple[re.Pattern[str], ...]

    def matches(self, owner: str, method: str, args: list[str] | None) -> bool:
        """Match one member, preserving overload-free adapter semantics."""
        broad = f"{owner}::{method}"
        if broad in self.names or any(pattern.match(broad) for pattern in self.name_patterns):
            return True
        if args is None:
            return broad in self.adapters or any(
                pattern.match(broad) for pattern in self.adapter_patterns
            )
        if not self.signatures and not self.signature_patterns:
            return False
        exact = "".join((broad + "(" + ",".join(args) + ")").split())
        return exact in self.signatures or any(
            pattern.match(exact) for pattern in self.signature_patterns
        )


def split_patterns(patterns: set[str]) -> tuple[frozenset[str], tuple[re.Pattern[str], ...]]:
    """Separate direct lookups from fnmatch-compatible compiled expressions."""
    literals: set[str] = set()
    wildcards: list[re.Pattern[str]] = []
    for pattern in sorted(patterns):
        if any(character in pattern for character in "*?["):
            wildcards.append(re.compile(fnmatch.translate(pattern)))
        else:
            literals.add(pattern)
    return frozenset(literals), tuple(wildcards)


@functools.lru_cache(maxsize=64)
def compile_exclusions(patterns: tuple[str, ...]) -> MemberExclusions:
    """Compile an immutable pattern snapshot; changes naturally get a new key."""
    names, name_patterns = split_patterns({pattern for pattern in patterns if "(" not in pattern})
    signatures, signature_patterns = split_patterns(
        {"".join(pattern.split()) for pattern in patterns if "(" in pattern}
    )
    adapters, adapter_patterns = split_patterns(
        {pattern.split("(", 1)[0] for pattern in patterns if "(" in pattern}
    )
    return MemberExclusions(
        names, signatures, adapters, name_patterns, signature_patterns, adapter_patterns
    )


def excluded_method(
    patterns: list[str], owner: str, method: str, args: list[str] | None = None
) -> bool:
    """Match a native member against cached class/signature exclusion indexes."""
    return compile_exclusions(tuple(patterns)).matches(owner, method, args)
