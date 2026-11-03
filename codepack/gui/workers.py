"""Background jobs so scanning and packing never block the UI thread."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, QRunnable, Signal

from codepack.core import PackOptions, RuleSet, ScanCancelled, ScanResult, build_pack, scan_project


class WorkerSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(int, object)  # (job id, result)
    failed = Signal(int, str)


class ScanJob(QRunnable):
    def __init__(self, job_id: int, root: Path, rules: RuleSet):
        super().__init__()
        self.job_id = job_id
        self.root = root
        self.rules = rules
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def progress(count: int, rel: str) -> None:
            if count % 200 == 0:
                self.signals.progress.emit(count, rel)

        try:
            result = scan_project(self.root, self.rules, progress=progress, cancel=lambda: self._cancelled)
        except ScanCancelled:
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.signals.failed.emit(self.job_id, str(exc))
            return
        self.signals.finished.emit(self.job_id, result)


class PackJob(QRunnable):
    def __init__(self, job_id: int, scan: ScanResult, files: Sequence[str], options: PackOptions):
        super().__init__()
        self.job_id = job_id
        self.scan = scan
        self.files = list(files)
        self.options = options
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = build_pack(self.scan, self.files, self.options)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.job_id, str(exc))
            return
        self.signals.finished.emit(self.job_id, result)
