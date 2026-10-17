"""UUID-addressed, local context bundles shared with the bundled MCP tool."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .settings import data_directory

MAX_IMAGE_BYTES = 15 * 1024 * 1024


def save_capture(target, instruction: str, image: Path | None = None) -> tuple[str, Path]:
    identifier = str(uuid.uuid4())
    folder = data_directory() / "captures"
    folder.mkdir(parents=True, exist_ok=True)
    if image:
        if image.resolve().parent != folder.resolve() or image.suffix.lower() != ".png":
            raise ValueError("截图必须在 Codex Pointer 的缓存目录内。")
        if image.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("截图超过 15 MiB，请选择鼠标周边范围，或缩小目标窗口。")
    bundle = folder / f"{identifier}.json"
    value = {
        "id": identifier, "created_at": time.time(),
        "target": asdict(target), "instruction": instruction.strip(),
        "image": str(image.resolve()) if image else None,
    }
    bundle.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return identifier, bundle


def read_capture(identifier: str, directory: Path | None = None) -> tuple[dict, bytes | None]:
    try:
        identifier = str(uuid.UUID(identifier))
    except (ValueError, AttributeError) as exc:
        raise ValueError("capture_id 必须是完整 UUID。") from exc
    folder = (directory or data_directory() / "captures").resolve()
    bundle = folder / f"{identifier}.json"
    if bundle.stat().st_size > 256 * 1024:
        raise ValueError("上下文包超出大小限制。")
    value = json.loads(bundle.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("上下文包必须是 JSON 对象。")
    if value.get("id") != identifier:
        raise ValueError("上下文包 ID 不一致。")
    if time.time() - float(value["created_at"]) > 24 * 3600:
        raise ValueError("这个上下文包已超过 24 小时，请重新选择目标。")
    image = None
    if value.get("image"):
        path = Path(value["image"]).resolve()
        if path.parent != folder or path.suffix.lower() != ".png":
            raise ValueError("截图必须在 Codex Pointer 的缓存目录内。")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("截图超过 15 MiB，请缩小截图范围。")
        image = path.read_bytes()
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("截图不是有效的 PNG 文件。")
    return value, image


def bundle_reference(identifier: str, bundle: Path) -> str:
    return (
        f"\nCodex Pointer 上下文包：{identifier}\n"
        f"本地文件：{bundle}\n"
        "如果已启用 Codex Pointer 插件，请先调用 read_capture，capture_id 为上面的 UUID。"
        "该工具会返回目标元数据与用户选择的截图。"
        "如果未启用插件，可以读取上述 JSON，并用当前可用的图像查看工具读取其中 image 路径；"
        "若不能访问本地文件，请说明限制。"
    )
