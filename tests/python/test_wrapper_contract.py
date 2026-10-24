# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify wrapper declaration discovery and reject stale adaptation references."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from qtluau_codegen.wrapper_contract import wrapper_methods


def main() -> None:
    """Exercise new declarations, injected VM arguments and missing references."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        header = root / "include/qtluau/widget_wrappers.hpp"
        header.parent.mkdir(parents=True)
        header.write_text("""class QtWidgetRef {
public:
  void setCaption(const std::string &caption);
  QtTypedWidgetRef<QNewControl> findChildNewControl(const std::string &name) const;
  luabridge::LuaRef property(const std::string &name, lua_State *L) const;
};
""")
        with patch("qtluau_codegen.wrapper_contract.support_root", return_value=root):
            methods = wrapper_methods()
        widget = methods["QtWidgetRef"]
        assert widget["setCaption"] == ("setCaption", [("caption", "string")], "()")
        assert widget["findChildNewControl"][2] == "_qt_QNewControl"
        assert widget["property"][1] == [("name", "string")]
        header.write_text(header.read_text().replace("void setCaption", "Unsupported setCaption"))
        with patch("qtluau_codegen.wrapper_contract.support_root", return_value=root):
            try:
                wrapper_methods()
            except ValueError as error:
                assert "Unsupported wrapper contract type" in str(error)
            else:
                raise AssertionError("Unknown wrapper signatures must fail generation")


if __name__ == "__main__":
    main()
