// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/callback.hpp"
#include "qtluau/qobject_value.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QDebug>
#include <QGlobalStatic>
#include <QMetaMethod>
#include <QMetaType>
#include <QPointer>
#include <QThread>
#include <QTimer>
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
    const void *context = nullptr;
    std::mutex deliveryMutex;
    bool active = true;
    QPointer<QObject> receiver;
};
std::mutex g_callbackMutex;
std::unordered_map<lua_State *, std::vector<std::weak_ptr<LuaCallbackSlot>>>
    g_callbacks;

struct ContextObject {
    const void *context;
    QPointer<QObject> object;
};
struct VmResources {
    LuaContextResolver resolver = nullptr;
    std::unordered_map<const QMetaObject *, SignalConnector> connectors;
    std::vector<ContextObject> objects;
    std::unordered_map<lua_State *, const void *> callbackContexts;
};
struct CallbackResources {
    std::unordered_map<lua_State *, VmResources> vms;
};
Q_GLOBAL_STATIC(CallbackResources, resources)
const void *contextKey(lua_State *L) {
    LuaContextResolver resolver = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        const auto &vm = resources->vms[lua_mainthread(L)];
        const auto context = vm.callbackContexts.find(L);
        if (context != vm.callbackContexts.end()) {
            return context->second;
        }
        resolver = vm.resolver;
    }
    return resolver ? resolver(L) : L;
}
void resetCallback(const std::shared_ptr<LuaCallbackSlot> &slot) {
    {
        std::lock_guard<std::mutex> lock(slot->deliveryMutex);
        slot->active = false;
        if (slot->receiver) {
            delete slot->receiver.data();
        }
    }
    slot->callback.reset();
    slot->ownerThread.reset();
}

