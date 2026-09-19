#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused tests for scripts/protean-sym2p/ (stdlib only, no network).

Two sections run from this one entry point, so the declared `sym2p-suite` gate
covers both halves of the object contract:

  * validator cases - real subprocess invocations of sym-validate.py, asserting
    the exit code and the typed diagnostic code;
  * publisher cases - real subprocess invocations of sym-publish.py against a
    temporary delegation tree, asserting the append-only write path (version
    resolution, sup chain, refusal to rewrite a published file), and then
    validating every published file with sym-validate.py --verify-hashes, so the
    two tools are proved to agree on the canonical content hash.

Exit 0 iff every case in both sections passes.

    python3 tests/run-tests.py
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "scripts", "protean-sym2p", "sym-validate.py")
PUBLISH = os.path.join(ROOT, "scripts", "protean-sym2p", "sym-publish.py")
FIX = os.path.join(HERE, "fixtures")
STATE = os.path.join(FIX, "state", "receiver-state.json")
EXAMPLE = os.path.join(ROOT, "examples", "protean-sym2p", "review-fix-verify-merge.jsonl")

V = lambda *p: os.path.join(FIX, "valid", *p)
I = lambda *p: os.path.join(FIX, "invalid", *p)

# (name, argv, expected_exit, expected_code_or_None)
CASES = [
    # ---- valid: must exit 0 ----
    ("help exits 0", ["--help"], 0, None),
    ("template/brief-packet.json", [os.path.join(ROOT, "templates", "protean-sym2p", "brief-packet.json")], 0, None),
    ("template/receipt-packet.json", [os.path.join(ROOT, "templates", "protean-sym2p", "receipt-packet.json")], 0, None),
    ("worked example (auto)", [EXAMPLE], 0, None),
    ("worked example (strict canonical)", ["--strict-canonical", EXAMPLE], 0, None),
    ("worked example verifies hashes", ["--verify-hashes", EXAMPLE], 0, None),
    ("valid packet-assert", [V("packet-assert.json")], 0, None),
    ("valid packet-error-ver", [V("packet-error-ver.json")], 0, None),
    ("valid object-dispute-open", [V("object-dispute-open.json")], 0, None),
    ("object hash verifies", ["--verify-hashes", V("object-dispute-open.json")], 0, None),
    ("base matches receiver state", ["--state", STATE, V("packet-update-current.json")], 0, None),

    # ---- invalid: must exit non-zero with a typed diagnostic ----
    ("truncated JSON", [I("syntax-truncated.jsonl")], 1, "ERR:SYN"),
    ("duplicate keys", [I("duplicate-keys.json")], 1, "ERR:SYN"),
    ("id grammar violated", [I("bad-id-grammar.json")], 1, "ERR:SYN"),
    ("float where integer required", [I("float-score.json")], 1, "ERR:SYN"),
    ("unknown act enum", [I("unknown-act.json")], 1, "ERR:SYN"),
    ("extra property (additionalProperties=false)", [I("extra-property.json")], 1, "ERR:SYN"),
    ("key order violated", [I("reordered-keys.json")], 1, "ERR:SYN"),
    ("multi-recipient packet", [I("multi-recipient.json")], 1, "ERR:POL"),
    ("wrong major version", [I("wrong-major-version.json")], 1, "ERR:SYN"),
    ("exec without authorization", [I("missing-auth-exec.json")], 1, "ERR:AUTH"),
    ("challenge without dissent", [I("challenge-without-dissent.json")], 1, "ERR:SEM"),
    ("verify without evidence", [I("verify-without-evidence.json")], 1, "ERR:SEM"),
    ("update without base", [I("update-without-base.json")], 1, "ERR:SYN"),
    ("dispute missing positions (P3-P5)", [I("protected-dispute-omission.json")], 1, "ERR:SYN"),
    ("losing position dropped at resolution", [I("drop-losing-position.json")], 1, "ERR:SEM"),
    ("expired authorization", ["--now", "2026-09-17T03:00:00Z",
                              I("expired-authorization.json")], 1, "ERR:EXP"),
    ("stale base vs receiver state", ["--state", STATE, I("stale-base.jsonl")], 1, "ERR:VER"),
    ("duplicate (f,id)", [I("duplicate-packet.jsonl")], 1, "ERR:DUP"),
    ("non-canonical serialization", ["--strict-canonical",
                                     I("noncanonical-whitespace.jsonl")], 1, "ERR:SYN"),
    ("tampered body, well-formed hash rejected", ["--verify-hashes",
                                                  I("object-hash-mismatch.json")], 1, "ERR:SYN"),
    # ---- the flag is opt-in: without it a stale-but-well-formed hash passes ----
    ("hash mismatch passes without the flag (opt-in)",
     [I("object-hash-mismatch.json")], 0, None),
    # ---- duplicate downgraded to a warning when explicitly allowed ----
    ("duplicate allowed -> warning only", ["--allow-duplicates",
                                           I("duplicate-packet.jsonl")], 0, "ERR:DUP"),
    ("unreadable input is a usage/IO error",
     [os.path.join(FIX, "absent.jsonl")], 2, None),
]


