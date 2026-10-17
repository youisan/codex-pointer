"""Small, local task starters. Selecting one never dispatches a request."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .i18n import tr, translate


@dataclass(frozen=True)
class QuickTask:
    key: str
    label: str
    prompt: str


_TASKS = {
    "folder": (
        QuickTask("folder-overview", "目录概览", "请先梳理这个文件夹的目录结构和主要内容，说明各部分的用途。"),
        QuickTask("folder-review", "查找问题", "请先查看这个文件夹的结构，再检查相关内容，指出明显问题并给出排查建议。"),
        QuickTask("folder-organize", "整理建议", "请根据这个文件夹的现有内容给出整理方案，先说明建议，不直接移动或删除文件。"),
    ),
    "file": (
        QuickTask("file-summary", "总结内容", "请阅读这个文件，概括主要内容和重点；若格式无法读取，请说明需要哪些信息。"),
        QuickTask("file-review", "检查问题", "请检查这个文件，指出明显问题或需要补充的内容，并给出修改建议。"),
        QuickTask("file-explain", "解释细节", "请用清楚易懂的语言解释这个文件中值得关注的细节；需要更多背景时请先说明。"),
    ),
    "window": (
        QuickTask("window-summary", "总结内容", "请结合选中窗口中可访问的内容，概括主要信息；若信息不足，请说明还需要什么。"),
        QuickTask("window-error", "解释报错", "请解释这个窗口中的报错或异常，给出可能原因和下一步排查建议；若无法读取界面，请先说明需要哪些信息。"),
        QuickTask("window-guide", "操作指引", "请说明这个软件当前界面主要区域的用途和常用操作入口；若无法读取界面，请先说明需要哪些信息。"),
    ),
}


def tasks_for(target: Any) -> tuple[QuickTask, ...]:
    """Choose built-in prompts by target kind, without reading target content."""
    kind = target.get("kind") if isinstance(target, Mapping) else getattr(target, "kind", None)
    tasks = _TASKS.get(kind, ()) if isinstance(kind, str) else ()
    return tuple(QuickTask(task.key, tr(task.label), tr(task.prompt)) for task in tasks)


def insertion_for(draft: str, task: QuickTask) -> str | None:
    """Return a paragraph to append, or None when this prompt is already present.

    Existing user text is never rewritten or treated as a selected replacement.
    The Qt caller appends this chunk in one undo block and keeps final dispatch
    as a separate action.
    """
    original = next((item for tasks in _TASKS.values() for item in tasks if item.key == task.key), None)
    prompts = {task.prompt}
    if original:
        prompts.update(translate(original.prompt, code) for code in ("zh-CN", "en-US"))
    if any(prompt in draft for prompt in prompts):
        return None
    if not draft.strip() or draft.endswith("\n\n"):
        return task.prompt
    return ("\n" if draft.endswith("\n") else "\n\n") + task.prompt
