# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Compile member exclusion patterns before emitting registration code."""

import fnmatch
import re


def excluded_method(
    patterns: list[str], owner: str, method: str, args: list[str] | None = None
) -> bool:
    """Match a native method against class or normalized signature exclusions."""
    broad = f"{owner}::{method}"
    exact = broad + "(" + ",".join(args or []) + ")"

    def normalize(value: str) -> str:
        """Normalize native signature punctuation for exclusion comparisons."""
        return re.sub(r"\s+", "", value)

    for pattern in patterns:
        if "(" not in pattern:
            if fnmatch.fnmatchcase(broad, pattern):
                return True
        elif args is None:
            # Curated convenience adapters do not distinguish native overloads.
            if fnmatch.fnmatchcase(broad, pattern.split("(")[0]):
                return True
        elif fnmatch.fnmatchcase(normalize(exact), normalize(pattern)):
            return True
    return False
