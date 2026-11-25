// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/painter.hpp"

#include <memory>

#include <QGuiApplication>
#include <QImage>
#include <QPainter>
#include <QPixmap>
#include <QScopeGuard>
#include <QThread>

#include "qtluau/bindings.hpp"

namespace qtluau {
namespace {
int paintDevice(lua_State *state, QPaintDevice &device) {
    luaL_checktype(state, 2, LUA_TFUNCTION);
    const auto argumentCount = lua_gettop(state);
    luaL_checkstack(state, argumentCount + 1, "painting callback");

    QPainter *painter;
    bool pushed;
    {
        const auto owned = std::make_shared<QPainter>();
        painter = owned.get();
        pushed = bool(luabridge::push(state, owned));
    }
    if (!pushed) {
        luaL_error(state, "Unable to create a QPainter");
    }
    const auto painterIndex = lua_gettop(state);
    if (device.paintingActive() || !painter->begin(&device)) {
        luaL_error(state, "Unable to begin painting on this device");
    }

    int status;
    {
        // The Lua stack keeps the painter and its device alive until end().
        const auto end = qScopeGuard([painter] { painter->end(); });
        lua_pushvalue(state, 2);
        lua_pushvalue(state, painterIndex);
        for (int index = 3; index <= argumentCount; ++index) {
            lua_pushvalue(state, index);
        }
        status = lua_pcall(state, argumentCount - 1, LUA_MULTRET, 0);
    }
    if (status != LUA_OK) {
        lua_error(state);
    }
    return lua_gettop(state) - painterIndex;
}
} // namespace

int usePainter(lua_State *state) {
    if (luabridge::Stack<QImage *>::isInstance(state, 1)) {
        const auto image = luabridge::Stack<QImage *>::get(state, 1);
        if (!image || !*image) {
            luaL_argerror(state, 1, "expected a writable QImage");
        }
        return paintDevice(state, **image);
    }
    if (!luabridge::Stack<QPixmap *>::isInstance(state, 1)) {
        luaL_argerror(state, 1, "expected a QImage or QPixmap");
    }
    const auto pixmap = luabridge::Stack<QPixmap *>::get(state, 1);
    if (!pixmap || !*pixmap) {
        luaL_argerror(state, 1, "expected a writable QPixmap");
    }
    const auto *application =
        qobject_cast<QGuiApplication *>(QCoreApplication::instance());
    if (!application || application->thread() != QThread::currentThread()) {
        luaL_error(state, "Pixmap painting requires the GUI thread");
    }
    return paintDevice(state, **pixmap);
}
} // namespace qtluau
