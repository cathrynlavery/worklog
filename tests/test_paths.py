"""Tests for ledger path resolution and private directory creation."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from worklog.paths import ensure_private_dir, ledger_root

from tests.support import TempLedger, permission_mode


class PathTests(TempLedger):
    def test_ledger_root_precedence_sources(self) -> None:
        explicit = self.sandbox / "explicit"
        xdg = self.sandbox / "xdg-source"
        home = self.sandbox / "home-source"
        os.environ.update(
            WORKLOG_DIR=str(explicit),
            XDG_DATA_HOME=str(xdg),
            HOME=str(home),
        )
        self.assertEqual(ledger_root(), explicit)

        del os.environ["WORKLOG_DIR"]
        self.assertEqual(ledger_root(), xdg / "worklog")

        del os.environ["XDG_DATA_HOME"]
        self.assertEqual(ledger_root(), home / ".local" / "share" / "worklog")

    def test_ensure_private_dir_creates_every_missing_level_at_0700(self) -> None:
        target = self.sandbox / "one" / "two" / "three"

        result = ensure_private_dir(target)

        self.assertEqual(result, target)
        for directory in (target.parent.parent, target.parent, target):
            self.assertTrue(directory.is_dir())
            self.assertEqual(permission_mode(directory), 0o700)

    def test_ensure_private_dir_does_not_chmod_existing_ancestor(self) -> None:
        ancestor = self.sandbox / "public-parent"
        ancestor.mkdir()
        os.chmod(ancestor, 0o755)

        ensure_private_dir(ancestor / "private" / "nested")

        self.assertEqual(permission_mode(ancestor), 0o755)
        self.assertEqual(permission_mode(ancestor / "private"), 0o700)

    def test_ensure_private_dir_rejects_file_in_path(self) -> None:
        conflict = self.sandbox / "conflict"
        conflict.write_text("not a directory", encoding="utf-8")

        with self.assertRaises(NotADirectoryError):
            ensure_private_dir(conflict / "child")


if __name__ == "__main__":
    unittest.main()
