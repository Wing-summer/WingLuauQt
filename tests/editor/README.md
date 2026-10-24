# Luau text editor / Luau 文本编辑器

This standalone test generates a Qt 6.6.2 API baseline with snake_case bindings, builds it as a static library, and creates the complete editor from `editor.luau`. If a newer SDK is selected, matching Qt QDoc indexes must be installed; the generator combines their introduction-version metadata with actual preprocessed header availability.

该独立测试生成 Qt 6.6.2 基准的 snake_case 绑定并编译静态库，由 `editor.luau` 创建完整界面。使用较新 SDK 时，需要安装匹配的 Qt QDoc 索引；生成器结合索引中的引入版本与实际预处理后的头文件可用性进行筛选。

```sh
cmake -S tests/editor -B build/editor -G Ninja -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/editor --parallel 3
ctest --test-dir build/editor --output-on-failure
QT_QPA_PLATFORM=offscreen build/editor/QtLuauTextEditor --smoke
# Interactive desktop / 桌面交互：
build/editor/QtLuauTextEditor
```

The File menu provides New, Sample and Close. Smoke mode creates callbacks in a coroutine, forces garbage collection, preserves native popup flags, and triggers the real QAction signals and checks the text, status and window visibility; it also verifies CMake copied the definition files to `luaudef` beside the executable. Set `EditorBindings_DEFINITIONS_DIR` to change that relative folder or use an absolute destination.

File 菜单提供新建、插入示例和关闭。自动测试在协程中创建回调、强制 GC 并检查 Popup 标志，再触发真实 QAction 信号并检查文本、状态和窗口可见性，同时检查 CMake 已将定义拷贝到程序旁的 `luaudef`。通过 `EditorBindings_DEFINITIONS_DIR` 可指定其他相对目录或绝对路径。
