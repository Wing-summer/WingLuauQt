# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Check typed factory results and arguments between selected QObject extensions."""
import pathlib
import tempfile

from qtluau_codegen.extensions import emit_extensions
from qtluau_codegen.models import object_list_field


def main() -> None:
    """Generate two related facades and verify their shared object contract."""
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        header = root / "facades.h"
        header.write_text("""
#include <QObject>
class Leaf : public QObject {
    Q_OBJECT
public:
    int value() const { return 7; }
};
class Factory : public QObject {
    Q_OBJECT
public:
    Leaf *leaf() { return nullptr; }
    void accept(Leaf *) {}
};
""")
        out = root / "output"
        out.mkdir()
        metadata = emit_extensions({"extensions": [{
            "module": "app", "headers": ["facades.h"], "compile_moc": False,
            "classes": {"Leaf": {"constructible": False}, "Factory": {"binding": "functions", "members": ["methods"]}},
        }]}, out, root)
        factory = next(entry for entry in metadata if entry["native"] == "Factory")
        returned = next(method for method in object_list_field(factory, "methods") if method["name"] == "leaf")
        assert returned["result"] == "_ext_app_Leaf"
        accepted = next(method for method in object_list_field(factory, "methods") if method["name"] == "accept")
        assert accepted["parameters"] == ["_ext_app_Leaf"]
        source = "\n".join(path.read_text() for path in out.glob("qt_ext_*.cpp"))
        assert "qtToLuaExtension(L," in source
        assert "QtObjectRef<Leaf>" in source
        assert "pushExtensionObject(L, object, false)" in (out / "qt_extensions.hpp").read_text()


if __name__ == "__main__":
    main()