def run(argv, script=SCRIPT, stdin=None):
    proc = subprocess.run([sys.executable, script] + argv,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          input=stdin)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Publisher section
#
# Every published file produced here is validated with the shipped validator
# under --verify-hashes, so the write path and the read path are proved to agree
# on the canonical content hash rather than asserted to.
# --------------------------------------------------------------------------

PUB_TMP = tempfile.mkdtemp(prefix="sym2p-publish-tests-")


def canon_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def expected_hash(obj):
    """The content hash, recomputed here independently of both tools.

    Documented rule (AUDIT/protean-sym2p/provenance.md): sha256 over the
    canonical compact ``body`` with sorted keys. Header fields sit outside the
    hash by design.
    """
    return "sha256:" + hashlib.sha256(canon_bytes(obj["body"])).hexdigest()


def draft(**over):
    obj = {
        "id": "e3", "type": "evidence", "tk": "t9", "prj": "demo", "ttl": "task",
        "deps": ["e1:v1"], "acl": ["relay", "cos"], "cf": 80,
        "body": {"source": "vendor doc", "scope": "pricing table",
                 "date": "2026-09-01", "extract": "tier 2 is 40% cheaper",
                 "caveats": ["list price only"]},
    }
    obj.update(over)
    return obj


def sandbox(name):
    root = os.path.join(PUB_TMP, name)
    deleg = os.path.join(root, "deleg")
    os.makedirs(os.path.join(deleg, "objects"))
    return root, deleg


def fresh_root(name):
    """A delegation root in the state of every first use: no objects/ store.

    ``sandbox`` pre-creates objects/ so most cases can publish immediately --
    which also means a case that reuses one can never reach the fresh-root
    path. These cases build their own root and deliberately do not create the
    store, because a --dry-run must never create it either.
    """
    root = os.path.join(PUB_TMP, name)
    deleg = os.path.join(root, "deleg")
    os.makedirs(deleg)
    return root, deleg


def write_json(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh)
    return path


def read_json(path):
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def publish_ok(name, deleg, obj, extra=None):
    path = write_json(os.path.join(PUB_TMP, name + "-input.json"), obj)
    return run(["--root", deleg, "--by", "research"] + (extra or []) + [path], PUBLISH)


