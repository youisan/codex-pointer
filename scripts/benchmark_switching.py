"""Offline Qt responsiveness probe; no desktop reads, screenshots or Codex I/O.

Run with: python scripts/benchmark_switching.py
Simulates three rapid target changes while a 600 ms metadata lookup is active.
Only owned Qt widgets and synthetic TargetContext values are used.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication

from codex_pointer.app import PointerController
from codex_pointer.bridge import CodexBridge
from codex_pointer.windows import TargetContext


def main():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    fake_bridge = Mock(spec=CodexBridge)
    capture_ms, heartbeat_ms, starts, typed = [], [], [], []
    last_tick = time.perf_counter()
    began = last_tick
    timed_out = False

    def synthetic(name):
        return TargetContext(title=f"Synthetic {name}", hwnd=100 + ord(name),
                             process_name="explorer.exe", explorer=True,
                             point=(ord(name), 200), rect=(10, 10, 600, 400))

    def enrich(target):
        name = target.title[-1]
        starts.append(name)
        time.sleep(0.6)
        return replace(target, kind="folder", path=f"C:/Synthetic/{name}",
                       source="explorer-hit-test")

    with patch("codex_pointer.app.CodexBridge", return_value=fake_bridge), \
            patch("codex_pointer.app.enrich_target", side_effect=enrich), \
            patch("codex_pointer.app.cancel_capture_lookup"), \
            patch("codex_pointer.app.close_capture_helpers"), \
            patch("codex_pointer.app.save_settings"):
        controller = PointerController(application, preview=True, theme="light", reduced_motion=True)
        controller.open_panel()
        application.processEvents()

        def choose(name):
            before = time.perf_counter()
            controller.capture(lambda: synthetic(name))
            capture_ms.append(round((time.perf_counter() - before) * 1000, 3))

        def type_during_lookup(text):
            controller.panel.editor.insertPlainText(text)
            typed.append({"text": text, "selecting": controller.selecting,
                          "editor_enabled": controller.panel.editor.isEnabled(),
                          "time_ms": round((time.perf_counter() - began) * 1000, 1)})

        def heartbeat():
            nonlocal last_tick
            now = time.perf_counter()
            heartbeat_ms.append((now - last_tick) * 1000)
            last_tick = now
            if (controller.target and controller.target.path == "C:/Synthetic/C"
                    and not controller.selecting):
                application.quit()

        def timeout():
            nonlocal timed_out
            timed_out = True
            application.quit()

        beat = QTimer()
        beat.setInterval(10)
        beat.timeout.connect(heartbeat)
        beat.start()
        QTimer.singleShot(0, lambda: choose("A"))
        QTimer.singleShot(80, lambda: type_during_lookup("Lookup A: "))
        QTimer.singleShot(180, lambda: choose("B"))
        QTimer.singleShot(230, lambda: type_during_lookup("B still editable; "))
        QTimer.singleShot(310, lambda: choose("C"))
        QTimer.singleShot(360, lambda: type_during_lookup("C is final."))
        QTimer.singleShot(4000, timeout)
        began = last_tick = time.perf_counter()
        application.exec()
        beat.stop()
        elapsed_ms = (time.perf_counter() - began) * 1000
        gaps = sorted(heartbeat_ms)
        result = {
            "safety": "Synthetic targets; no desktop capture or Codex calls.",
            "metadata_delay_ms": 600,
            "capture_return_ms": capture_ms,
            "heartbeat_samples": len(gaps),
            "heartbeat_gap_p95_ms": round(gaps[min(len(gaps) - 1, int(len(gaps) * .95))], 3),
            "heartbeat_gap_max_ms": round(max(gaps), 3),
            "elapsed_ms": round(elapsed_ms, 1),
            "enrichment_started": starts,
            "final_target": controller.target.path if controller.target else None,
            "typed_while_lookup": typed,
            "draft": controller.panel.editor.toPlainText(),
            "timed_out": timed_out,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert not timed_out, result
        assert result["final_target"] == "C:/Synthetic/C", result
        assert starts == ["A", "C"], result
        assert all(record["selecting"] and record["editor_enabled"] for record in typed), result
        assert result["draft"] == "Lookup A: B still editable; C is final.", result
        fake_bridge.open_new_draft.assert_not_called()
        fake_bridge.send_existing.assert_not_called()
        fake_bridge.send_new.assert_not_called()
        controller.cleanup()
        for widget in application.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()


if __name__ == "__main__":
    main()
