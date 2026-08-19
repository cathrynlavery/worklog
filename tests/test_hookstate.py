"""Tests for per-session prompt-hook bookkeeping."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from worklog import hookstate
from worklog.hookstate import REASSERT_EVERY_TURNS, decide, needs_full_instruction
from worklog.paths import hook_state_dir, state_root, state_root_is_worklog_owned

from tests.support import TempLedger, permission_mode


class HookStateTests(TempLedger):
    def test_first_turn_is_full_and_later_turns_are_terse(self) -> None:
        self.assertTrue(needs_full_instruction("session-abc"))
        for turn in range(2, REASSERT_EVERY_TURNS + 1):
            with self.subTest(turn=turn):
                self.assertFalse(needs_full_instruction("session-abc"))

    def test_full_instruction_returns_periodically(self) -> None:
        results = [needs_full_instruction("session-abc") for _ in range(60)]

        full_turns = [index + 1 for index, full in enumerate(results) if full]
        self.assertEqual(full_turns, [1, 26, 51])

    def test_sessions_are_tracked_independently(self) -> None:
        self.assertTrue(needs_full_instruction("session-one"))
        self.assertFalse(needs_full_instruction("session-one"))

        # A parallel terminal must get its own full instruction.
        self.assertTrue(needs_full_instruction("session-two"))
        self.assertFalse(needs_full_instruction("session-two"))
        self.assertFalse(needs_full_instruction("session-one"))

    def test_unknown_session_always_gets_the_full_instruction(self) -> None:
        for _ in range(5):
            self.assertTrue(needs_full_instruction("unknown"))
            self.assertTrue(needs_full_instruction(""))

        self.assertFalse(hook_state_dir().exists())

    def test_shrinking_transcript_resends_the_full_instruction(self) -> None:
        transcript = self.sandbox / "transcript.jsonl"
        transcript.write_text("x" * 5000, encoding="utf-8")

        self.assertTrue(needs_full_instruction("session-abc", str(transcript)))
        self.assertFalse(needs_full_instruction("session-abc", str(transcript)))

        # Compaction rewrites the transcript smaller.
        transcript.write_text("x" * 200, encoding="utf-8")
        self.assertTrue(needs_full_instruction("session-abc", str(transcript)))

        # And the counter restarts from the fresh assertion.
        self.assertFalse(needs_full_instruction("session-abc", str(transcript)))

    def test_growing_transcript_stays_terse(self) -> None:
        transcript = self.sandbox / "transcript.jsonl"
        transcript.write_text("x" * 100, encoding="utf-8")
        self.assertTrue(needs_full_instruction("session-abc", str(transcript)))

        for size in (200, 400, 800):
            transcript.write_text("x" * size, encoding="utf-8")
            with self.subTest(size=size):
                self.assertFalse(
                    needs_full_instruction("session-abc", str(transcript))
                )

    def test_missing_transcript_path_does_not_break_the_decision(self) -> None:
        self.assertTrue(needs_full_instruction("session-abc", "/nonexistent/file"))
        self.assertFalse(needs_full_instruction("session-abc", "/nonexistent/file"))

    def test_state_is_private_and_outside_the_ledger(self) -> None:
        needs_full_instruction("session-abc")

        directory = hook_state_dir()
        self.assertEqual(permission_mode(directory), 0o700)
        files = list(directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(permission_mode(files[0]), 0o600)
        self.assertFalse(self.root.exists())

    def test_permissive_state_directory_is_tightened(self) -> None:
        directory = hook_state_dir()
        directory.mkdir(mode=0o755, parents=True)
        os.chmod(directory, 0o755)

        needs_full_instruction("session-abc")

        self.assertEqual(permission_mode(directory), 0o700)

    def test_a_caller_named_state_root_is_never_re_permissioned(self) -> None:
        # WORKLOG_STATE_DIR may name a directory shared with other tools.
        shared = self.sandbox / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        with mock.patch.dict(os.environ, {"WORKLOG_STATE_DIR": str(shared)}):
            self.assertFalse(state_root_is_worklog_owned())

            needs_full_instruction("session-abc")

            self.assertEqual(permission_mode(shared), 0o755)
            # The leaf worklog creates is still its own to protect.
            self.assertEqual(permission_mode(shared / "hook-sessions"), 0o700)

    def test_a_default_state_root_is_tightened(self) -> None:
        environment = dict(os.environ)
        environment.pop("WORKLOG_STATE_DIR", None)
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertTrue(state_root_is_worklog_owned())
            root = state_root()
            root.mkdir(mode=0o755, parents=True)
            os.chmod(root, 0o755)

            needs_full_instruction("session-abc")

            self.assertEqual(permission_mode(root), 0o700)

    def test_a_symlinked_state_directory_is_left_alone(self) -> None:
        # chmod follows symlinks, so hardening one would re-permission a
        # target that belongs to someone else.
        target = self.sandbox / "elsewhere"
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
        state_root().mkdir(mode=0o700, parents=True)
        hook_state_dir().symlink_to(target, target_is_directory=True)

        needs_full_instruction("session-abc")

        self.assertEqual(permission_mode(target), 0o755)
        # State is still written, just into the directory the user chose.
        self.assertEqual(len(list(target.iterdir())), 1)

    def test_permissive_state_directory_is_tightened_by_doctor(self) -> None:
        directory = hook_state_dir()
        directory.mkdir(mode=0o755, parents=True)
        os.chmod(directory, 0o755)

        from worklog.doctor import run_checks

        run_checks()

        self.assertEqual(permission_mode(directory), 0o700)

    def test_group_and_world_bits_are_stripped_from_state_files(self) -> None:
        needs_full_instruction("session-abc")
        needs_full_instruction("session-abc")

        for path in hook_state_dir().iterdir():
            with self.subTest(path=path.name):
                self.assertEqual(permission_mode(path), 0o600)

    def test_state_file_name_survives_a_hostile_session_id(self) -> None:
        needs_full_instruction("../../escape/../id with spaces")

        files = list(hook_state_dir().iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, hook_state_dir())
        self.assertNotIn("/", files[0].name)

    def test_similar_session_ids_do_not_share_state(self) -> None:
        self.assertTrue(needs_full_instruction("session/abc"))
        self.assertTrue(needs_full_instruction("session:abc"))

        self.assertEqual(len(list(hook_state_dir().iterdir())), 2)

    def test_state_survives_a_corrupt_file(self) -> None:
        needs_full_instruction("session-abc")
        corrupt = next(iter(hook_state_dir().iterdir()))
        corrupt.write_text("{not json", encoding="utf-8")

        # A corrupt file reads as a fresh session: verbose, never broken.
        self.assertTrue(needs_full_instruction("session-abc"))
        self.assertFalse(needs_full_instruction("session-abc"))

    def test_stale_state_files_are_pruned(self) -> None:
        needs_full_instruction("session-old")
        stale = next(iter(hook_state_dir().iterdir()))
        ancient = 1_000_000.0
        os.utime(stale, (ancient, ancient))

        needs_full_instruction("session-new")

        remaining = {path.name for path in hook_state_dir().iterdir()}
        self.assertNotIn(stale.name, remaining)
        self.assertEqual(len(remaining), 1)

    def test_recent_state_files_are_kept(self) -> None:
        needs_full_instruction("session-one")
        needs_full_instruction("session-two")

        self.assertEqual(len(list(hook_state_dir().iterdir())), 2)

    def test_state_records_whether_transcript_path_was_available(self) -> None:
        transcript = self.sandbox / "transcript.jsonl"
        transcript.write_text("x" * 10, encoding="utf-8")
        needs_full_instruction("session-abc", str(transcript))

        state = json.loads(next(iter(hook_state_dir().iterdir())).read_text())
        self.assertTrue(state["saw_transcript_path"])
        self.assertEqual(state["transcript_size"], 10)

    def test_decide_fails_open_when_state_cannot_be_written(self) -> None:
        with mock.patch.object(
            hookstate, "_write_state", side_effect=OSError("read-only")
        ):
            for _ in range(3):
                self.assertTrue(decide("session-abc"))

    def test_decide_leaves_no_temporary_files_behind(self) -> None:
        decide("session-abc")
        decide("session-abc")

        names = [path.name for path in hook_state_dir().iterdir()]
        self.assertEqual(len(names), 1)
        self.assertFalse(any(name.endswith(".tmp") for name in names))


class HookStatePathTests(TempLedger):
    def test_state_root_prefers_xdg_state_home(self) -> None:
        with mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": str(self.sandbox / "xdgstate")}
        ):
            del os.environ["WORKLOG_STATE_DIR"]
            self.assertEqual(
                hook_state_dir(),
                self.sandbox / "xdgstate" / "worklog" / "hook-sessions",
            )

    def test_state_root_defaults_under_home(self) -> None:
        environment = dict(os.environ)
        environment.pop("WORKLOG_STATE_DIR", None)
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                hook_state_dir(),
                Path(self.home) / ".local" / "state" / "worklog" / "hook-sessions",
            )


if __name__ == "__main__":
    unittest.main()