def run_publish_cases():
    """Sequential publisher checks; returns (passed, total, failures, notes)."""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    def validates(path):
        rc, out = run(["--verify-hashes", "--kind", "object", path])
        return rc == 0, out.strip()[:120]

    # -- 1. first publication -------------------------------------------------
    root1, deleg1 = sandbox("first")
    rc, out = publish_ok("first", deleg1, draft(), ["--at", "2026-09-19T16:00:00Z"])
    v1 = os.path.join(deleg1, "objects", "e3.md")
    check("publish v1 exits 0 with an OK line", rc == 0 and "OK e3:v1" in out,
          out.strip()[:120])
    check("publish v1 writes <id>.md", os.path.isfile(v1))
    if os.path.isfile(v1):
        obj = read_json(v1)
        ok, detail = validates(v1)
        check("published v1 validates (--verify-hashes)", ok, detail)
        check("v1 header block: v=1, no sup, author and stamp",
              obj.get("v") == 1 and "sup" not in obj and obj.get("by") == "research"
              and obj.get("at") == "2026-09-19T16:00:00Z", str(sorted(obj)))
        check("v1 hash is the canonical content hash",
              obj.get("hash") == expected_hash(obj), obj.get("hash", ""))
        with open(v1, "rb") as fh:
            raw = fh.read()
        check("written form is compact canonical JSON",
              raw.decode("utf-8").strip() == canon_bytes(obj).decode("utf-8"))

    # -- 2. revision, and the sup chain ---------------------------------------
    root2, deleg2 = sandbox("rev")
    publish_ok("rev1", deleg2, draft(), ["--at", "2026-09-19T16:00:00Z"])
    rc, out = publish_ok("rev2", deleg2, draft(body=dict(draft()["body"], extract="tier 2 is 45% cheaper")),
                         ["--at", "2026-09-19T16:01:00Z"])
    v2 = os.path.join(deleg2, "objects", "e3.v2.md")
    check("revision appends <id>.v2.md", rc == 0 and os.path.isfile(v2), out.strip()[:120])
    if os.path.isfile(v2):
        obj2 = read_json(v2)
        ok, detail = validates(v2)
        check("published v2 validates (--verify-hashes)", ok, detail)
        check("v2: v=2 and sup=[<id>] (section 4 rule 2)",
              obj2.get("v") == 2 and obj2.get("sup") == ["e3"], str(obj2.get("sup")))
        check("v1 is untouched by the revision",
              read_json(os.path.join(deleg2, "objects", "e3.md")).get("v") == 1)

    rc, out = publish_ok("rev3", deleg2, draft(body=dict(draft()["body"], extract="tier 2 is 50% cheaper")),
                         ["--at", "2026-09-19T16:02:00Z"])
    v3 = os.path.join(deleg2, "objects", "e3.v3.md")
    check("third revision appends v3", rc == 0 and os.path.isfile(v3), out.strip()[:120])
    if os.path.isfile(v3):
        obj3 = read_json(v3)
        ok, detail = validates(v3)
        check("published v3 validates (--verify-hashes)", ok, detail)
        check("v3 sup is the legal versioned REF <id>:v2",
              obj3.get("sup") == ["e3:v2"], str(obj3.get("sup")))

    # -- 3. idempotency: same content is not republished ----------------------
    tip = os.path.join(deleg2, "objects", "e3.v3.md")
    before = os.stat(tip).st_mtime_ns, open(tip, "rb").read()
    rc, out = publish_ok("rev3-again", deleg2,
                         draft(body=dict(draft()["body"], extract="tier 2 is 50% cheaper")),
                         ["--at", "2026-09-19T19:00:00Z"])
    after = os.stat(tip).st_mtime_ns, open(tip, "rb").read()
    check("repeat publish is an idempotent no-op (exit 0, says so)",
          rc == 0 and "already published" in out, out.strip()[:120])
    check("no-op publishes no new version and rewrites nothing",
          sorted(os.listdir(os.path.join(deleg2, "objects"))) ==
          ["e3.md", "e3.v2.md", "e3.v3.md"] and before == after)

    # -- 4. announce packet --------------------------------------------------
    root4, deleg4 = sandbox("announce")
    rc, out = publish_ok("ann", deleg4, draft(),
                         ["--at", "2026-09-19T16:00:00Z", "--announce", "--to", "relay"])
    lines = [ln for ln in out.strip().splitlines() if ln.startswith("{")]
    check("--announce emits one canonical packet line", rc == 0 and len(lines) == 1,
          out.strip()[:160])
    if lines:
        ann = lines[0]
        anndoc = json.loads(ann)
        annfile = os.path.join(PUB_TMP, "announce.jsonl")
        with open(annfile, "w") as fh:
            fh.write(ann + "\n")
        rc2, out2 = run(["--strict-canonical", annfile])
        check("announce line validates as a canonical packet", rc2 == 0, out2.strip()[:120])
        check("announce names the new ref for the recipient",
              anndoc.get("s") == "e3" and anndoc.get("a") == "assert"
              and anndoc.get("f") == "research" and anndoc.get("t") == "relay"
              and anndoc.get("rq") == "rev" and "base" not in anndoc,
              ann[:160])
    # the revision announce carries the predecessor in `base`
    _, out = publish_ok("ann2", deleg4, draft(body=dict(draft()["body"], extract="revised")),
                        ["--at", "2026-09-19T16:05:00Z", "--announce", "--to", "relay"])
    lines2 = [ln for ln in out.strip().splitlines() if ln.startswith("{")]
    check("revision announce carries s=<id>:v2 and base=<id>:v1",
          len(lines2) == 1 and json.loads(lines2[0]).get("s") == "e3:v2"
          and json.loads(lines2[0]).get("base") == "e3:v1",
          lines2[0][:160] if lines2 else "no announce line")

    # -- 5. the write path refuses to rewrite a published file (M-5) ---------
    spec = importlib.util.spec_from_file_location("sym_publish", PUBLISH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root5, deleg5 = sandbox("writeonce")
    target = os.path.join(deleg5, "objects", "e9.md")
    with open(target, "w") as fh:
        fh.write('{"published":"already"}')
    findings = []
    wrote = mod.write_once(target, b'{"v":1}', findings)
    check("write_once refuses an existing published file",
          wrote is False and findings and findings[0]["code"] == "ERR:VER",
          str(findings)[:160])
    check("refused write leaves the published bytes untouched",
          open(target, "rb").read() == b'{"published":"already"}')

    # -- 6. CLI refusals -----------------------------------------------------
    rc, out = run(["--root", deleg2, "--by", "research", "--version", "3",
                   write_json(os.path.join(PUB_TMP, "conflict.json"),
                              draft(body=dict(draft()["body"], extract="conflicting")))],
                  PUBLISH)
    check("a published version cannot be overwritten (--version conflict)",
          rc == 1 and "ERR:VER" in out, out.strip()[:160])

    root6, deleg6 = sandbox("hole")
    with open(os.path.join(deleg6, "objects", "x9.v3.md"), "w") as fh:
        fh.write(json.dumps(draft(id="x9")))
    rc, out = publish_ok("hole", deleg6, draft(id="x9"))
    check("a version-chain hole is refused (fail closed)",
          rc == 1 and "ERR:VER" in out and "hole" in out, out.strip()[:160])

    root7, deleg7 = sandbox("dupe")
    for name in ("x8.md", "x8.v1.md"):
        with open(os.path.join(deleg7, "objects", name), "w") as fh:
            fh.write(json.dumps(draft(id="x8")))
    rc, out = publish_ok("dupe", deleg7, draft(id="x8"))
    check("two files claiming version 1 are refused",
          rc == 1 and "ERR:VER" in out, out.strip()[:160])

    root8, deleg8 = sandbox("declared")
    rc, out = publish_ok("badhash", deleg8, draft(hash="sha256:" + "0" * 64))
    check("a stale declared hash is refused, not silently recomputed",
          rc == 1 and "ERR:SYN" in out and not os.listdir(os.path.join(deleg8, "objects")),
          out.strip()[:160])
    rc, out = publish_ok("badby", deleg8, draft(by="qa"))
    check("a conflicting authorship claim is refused (ERR:AUTH)",
          rc == 1 and "ERR:AUTH" in out, out.strip()[:160])
    rc, out = publish_ok("badv", deleg8, draft(v=9))
    check("a declared version that contradicts the chain is refused (ERR:VER)",
          rc == 1 and "ERR:VER" in out, out.strip()[:160])
    rc, out = publish_ok("badsup", deleg8, draft(sup=["e3:v9"]))
    check("a declared sup that contradicts the lineage is refused (ERR:VER)",
          rc == 1 and "ERR:VER" in out, out.strip()[:160])
    rc, out = publish_ok("badkey", deleg8, draft(extra="nope"))
    check("an unknown object property is refused (ERR:SYN)",
          rc == 1 and "ERR:SYN" in out, out.strip()[:160])
    missing = draft()
    del missing["ttl"]
    rc, out = publish_ok("badmissing", deleg8, missing)
    check("a missing required field is refused (ERR:SYN)",
          rc == 1 and "ERR:SYN" in out, out.strip()[:160])
    rc, out = publish_ok("badbody", deleg8, draft(body="prose"))
    check("a non-object body is refused (ERR:SYN)",
          rc == 1 and "ERR:SYN" in out, out.strip()[:160])
    truncated = os.path.join(PUB_TMP, "truncated.json")
    with open(truncated, "w") as fh:
        fh.write('{"id":"e3","type":"evidence"')
    rc, out = run(["--root", deleg8, "--by", "research", truncated], PUBLISH)
    check("malformed input JSON is refused (ERR:SYN)",
          rc == 1 and "ERR:SYN" in out, out.strip()[:160])

    # -- 6b. hash scope, and a caller-computed hash ---------------------------
    root10, deleg10 = sandbox("hashscope")
    supplied_body = draft(id="e8")
    supplied = dict(supplied_body, hash=expected_hash(supplied_body))
    rc, out = publish_ok("supplied", deleg10, supplied, ["--at", "2026-09-19T16:00:00Z"])
    e8 = os.path.join(deleg10, "objects", "e8.md")
    check("a caller-supplied correct body hash survives publication",
          rc == 0 and os.path.isfile(e8) and read_json(e8).get("hash") == supplied["hash"],
          out.strip()[:120])
    if os.path.isfile(e8):
        ok, detail = validates(e8)
        check("the supplied-hash publication verifies (--verify-hashes)", ok, detail)
        # The documented rule hashes the body, so header fields are outside it.
        # Pinned deliberately: a future hash-scope change must fail loudly here.
        edited = read_json(e8)
        edited["ttl"] = "project"
        with open(e8, "w") as fh:
            fh.write(json.dumps(edited, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False) + "\n")
        rc, out = run(["--verify-hashes", "--kind", "object", e8])
        check("hash scope is the body: a header edit still verifies (pinned)", rc == 0,
              out.strip()[:120])

    # -- 7. normalization and inputs -----------------------------------------
    root9, deleg9 = sandbox("normalize")
    rc, out = publish_ok("normalize", deleg9, draft(), ["--at", "2026-09-19T16:00:00Z"])
    pretty = os.path.join(PUB_TMP, "pretty.json")
    with open(pretty, "w") as fh:
        fh.write(json.dumps(draft(id="e4", body={"extract": "ümlaut — em dash"}),
                            indent=2, sort_keys=False))
    rc, out = run(["--root", deleg9, "--by", "research", "--at", "2026-09-19T16:00:00Z",
                   pretty], PUBLISH)
    e4 = os.path.join(deleg9, "objects", "e4.md")
    check("pretty-printed input is normalized to canonical form",
          rc == 0 and os.path.isfile(e4) and
          open(e4, "rb").read().decode("utf-8") == canon_bytes(read_json(e4)).decode("utf-8") + "\n",
          out.strip()[:120])
    if os.path.isfile(e4):
        ok, detail = validates(e4)
        check("normalized non-ASCII object validates (UTF-8, ensure_ascii=False)", ok, detail)

    rc, out = run(["--root", deleg9, "--by", "research", "--at", "2026-09-19T16:00:00Z",
                   "-"], PUBLISH, stdin=canon_bytes(draft(id="e5")) + b"\n")
    check("stdin input ('-') publishes",
          rc == 0 and os.path.isfile(os.path.join(deleg9, "objects", "e5.md")),
          out.strip()[:120])

    rc, out = run(["--root", deleg9, "--by", "research", "--dry-run",
                   "--announce", "--to", "relay",
                   write_json(os.path.join(PUB_TMP, "dry.json"), draft(id="e6"))], PUBLISH)
    check("--dry-run prints the plan and writes nothing",
          rc == 0 and "dry-run, no files written" in out
          and not os.path.exists(os.path.join(deleg9, "objects", "e6.md")),
          out.strip()[:120])

    rc1, out1 = run(["--root", deleg9, "--by", "research", "--announce",
                     write_json(os.path.join(PUB_TMP, "noann.json"), draft(id="e7"))], PUBLISH)
    rc2, out2 = run(["--root", os.path.join(PUB_TMP, "absent-root"), "--by", "research",
                     write_json(os.path.join(PUB_TMP, "noroot.json"), draft(id="e7"))], PUBLISH)
    rc3, out3 = run(["--root", deleg9, "--by", "research",
                     os.path.join(PUB_TMP, "absent.json")], PUBLISH)
    check("usage/IO failures exit 2 (missing --to, missing root, unreadable input)",
          (rc1, rc2, rc3) == (2, 2, 2),
          " ".join([out1.strip()[:40], out2.strip()[:40], out3.strip()[:40]]))

    # -- 8. first use: a fresh root with no objects/ store --------------------
    # The documented first-use path, and the one --dry-run exists to check.
    # Section 7 reuses a sandbox whose objects/ an earlier case already
    # populated, so a dry-run there never reaches this state; these cases
    # build their own root with no store.
    root11, deleg11 = fresh_root("freshroot")
    objects11 = os.path.join(deleg11, "objects")
    fresh_input = write_json(os.path.join(PUB_TMP, "fresh.json"), draft(id="e9"))

    rc, out = run(["--root", deleg11, "--by", "research", "--dry-run",
                   fresh_input], PUBLISH)
    check("--dry-run on a fresh root exits 0 and plans v1",
          rc == 0 and "dry-run, no files written" in out and "ref: e9:v1" in out,
          "exit=%d %s" % (rc, out.strip()[:160]))
    present_11 = sorted(os.listdir(objects11)) if os.path.isdir(objects11) else None
    check("--dry-run on a fresh root creates no store and writes nothing",
          present_11 is None,
          "objects/ created with %s" % present_11)

    rc, out = run(["--root", deleg11, "--by", "research", "--dry-run", "--announce",
                   "--to", "relay", fresh_input], PUBLISH)
    check("--dry-run on a fresh root still emits the announce plan",
          rc == 0 and "announce: " in out and "dry-run, no files written" in out,
          "exit=%d %s" % (rc, out.strip()[:160]))

    rc, out = run(["--root", deleg11, "--by", "research",
                   "--at", "2026-09-19T16:00:00Z", fresh_input], PUBLISH)
    e9 = os.path.join(objects11, "e9.md")
    check("the same fresh root then publishes for real",
          rc == 0 and os.path.isfile(e9), "exit=%d %s" % (rc, out.strip()[:160]))
    if os.path.isfile(e9):
        ok, detail = validates(e9)
        check("the first-use publication validates (--verify-hashes)", ok, detail)
        rc, out = run(["--root", deleg11, "--by", "research", "--dry-run",
                       write_json(os.path.join(PUB_TMP, "fresh2.json"), draft(id="e9"))], PUBLISH)
        check("--dry-run on a populated root is a planned no-op, not a write",
              rc == 0 and ("already published" in out or "v2" in out),
              "exit=%d %s" % (rc, out.strip()[:160]))

    passed = sum(1 for _n, ok, _d in checks if ok)
    failures = [n for n, ok, _d in checks if not ok]
    for name, ok, detail in checks:
        print("%-4s %-52s %s" % ("PASS" if ok else "FAIL", name, "" if ok else detail))
    return passed, len(checks), failures


def main():
    failures = []
    for name, argv, want_exit, want_code in CASES:
        rc, out = run(argv)
        problems = []
        if rc != want_exit:
            problems.append("exit %d (wanted %d)" % (rc, want_exit))
        if want_code and want_code not in out:
            problems.append("diagnostic %s missing" % want_code)
        if not want_code and want_exit == 0 and "OK" not in out and "--help" not in argv:
            problems.append("no OK line")
        status = "PASS" if not problems else "FAIL"
        print("%-4s %-52s exit=%d" % (status, name, rc))
        if problems:
            failures.append(name)
            for p in problems:
                print("       -> %s" % p)
            for line in out.strip().splitlines()[:6]:
                print("       |  %s" % line)
    print("")
    print("%d/%d validator cases passed" % (len(CASES) - len(failures), len(CASES)))
    print("")
    try:
        pub_passed, pub_total, pub_failures = run_publish_cases()
    finally:
        shutil.rmtree(PUB_TMP, ignore_errors=True)
    print("")
    print("%d/%d publisher cases passed" % (pub_passed, pub_total))
    failures.extend(pub_failures)
    total = len(CASES) + pub_total
    print("")
    print("%d/%d cases passed" % (total - len(failures), total))
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
