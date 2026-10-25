# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Exercise publication isolation, rollback and cross-process export ordering."""

import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from qtluau_codegen.project_output import project_output


class ProjectOutputTests(unittest.TestCase):
    """Keep live compiler inputs valid while exporters build temporary assets."""

    def test_publish_and_rollback(self) -> None:
        """Publish only final output and preserve live state on errors."""
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "project"
            source = output / "generated/source.cpp"
            source.parent.mkdir(parents=True)
            source.write_text("old")
            note = output / "notes.txt"
            note.write_text("unrelated")
            stamp = source.stat().st_mtime_ns
            with project_output(output) as staging:
                self.assertEqual(source.read_text(), "old")
                self.assertFalse((staging / "notes.txt").exists())
            self.assertEqual(source.stat().st_mtime_ns, stamp)
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                with project_output(output) as staging:
                    (staging / "generated/source.cpp").unlink()
                    raise RuntimeError("generation failed")
            self.assertEqual(source.read_text(), "old")
            with project_output(output) as staging:
                (staging / "generated/source.cpp").unlink()
                (staging / "manifest.json").write_text("final")
                self.assertTrue(source.exists())
                self.assertFalse((output / "manifest.json").exists())
            self.assertFalse(source.exists())
            self.assertEqual((output / "manifest.json").read_text(), "final")
            self.assertEqual(note.read_text(), "unrelated")

    def test_serialized_writers(self) -> None:
        """A second writer snapshots the first writer's completed publication."""
        script = """
import pathlib, sys, time
from qtluau_codegen.project_output import project_output
root, role = pathlib.Path(sys.argv[1]), sys.argv[2]
(root / (role + '.started')).touch()
with project_output(root / 'project') as staging:
    path = staging / 'manifest.json'
    if role == 'first':
        path.write_text('first')
        (root / 'first.ready').touch()
        end = time.monotonic() + 10
        while not (root / 'release').exists():
            assert time.monotonic() < end, 'release timed out'
            time.sleep(0.01)
    else:
        assert path.read_text() == 'first', 'writer read an incomplete snapshot'
        path.write_text('second')
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "project").mkdir()
            (root / "project/manifest.json").write_text("old")
            processes: list[subprocess.Popen[str]] = []
            try:
                for role, marker in [("first", "first.ready"), ("second", "second.started")]:
                    processes.append(subprocess.Popen([sys.executable, "-c", script, temporary, role],
                                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
                    deadline = time.monotonic() + 10
                    while not (root / marker).exists():
                        self.assertLess(time.monotonic(), deadline, marker)
                        time.sleep(0.01)
                self.assertEqual((root / "project/manifest.json").read_text(), "old")
                (root / "release").touch()
                for process in processes:
                    output, _ = process.communicate(timeout=15)
                    self.assertEqual(process.returncode, 0, output)
                self.assertEqual((root / "project/manifest.json").read_text(), "second")
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()


if __name__ == "__main__":
    unittest.main()
