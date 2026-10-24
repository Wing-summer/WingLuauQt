// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/callback.hpp"
#include "qtluau/qobject_value.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QDebug>
#include <QMetaMethod>
#include <algorithm>
#include <mutex>
#include <optional>
#include <unordered_map>
#include <vector>

namespace qtluau {
namespace {
class SignalReceiver final : public QObject {
  Q_OBJECT
public:
  using QObject::QObject;
  std::function<void()> callback;
public slots:
  void dispatch() { callback(); }
};

struct LuaCallbackSlot {
  explicit LuaCallbackSlot(luabridge::LuaRef value)
      : callback(std::move(value)) {
    auto *state = callback->state();
    if (state != lua_mainthread(state)) {
      lua_pushthread(state);
      ownerThread.emplace(luabridge::LuaRef::fromStack(state, -1));
      lua_pop(state, 1);
    }
  }
  // Release the callback before its coroutine when a Qt connection is
  // destroyed.
  std::optional<luabridge::LuaRef> ownerThread;
  std::optional<luabridge::LuaRef> callback;
};
std::mutex g_callbackMutex;
std::unordered_map<lua_State *, std::vector<std::weak_ptr<LuaCallbackSlot>>>
    g_callbacks;

std::shared_ptr<LuaCallbackSlot> trackCallback(luabridge::LuaRef callback) {
  lua_State *L = callback.state();
  if (!L) {
    throw std::invalid_argument("Qt callback has no owning Luau state");
  }
  auto slot = std::make_shared<LuaCallbackSlot>(std::move(callback));
  std::lock_guard<std::mutex> lock(g_callbackMutex);
  auto &entries = g_callbacks[lua_mainthread(L)];
  entries.erase(std::remove_if(entries.begin(), entries.end(),
                               [](const auto &w) { return w.expired(); }),
                entries.end());
  entries.emplace_back(slot);
  return slot;
}

} // namespace
std::function<void()> makeLuaCallback(luabridge::LuaRef callback) {
  if (!callback.isFunction()) {
    throw std::invalid_argument("Expected a Luau callback function");
  }
  auto slot = trackCallback(std::move(callback));
  return [slot]() {
    if (!slot->callback) {
      return;
    }
    try {
      auto result = (*slot->callback)();
      if (!result) {
        qWarning() << "Lua callback failed:" << result.message().c_str();
      }
    } catch (const std::exception &error) {
      qWarning() << "Lua callback failed:" << error.what();
    } catch (...) {
      qWarning() << "Lua callback failed with an unknown exception";
    }
  };
}
void connectLuaSignal(QObject *sender, QAnyStringView signal,
                      luabridge::LuaRef callback) {
  const QByteArray requested = signal.toString().toUtf8();
  const bool signature = requested.contains('(');
  const QByteArray normalized =
      signature ? QMetaObject::normalizedSignature(requested.constData())
                : requested;
  const QMetaObject *meta = sender->metaObject();
  QMetaMethod selected;
  for (int i = 0; i < meta->methodCount(); ++i) {
    const QMetaMethod candidate = meta->method(i);
    if (candidate.methodType() != QMetaMethod::Signal) {
      continue;
    }
    if (!signature && (candidate.attributes() & QMetaMethod::Cloned)) {
      continue;
    }
    if ((signature ? candidate.methodSignature() : candidate.name()) !=
        normalized) {
      continue;
    }
    if (selected.isValid()) {
      throw std::invalid_argument(
          "Ambiguous Qt signal; provide its full signature");
    }
    selected = candidate;
  }
  if (!selected.isValid()) {
    throw std::invalid_argument("Unknown Qt signal");
  }
  auto invoke = makeLuaCallback(std::move(callback));
  auto *receiver = new SignalReceiver(sender);
  receiver->callback = std::move(invoke);
  const QMetaMethod slot = receiver->metaObject()->method(
      receiver->metaObject()->indexOfSlot("dispatch()"));
  if (!QObject::connect(sender, selected, receiver, slot)) {
    delete receiver;
    throw std::runtime_error("Cannot connect the Qt signal");
  }
}
void QtWidgetRef::connect(const std::string &signal,
                          luabridge::LuaRef callback) {
  connectLuaSignal(get(), QAnyStringView(signal), std::move(callback));
}
void QObjectRef::connect(const std::string &signal,
                         luabridge::LuaRef callback) {
  connectLuaSignal(get(), QAnyStringView(signal), std::move(callback));
}
void clearLuaCallbacks(lua_State *L) {
  if (!L) {
    return;
  }
  std::vector<std::weak_ptr<LuaCallbackSlot>> callbacks;
  {
    std::lock_guard<std::mutex> lock(g_callbackMutex);
    auto it = g_callbacks.find(lua_mainthread(L));
    if (it == g_callbacks.end()) {
      return;
    }
    callbacks = std::move(it->second);
    g_callbacks.erase(it);
  }
  // Destroy LuaRefs while the state is still alive. Qt connections may persist
  // until their QObject sender is destroyed, but their shared slots are now
  // empty and safe.
  for (const auto &weak : callbacks) {
    if (auto slot = weak.lock()) {
      slot->callback.reset();
      slot->ownerThread.reset();
    }
  }
}

} // namespace qtluau

#include "callback_lifetime.moc"
