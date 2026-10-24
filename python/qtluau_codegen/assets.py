# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Locate shipped C++ generator support sources in a checkout or installation."""

import pathlib
import sysconfig


def support_root() -> pathlib.Path:
    """Locate complete support assets in a checkout or installed package."""
    candidates = [
        pathlib.Path(__file__).resolve().parents[2],
        pathlib.Path(sysconfig.get_path("data")) / "share/wingluauqt",
    ]
    # CMake may run an installed generator through a separate dependency venv.
    # Locate its own installation prefix even when sysconfig refers to that venv.
    candidates.extend(
        parent / "share/wingluauqt" for parent in pathlib.Path(__file__).resolve().parents
    )
    for root in candidates:
        if (
            (root / "include/qtluau/bindings.hpp").is_file()
            and (root / "support/execute_luau.cpp").is_file()
            and (root / "config/bindings.json").is_file()
        ):
            return root
    raise ValueError(
        "C++ generation support sources are missing; install the complete wingluauqt package"
    )
