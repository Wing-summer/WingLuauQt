# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify declaration-only metadata scanning and isolated concurrent results."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from qtluau_codegen.discovery import QT_ANNOTATIONS, SDK_FLAGS, scan_semantics
from qtluau_codegen.native_apis import selected_namespaces
from tsujikiri.configurations import SourceConfig
from tsujikiri.parse_cache import ParseKey, parse_worker

_SOURCE = '''
#include <cstddef>
namespace std { struct ForeignScannerDeclaration; }
namespace Sdk {
inline namespace Version {
namespace Nested { enum Kind { First, Second }; }
}
}
template<class T> class QFlags {};
template<class T> class QList {};
using GlobalList = QList<int>;
class QBase {
public:
    void inherited();
};
class QExample : public QBase {
public:
    using QBase::inherited;
    using Options = QFlags<int>;
    using Values = QList<int>;
    QExample() = default;
    QExample(const QExample &) = delete;
    QT_ANNOTATE_ACCESS_SPECIFIER(qt_signal)
    void changed(int value);
    int calculate(int value = 7) { return value + 1; }
};
'''


class SdkScanTests(unittest.TestCase):
    """Keep alias, signal and deletion facts intact without parsing bodies."""

    def test_metadata_and_isolation(self) -> None:
        """Return deterministic metadata without changing published dictionaries."""
        before = dict(SDK_FLAGS)
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "sdk.hpp"
            source.write_text(_SOURCE)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(scan_semantics, source, []) for _ in range(2)]
                first, second = [future.result() for future in futures]
        self.assertEqual(first, second)
        self.assertEqual(
            first.containers,
            {"GlobalList": "QList<int>", "QExample::Values": "QList<int>"},
        )
        self.assertEqual(first.flag_types, {"QExample::Options": "QFlags<int>"})
        self.assertEqual(first.namespaces, ("Sdk::Nested",))
        self.assertEqual(first.noncopyable, {"QExample"})
        self.assertEqual(first.deleted, {"QExample": {("constQExample&",)}})
        self.assertEqual(SDK_FLAGS, before)

    def test_upstream_ir_metadata(self) -> None:
        """Use upstream attributes, using declarations and parameter defaults."""
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "sdk.hpp"
            source.write_text(_SOURCE)
            config = SourceConfig(path=str(source), defines=list(QT_ANNOTATIONS))
            result = parse_worker(ParseKey.from_source(config, [""], "fixture"), False)
        self.assertFalse(result.clang_errors)
        record = result.module.class_by_name["QExample"]
        self.assertEqual([using.member_name for using in record.using_declarations], ["inherited"])
        changed = next(method for method in record.methods if method.name == "changed")
        self.assertIn("qt_signal", changed.attributes)
        calculate = next(method for method in record.methods if method.name == "calculate")
        self.assertEqual(calculate.parameters[0].default_value, "7")

    def test_cli_imports_do_not_scan(self) -> None:
        """Allow help and spawned worker imports without recursive SDK discovery."""
        result = subprocess.run(
            [sys.executable, "-c", """
from unittest.mock import patch
with patch('qtluau_codegen.discovery.scan', side_effect=AssertionError('import scanned SDK')):
    import qtluau_codegen.project
    import qtluau_codegen.qt_pipeline
    import qtluau_codegen.registration_codegen
    import qtluau_codegen.generate_definitions
"""], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configured_native_scopes(self) -> None:
        """Infer parser scopes from all symbol selectors without API allowlists."""
        self.assertEqual(selected_namespaces({
            "classes": ["Sdk::Api"],
            "types": {"Sdk::Value": {}},
            "enum_types": {"Sdk::Api::Mode": {}},
            "functions": {"Helpers::create": {}},
        }), ["Helpers", "Sdk", "Sdk::Api"])
        self.assertEqual(selected_namespaces({"functions": {"globalFunction": {}}}), [""])

    def test_transitive_module_namespaces(self) -> None:
        """Retain namespace enums from SDK dependencies outside selected modules."""
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            core = root / "QtCore"
            widgets = root / "QtWidgets"
            core.mkdir()
            widgets.mkdir()
            dependency = core / "enums.hpp"
            dependency.write_text("namespace DependencyScope { enum Mode { Value }; }")
            source = widgets / "shim.hpp"
            source.write_text(f'#include "{dependency.as_posix()}"\n')
            metadata = scan_semantics(source, [f"-I{widgets}"], ("QtWidgets",))
        self.assertEqual(metadata.namespaces, ("DependencyScope",))

    def test_invalid_header(self) -> None:
        """Reject incomplete metadata instead of publishing a partially parsed SDK."""
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "invalid.hpp"
            source.write_text("#include <missing_qtluau_test_header.h>\n")
            with self.assertRaisesRegex(ValueError, "Could not scan Qt SDK metadata"):
                scan_semantics(source, [])


if __name__ == "__main__":
    unittest.main()
