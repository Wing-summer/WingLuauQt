# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Preserve fnmatch and overload semantics when indexing member exclusions."""

from __future__ import annotations

import fnmatch
import itertools
import re
import unittest

from qtluau_codegen.exclusions import excluded_method


def reference_match(patterns: list[str], owner: str, method: str, args: list[str] | None) -> bool:
    """Evaluate the original ordered rule interpretation for equivalence checks."""
    broad = f"{owner}::{method}"
    for pattern in patterns:
        if "(" not in pattern:
            if fnmatch.fnmatchcase(broad, pattern):
                return True
        elif args is None:
            if fnmatch.fnmatchcase(broad, pattern.split("(")[0]):
                return True
        elif fnmatch.fnmatchcase(
            re.sub(r"\s+", "", broad + "(" + ",".join(args) + ")"),
            re.sub(r"\s+", "", pattern),
        ):
            return True
    return False


class ExclusionTests(unittest.TestCase):
    """Keep literals, wildcards, adapter heads and mutable policies compatible."""

    def test_rule_equivalence(self) -> None:
        """Check mixed policies across overloads and fnmatch punctuation edge cases."""
        patterns = [
            "QFoo::read", "Q*::set?", "Q[AB]::read", "QFoo::read()",
            "QFoo::read(const QString &)", "QFoo::read(QList< int >, bool)",
            "*::read(*)", "QFoo::read([!x]*)", "QFoo::read(int[3])",
            "QFoo::read(\u2003int\t)", "QFoo::operator()(int)", "QFoo::[",
        ]
        policies = [[pattern] for pattern in patterns] + [patterns, list(reversed(patterns)), []]
        arguments: list[list[str] | None] = [None, [], ["int"], ["const QString&"],
                                           ["QList<int>", "bool"], ["int[3]"]]
        for policy, owner, method, args in itertools.product(
            policies, ["QFoo", "QA", "QB", "Other"], ["read", "setA", "operator()", "["], arguments
        ):
            with self.subTest(policy=policy, owner=owner, method=method, args=args):
                self.assertEqual(excluded_method(policy, owner, method, args),
                                 reference_match(policy, owner, method, args))

    def test_policy_changes(self) -> None:
        """Mutating a policy must invalidate its compiled snapshot immediately."""
        patterns = ["QFoo::read(int)"]
        self.assertTrue(excluded_method(patterns, "QFoo", "read", ["int"]))
        self.assertFalse(excluded_method(patterns, "QFoo", "read", ["bool"]))
        patterns[:] = ["QFoo::read(bool)"]
        self.assertFalse(excluded_method(patterns, "QFoo", "read", ["int"]))
        self.assertTrue(excluded_method(patterns, "QFoo", "read", ["bool"]))
        patterns.clear()
        self.assertFalse(excluded_method(patterns, "QFoo", "read", None))


if __name__ == "__main__":
    unittest.main()
