#!/usr/bin/env python3
"""Exercises every declared gate: passes on a clean tree, fails on a bad fixture.

The bad fixtures are stored base64-encoded so that the repository itself never
contains the identifier the gate exists to catch.
"""
import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def fixture(name):
    path = os.path.join(FIXTURES, name + ".b64")
    with open(path, encoding="ascii") as fh:
        return base64.b64decode(fh.read().strip()).decode("utf-8")


def run_gate(rel_cmd, cwd):
    return subprocess.run([sys.executable, os.path.join(ROOT, rel_cmd.split()[0])]
                          + rel_cmd.split()[1:], capture_output=True, text=True,
                          cwd=cwd, timeout=120)


class TestGates(unittest.TestCase):
    def test_internal_names_gate_passes_on_clean_tree(self):
        result = run_gate("gates/protean-sym2p/check-internal-names.py", ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_internal_names_gate_fails_on_injected_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "tree")
            shutil.copytree(os.path.join(ROOT, "gates", "protean-sym2p"),
                            os.path.join(tree, "gates", "protean-sym2p"))
            with open(os.path.join(tree, "leak.md"), "w", encoding="utf-8") as fh:
                fh.write("owner: " + fixture("leak-token") + "\n")
            result = run_gate("gates/protean-sym2p/check-internal-names.py", tree)
            self.assertNotEqual(result.returncode, 0,
                                "gate did not fire on an injected private token")

    def test_internal_names_gate_fails_on_private_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "tree")
            shutil.copytree(os.path.join(ROOT, "gates", "protean-sym2p"),
                            os.path.join(tree, "gates", "protean-sym2p"))
            with open(os.path.join(tree, "leak.md"), "w", encoding="utf-8") as fh:
                fh.write("notes live under " + fixture("leak-path") + "\n")
            result = run_gate("gates/protean-sym2p/check-internal-names.py", tree)
            self.assertNotEqual(result.returncode, 0,
                                "gate did not fire on an injected private path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
