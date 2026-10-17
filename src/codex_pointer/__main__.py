from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Pointer — 将窗口或文件夹带入 Codex 对话")
    parser.add_argument("--smoke-test", action="store_true", help="构建界面后自动关闭，不捕获或发送")
    parser.add_argument("--diagnose", action="store_true", help="只检查 Codex 命令和连接，不发送任务")
    parser.add_argument("--mcp", action="store_true", help="运行本地上下文 MCP 服务（stdio）")
    parser.add_argument("--preview", action="store_true", help="打开可交互的示例界面，不截图或发送")
    parser.add_argument("--theme", choices=["system", "light", "dark"], default=None)
    parser.add_argument("--render-preview", metavar="PNG", help="将真实原生组件离屏渲染为 PNG")
    args = parser.parse_args()
    if args.mcp:
        from .mcp_server import serve
        serve()
        return
    if args.diagnose:
        from .bridge import CodexBridge
        bridge = CodexBridge()
        print(bridge.diagnostics())
        return
    if sys.platform != "win32" and not (args.preview or args.render_preview or args.smoke_test):
        parser.error("悬浮按钮需要 Windows 10/11。测试和提示词模块可以跨平台运行。")
    from .app import run
    run(smoke_test=args.smoke_test, preview=args.preview, theme=args.theme, render_path=args.render_preview)


if __name__ == "__main__":
    main()
