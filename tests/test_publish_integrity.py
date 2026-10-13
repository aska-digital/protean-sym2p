"""A parsed stored tip is not sufficient evidence for a retry or successor."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts/protean-sym2p/sym-publish.py"
VALIDATE = ROOT / "scripts/protean-sym2p/sym-validate.py"


def draft(text):
    return {"id": "synthetic", "type": "query", "tk": "task1", "prj": "demo",
            "ttl": "task", "body": {"text": text}}


def publish(root, obj, *flags):
    return subprocess.run([sys.executable, str(PUBLISH), "--root", str(root),
                           "--by", "rolea", "--at", "2026-01-02T03:04:05Z",
                           *flags, "-"], input=json.dumps(obj), capture_output=True,
                          text=True, timeout=30)


def snapshot(root):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (root / "objects").iterdir()}


class TestPublishIntegrity(unittest.TestCase):
    def initialize(self, root, version=1):
        for n in range(1, version + 1):
            result = publish(root, draft("body %d" % n))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        name = "synthetic.md" if version == 1 else "synthetic.v%d.md" % version
        return root / "objects" / name

    def assert_refusal_preserves(self, root, obj, code):
        before = snapshot(root)
        for flags in ((), ("--dry-run",), ("--announce", "--to", "relay")):
            result = publish(root, obj, *flags)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn(code, result.stdout + result.stderr)
            self.assertEqual(before, snapshot(root))
            self.assertNotIn("already published", result.stdout)
            self.assertNotIn('"a":"assert"', result.stdout)

    def test_stale_hash_refuses_matching_tampered_body(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tip = self.initialize(root)
            obj = json.loads(tip.read_text())
            obj["body"] = {"text": "tampered"}
            tip.write_text(json.dumps(obj) + "\n")
            self.assert_refusal_preserves(root, draft("tampered"), "ERR:SYN")

    def test_stale_hash_refuses_successor_of_tampered_tip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tip = self.initialize(root)
            obj = json.loads(tip.read_text())
            obj["body"] = {"text": "tampered"}
            tip.write_text(json.dumps(obj) + "\n")
            self.assert_refusal_preserves(root, draft("new revision"), "ERR:SYN")

    def test_invalid_stored_headers_refuse_noop_and_successor(self):
        changes = (("hash", None, "ERR:SYN"), ("by", 7, "ERR:SYN"),
                   ("at", None, "ERR:SYN"), ("v", True, "ERR:VER"),
                   ("v", 2, "ERR:VER"), ("id", "other", "ERR:VER"),
                   ("sup", ["synthetic:v9"], "ERR:VER"))
        for field, value, code in changes:
            for body in ("body 1", "new revision"):
                with self.subTest(field=field, body=body), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    tip = self.initialize(root)
                    obj = json.loads(tip.read_text())
                    if value is None:
                        del obj[field]
                    else:
                        obj[field] = value
                    tip.write_text(json.dumps(obj) + "\n")
                    self.assert_refusal_preserves(root, draft(body), code)

    def test_revision_tip_must_name_its_actual_predecessor(self):
        for sup in (None, [], ["unrelated"], ["synthetic:v3"]):
            with self.subTest(sup=sup), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                tip = self.initialize(root, 3)
                obj = json.loads(tip.read_text())
                if sup is None:
                    del obj["sup"]
                else:
                    obj["sup"] = sup
                tip.write_text(json.dumps(obj) + "\n")
                self.assert_refusal_preserves(root, draft("body 3"), "ERR:VER")
                self.assert_refusal_preserves(root, draft("body 4"), "ERR:VER")

    def test_valid_retry_and_successor_preserve_existing_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tip = self.initialize(root, 2)
            # Both the bare predecessor and explicit v1 REF denote version 1.
            obj = json.loads(tip.read_text())
            obj["sup"] = ["synthetic:v1"]
            tip.write_text(json.dumps(obj) + "\n")
            before = snapshot(root)
            again = publish(root, draft("body 2"))
            self.assertEqual(0, again.returncode, again.stdout + again.stderr)
            self.assertIn("already published", again.stdout)
            self.assertEqual(before, snapshot(root))
            revised = publish(root, draft("body 3"))
            self.assertEqual(0, revised.returncode, revised.stdout + revised.stderr)
            after = snapshot(root)
            self.assertEqual(before, {name: after[name] for name in before})
            v3 = root / "objects/synthetic.v3.md"
            self.assertEqual(["synthetic:v2"], json.loads(v3.read_text())["sup"])
            validated = subprocess.run([sys.executable, str(VALIDATE), "--kind", "object",
                                        "--verify-hashes", str(v3)], capture_output=True,
                                       text=True, timeout=30)
            self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)


if __name__ == "__main__":
    unittest.main()
