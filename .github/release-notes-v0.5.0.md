## Codex Pointer 0.5.0 — Windows preview

[English documentation](https://github.com/youisan/codex-pointer#readme) · [中文说明](https://github.com/youisan/codex-pointer/blob/main/README.zh-CN.md) · [Website / 双语主页](https://youisan.github.io/codex-pointer/)

### What's new

- Target-specific quick tasks for windows, folders and files. Click to fill the composer; existing text is kept, duplicates are avoided, and sending remains an explicit action.
- Drop one local file or folder directly onto the circle. Unicode, spaces and UNC paths are supported; files are never moved or executed.
- Bounded path validation shares the warmed metadata helper. Unavailable network paths time out and old results cannot replace a new target.
- English / Chinese website and documentation.

Also includes target outlines, drag cancellation, explicit per-target chat bindings, recent targets, optional screenshot preview, light/dark themes, reduced motion, and click-again-to-collapse behavior.

### Install

Download **codex-pointer-0.5.0-windows-x64.zip**, extract the complete folder, and run these commands inside the extracted `codex-pointer` folder:

```powershell
codex plugin marketplace add .
codex plugin add codex-pointer@codex-pointer-local
```

Reload plugins or restart Codex. Open **Explore → Codex Pointer**, pin it, and choose **Show button**. The standalone EXE is also available for trying the picker. Quit the old circle before opening this version.

Windows 10/11 x64 and an installed, signed-in Codex desktop client are required. Native UI labels are currently Chinese. The website and documentation support both languages. This is an unsigned community preview, not an OpenAI product.

### 中文更新

- 窗口、文件夹、文件各有对应快捷任务：只填入内容，保留原稿，不自动发送。
- 将单个本地文件或文件夹拖入圆圈即可选中；支持中文、空格和 UNC 共享路径，不会移动或运行文件。
- 路径验证在后台完成并复用识别进程，网络失联有超时保护，旧查询不会覆盖新对象。
- 新增支持英中切换的主页和双语文档。

推荐下载完整 ZIP，解压后在 `codex-pointer` 目录运行上面的两条安装命令。刷新插件或重启 Codex，在“探索”中找到 Codex Pointer 并固定到侧边栏。升级前先右键退出旧圆圈。

### Verification and limits

Release checks cover offline Qt interaction, quick-task draft protection, real file-drop events, cancellation races, owned temporary-file metadata lookup, helper timeout/reuse, frozen GUI rendering, ZIP integrity, and isolated native Codex plugin discovery. No real screen capture or model task is used in these checks.

Pointer brings context to a chat; execution depends on the tools and permissions available in that chat. New-chat drafts still require confirmation in Codex. Experimental direct sending depends on the local shared app-server. Real Explorer layouts, mixed-DPI desktops and full task execution need broader environment testing.

Verify downloads against **SHA256SUMS.txt**. The complete ZIP includes replaceable Qt libraries, third-party notices and license texts.
