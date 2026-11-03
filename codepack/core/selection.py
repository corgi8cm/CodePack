"""Checked-file state shared by the CLI and the GUI.

The selection is stored as manual overrides on top of the scan's defaults:
included files are checked unless in ``forced_off``; excluded (but
forceable) files are unchecked unless in ``forced_on``. This lets the
overrides survive a rescan with different rules.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from codepack.core.models import ScanResult


class CheckState(Enum):
    UNCHECKED = 0
    PARTIAL = 1
    CHECKED = 2


class Selection:
    def __init__(
        self,
        scan: ScanResult,
        forced_on: Iterable[str] = (),
        forced_off: Iterable[str] = (),
    ):
        self.scan = scan
        self.forced_on: set[str] = {
            r for r in forced_on if r in scan.files and scan.files[r].checkable and not scan.files[r].included
        }
        self.forced_off: set[str] = {r for r in forced_off if r in scan.files and scan.files[r].included}
        self._dir_cache: dict[str, CheckState] = {}

    def carry_over(self, new_scan: ScanResult) -> Selection:
        """Build a selection for ``new_scan`` that keeps the manual overrides."""
        return Selection(new_scan, self.forced_on, self.forced_off)

    # --- queries ----------------------------------------------------------

    def is_checkable(self, rel: str) -> bool:
        if rel in self.scan.files:
            return self.scan.files[rel].checkable
        return rel in self.scan.dirs and self.scan.dirs[rel].pruned is None

    def is_checked(self, rel: str) -> bool:
        entry = self.scan.files.get(rel)
        if entry is None:
            return False
        if entry.included:
            return rel not in self.forced_off
        return rel in self.forced_on

    def state_of(self, rel: str) -> CheckState:
        if rel in self.scan.files:
            return CheckState.CHECKED if self.is_checked(rel) else CheckState.UNCHECKED
        cached = self._dir_cache.get(rel)
        if cached is not None:
            return cached
        state = self._compute_dir_state(rel)
        self._dir_cache[rel] = state
        return state

    def _compute_dir_state(self, dir_rel: str) -> CheckState:
        any_checked = False
        all_included_checked = True
        for rel in self.scan.files_under(dir_rel):
            checked = self.is_checked(rel)
            any_checked = any_checked or checked
            if self.scan.files[rel].included and not checked:
                all_included_checked = False
            if any_checked and not all_included_checked:
                return CheckState.PARTIAL
        if not any_checked:
            return CheckState.UNCHECKED
        return CheckState.CHECKED

    def checked_files(self) -> list[str]:
        result = [r for r, f in self.scan.files.items() if f.included and r not in self.forced_off]
        result.extend(self.forced_on)
        return sorted(result)

    def checked_tokens(self) -> int:
        return sum(self.scan.files[r].tokens for r in self.checked_files())

    # --- mutations --------------------------------------------------------

    def set_file(self, rel: str, checked: bool) -> bool:
        """Check or uncheck one file. Returns False if it cannot be checked."""
        entry = self.scan.files.get(rel)
        if entry is None or (checked and not entry.checkable):
            return False
        if entry.included:
            if checked:
                self.forced_off.discard(rel)
            else:
                self.forced_off.add(rel)
        elif checked:
            self.forced_on.add(rel)
        else:
            self.forced_on.discard(rel)
        self._dir_cache.clear()
        return True

    def set_dir(self, dir_rel: str, checked: bool) -> None:
        """Checking a directory checks its included descendants only;
        unchecking it unchecks everything below it."""
        for rel in self.scan.files_under(dir_rel):
            entry = self.scan.files[rel]
            if checked:
                if entry.included:
                    self.forced_off.discard(rel)
            elif entry.included:
                self.forced_off.add(rel)
            else:
                self.forced_on.discard(rel)
        self._dir_cache.clear()

    def set(self, rel: str, checked: bool) -> bool:
        if rel in self.scan.files:
            return self.set_file(rel, checked)
        if rel in self.scan.dirs:
            self.set_dir(rel, checked)
            return True
        return False

    def add_files(self, files: Iterable[str]) -> list[str]:
        """Check each file (forcing excluded ones). Returns the files that could not be checked."""
        rejected = [rel for rel in files if not self.set_file(rel, True)]
        return rejected

    def select_only(self, files: Iterable[str]) -> list[str]:
        """Uncheck everything, then check ``files``. Returns the files that could not be checked."""
        self.set_dir("", False)
        return self.add_files(files)

    def reset(self) -> None:
        self.forced_on.clear()
        self.forced_off.clear()
        self._dir_cache.clear()
