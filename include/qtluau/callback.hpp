// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
#define QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
#include "qtluau/bindings.hpp"
#include <QObject>
#include <functional>
#include <vector>
namespace qtluau {
using LuaContextResolver = const void *(*)(lua_State *);
using SignalConnector = bool (*)(QObject *, const QByteArray &,
                                 const luabridge::LuaRef &);
using LuaSignalArguments =
    std::function<std::vector<luabridge::LuaRef>(lua_State *)>;
struct QueuedLuaCallback {
    QObject *receiver;
    std::function<void(LuaSignalArguments)> post;
};
void setLuaContextResolver(lua_State *L, LuaContextResolver resolver);
void clearLuaContext(lua_State *L);
void registerSignalConnector(lua_State *L, const QMetaObject *meta,
                             SignalConnector connector);
QueuedLuaCallback makeQueuedLuaCallback(QObject *sender,
                                        const luabridge::LuaRef &callback);
void trackContextObject(lua_State *L, QObject *object);
template <class T>
T *trackLuaObject(lua_State *L, T *object) {
    trackContextObject(L, object);
    return object;
}
template <class Sender, class Signal, class Encoder>
void connectQueuedSignal(Sender *sender, Signal signal,
                         const luabridge::LuaRef &callback, Encoder encoder) {
    auto delivery = makeQueuedLuaCallback(sender, callback);
    QObject::connect(
        sender, signal, delivery.receiver,
        [post = std::move(delivery.post), encoder](auto &&...args) {
            post(encoder(std::forward<decltype(args)>(args)...));
        },
        Qt::DirectConnection);
}

void connectLuaSignal(QObject *sender, QAnyStringView signal,
                      luabridge::LuaRef callback);
std::function<void()> makeLuaCallback(luabridge::LuaRef callback);
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