std::shared_ptr<LuaCallbackSlot> trackCallback(luabridge::LuaRef callback) {
    lua_State *L = callback.state();
    if (!L) {
        throw std::invalid_argument("Qt callback has no owning Luau state");
    }
    auto slot = std::make_shared<LuaCallbackSlot>(std::move(callback));
    slot->context = contextKey(L);
    std::lock_guard<std::mutex> lock(g_callbackMutex);
    auto &entries = g_callbacks[lua_mainthread(L)];
    entries.erase(std::remove_if(entries.begin(), entries.end(),
                                 [](const auto &w) { return w.expired(); }),
                  entries.end());
    entries.emplace_back(slot);
    return slot;
}

} // namespace
void setLuaContextResolver(lua_State *L, LuaContextResolver resolver) {
    std::lock_guard<std::mutex> lock(g_callbackMutex);
    resources->vms[lua_mainthread(L)].resolver = resolver;
}
void registerSignalConnector(lua_State *L, const QMetaObject *meta,
                             SignalConnector connector) {
    std::lock_guard<std::mutex> lock(g_callbackMutex);
    resources->vms[lua_mainthread(L)].connectors[meta] = connector;
}
void trackContextObject(lua_State *L, QObject *object) {
    const void *context = contextKey(L);
    std::lock_guard<std::mutex> lock(g_callbackMutex);
    resources->vms[lua_mainthread(L)].objects.push_back({context, object});
}
void clearLuaContext(lua_State *L) {
    if (!L) {
        return;
    }
    if (resources.isDestroyed()) {
        clearLuaCallbacks(L);
        return;
    }
    const void *context = contextKey(L);
    std::vector<std::shared_ptr<LuaCallbackSlot>> callbacksToReset;
    std::vector<QPointer<QObject>> objects;
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        auto &vm = resources->vms[lua_mainthread(L)];
        for (auto it = vm.objects.begin(); it != vm.objects.end();) {
            if (it->context == context) {
                objects.push_back(it->object);
                it = vm.objects.erase(it);
            } else {
                ++it;
            }
        }
        for (const auto &weak : g_callbacks[lua_mainthread(L)]) {
            if (auto slot = weak.lock(); slot && slot->context == context) {
                callbacksToReset.push_back(std::move(slot));
            }
        }
    }
    for (const auto &slot : callbacksToReset) {
        resetCallback(slot);
    }
    for (const auto &object : objects) {
        if (object && !object->parent()) {
            delete object.data();
        }
    }
}
QueuedLuaCallback makeQueuedLuaCallback(QObject *sender,
                                        const luabridge::LuaRef &callback) {
    if (!callback.isFunction()) {
        throw std::invalid_argument("Expected a Luau callback function");
    }
    if (sender->thread() != QThread::currentThread()) {
        throw std::runtime_error("Signal sender belongs to another thread");
    }
    auto slot = trackCallback(callback);
    auto *receiver = new QObject(sender);
    slot->receiver = receiver;
    return {
        receiver, [slot](LuaSignalArguments encode) {
            std::lock_guard<std::mutex> lock(slot->deliveryMutex);
            if (!slot->active || !slot->receiver) {
                return;
            }
            QTimer::singleShot(
                0, slot->receiver, [slot, encode = std::move(encode)] {
                    if (!slot->callback) {
                        return;
                    }
                    auto *owner = slot->callback->state();
                    auto *main = lua_mainthread(owner);
                    lua_State *execution = nullptr;
                    std::optional<luabridge::LuaRef> keepAlive;
                    try {
                        // A signal can arrive while its source coroutine is
                        // yielded. Pin a separate invocation thread without
                        // changing that stack.
                        {
                            const luabridge::StackRestore restoreOwner(owner);
                            const luabridge::StackRestore restoreMain(main);
                            execution = lua_newthread(owner);
                            if (owner != main) {
                                lua_xmove(owner, main, 1);
                            }
                            keepAlive.emplace(
                                luabridge::LuaRef::fromStack(main, -1));
                        }
                        if (!lua_getthreaddata(execution)) {
                            lua_setthreaddata(execution,
                                              lua_getthreaddata(owner));
                        }
                        {
                            std::lock_guard<std::mutex> lock(g_callbackMutex);
                            resources->vms[main].callbackContexts[execution] =
                                slot->context;
                        }
                        auto args = encode(execution);
                        slot->callback->push(execution);
                        for (const auto &arg : args) {
                            arg.push(execution);
                        }
                        const int status = lua_pcall(
                            execution, static_cast<int>(args.size()), 0, 0);
                        if (status != LUA_OK) {
                            qWarning() << "Lua signal callback failed:"
                                       << (status == LUA_YIELD
                                               ? "Signal callbacks cannot yield"
                                               : lua_tostring(execution, -1));
                        }
                    } catch (const std::exception &error) {
                        qWarning()
                            << "Lua signal callback failed:" << error.what();
                    }
                    if (execution && keepAlive) {
                        lua_resetthread(execution);
                        std::lock_guard<std::mutex> lock(g_callbackMutex);
                        if (!resources.isDestroyed()) {
                            const auto vm = resources->vms.find(main);
                            if (vm != resources->vms.end()) {
                                vm->second.callbackContexts.erase(execution);
                            }
                        }
                    }
                    keepAlive.reset();
                });
        }};
}
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
                qWarning() << "Lua callback failed:"
                           << result.message().c_str();
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
    auto snake = [](const QByteArray &name) {
        QByteArray result;
        for (int i = 0; i < name.size(); ++i) {
            const auto ch = name[i];
            if (ch >= 'A' && ch <= 'Z') {
                if (i && ((name[i - 1] >= 'a' && name[i - 1] <= 'z') ||
                          (i + 1 < name.size() && name[i + 1] >= 'a' &&
                           name[i + 1] <= 'z'))) {
                    result += '_';
                }
                result += static_cast<char>(ch - 'A' + 'a');
            } else {
                result += ch;
            }
        }
        return result;
    };
    const bool signature = requested.contains('(');
    const QByteArray normalized =
        signature ? QMetaObject::normalizedSignature(requested.constData())
                  : requested;
    const auto requestedName =
        signature ? normalized.left(normalized.indexOf('(')) : normalized;
    QList<QByteArray> requestedTypes;
    if (signature) {
        const auto body =
            normalized.mid(normalized.indexOf('(') + 1).chopped(1);
        int depth = 0;
        int start = 0;
        for (int index = 0; index < body.size(); ++index) {
            if (body[index] == '<') {
                ++depth;
            } else if (body[index] == '>') {
                --depth;
            } else if (body[index] == ',' && depth == 0) {
                requestedTypes.append(body.mid(start, index - start));
                start = index + 1;
            }
        }
        if (!body.isEmpty()) {
            requestedTypes.append(body.mid(start));
        }
    }
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
        const QByteArray alias = snake(candidate.name());
        if (candidate.name() != requestedName && alias != requestedName) {
            continue;
        }
        if (signature) {
            if (candidate.parameterCount() != requestedTypes.size()) {
                continue;
            }
            const auto nativeTypes = candidate.parameterTypes();
            bool compatible = true;
            for (int parameter = 0; parameter < requestedTypes.size();
                 ++parameter) {
                if (nativeTypes[parameter] == requestedTypes[parameter]) {
                    continue;
                }
                const auto actual = candidate.parameterMetaType(parameter);
                const auto requestedType =
                    QMetaType::fromName(requestedTypes[parameter]);
                if (!requestedType.isValid() || requestedType != actual) {
                    compatible = false;
                    break;
                }
            }
            if (!compatible) {
                continue;
            }
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
    std::vector<SignalConnector> connectors;
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        const auto &registered =
            resources->vms[lua_mainthread(callback.state())].connectors;
        for (auto *current = meta; current; current = current->superClass()) {
            const auto found = registered.find(current);
            if (found != registered.end()) {
                connectors.push_back(found->second);
            }
        }
    }
    for (auto connector : connectors) {
        if (connector(sender, selected.methodSignature(), callback)) {
            return;
        }
    }
    if (!connectors.empty()) {
        throw std::invalid_argument(
            "Qt signal has no safe generated conversion");
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
        if (it != g_callbacks.end()) {
            callbacks = std::move(it->second);
            g_callbacks.erase(it);
        }
    }
    // Destroy LuaRefs while the state is still alive. Qt connections may
    // persist until their QObject sender is destroyed, but their shared slots
    // are now empty and safe.
    for (const auto &weak : callbacks) {
        if (auto slot = weak.lock()) {
            resetCallback(slot);
        }
    }
    std::vector<ContextObject> objects;
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        if (!resources.isDestroyed()) {
            const auto found = resources->vms.find(lua_mainthread(L));
            if (found != resources->vms.end()) {
                objects = std::move(found->second.objects);
                resources->vms.erase(found);
            }
        }
    }
    for (const auto &entry : objects) {
        if (entry.object && !entry.object->parent()) {
            delete entry.object.data();
        }
    }
}

} // namespace qtluau

#include "callback_lifetime.moc"
