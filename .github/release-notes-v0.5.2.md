## Codex Pointer 0.5.2 — Windows preview

[Website / 双语主页](https://youisan.github.io/codex-pointer/) · [English documentation](https://github.com/youisan/codex-pointer#readme) · [中文说明](https://github.com/youisan/codex-pointer/blob/main/README.zh-CN.md)

### Fix

File and folder drops now validate their path without loading desktop accessibility libraries or creating an Explorer COM object. This reduces first-use startup work and avoids a timeout on Windows environments with slower desktop initialization. Explorer accessibility is loaded only when a window lookup needs it. The three-second query budget is unchanged.

The Windows integration tests also handle equivalent short (8.3) and full paths correctly. Real-process metadata tests allow shared CI machines time to cold-start PowerShell; controlled timeout tests still verify the unchanged production deadline.

### Included features

- Target-specific quick tasks that fill the composer without replacing your draft or sending automatically.
- Drop one local file or folder onto the circle; Unicode, spaces and UNC paths are supported.
- Window and folder target previews, explicit per-target chat bindings, recent targets, optional screenshot previews, light/dark themes and click-again-to-collapse.
- English / Chinese website and documentation. The native Windows UI currently uses Chinese labels.

### Install

Download **codex-pointer-0.5.2-windows-x64.zip** and extract the complete folder. In the extracted `codex-pointer` folder, run:

```powershell
codex plugin marketplace add .
codex plugin add codex-pointer@codex-pointer-local
```

Reload plugins or restart Codex, then open **Explore → Codex Pointer → Show button**. Quit the old circle before opening this version. Requires Windows 10/11 x64 and an installed, signed-in Codex desktop client.

### 中文

修复首次拖入文件或文件夹时不必要的桌面组件初始化，减少冷启动耗时，避免部分 Windows 环境的识别超时。只有识别软件窗口时才加载资源管理器相关组件，三秒查询超时保护保持有效。测试也兼容 Windows 短路径与完整路径指向同一对象的情况。

本版包含快捷任务、文件拖入圆圈、按对象记住对话、目标预览和双语主页。推荐下载完整 ZIP；升级前先右键退出旧按钮。

This is an unsigned community preview, not an OpenAI product. Screenshots require opt-in. New-chat drafts require confirmation in Codex, and execution depends on that chat's tools and permissions. Verify downloads against **SHA256SUMS.txt**; licenses and notices are included in the ZIP.
