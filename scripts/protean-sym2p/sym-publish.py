#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sym-publish.py - the write-once object publisher for SYM-2P/1.0 (stdlib only).

M-5 requires object writes to be append-only versions (``<id>.md``, then
``<id>.v<N>.md`` with ``sup`` and an incremented ``v``) and requires the tooling
to refuse to rewrite a published file (L-14). ``sym-validate.py`` checks object
shape on the read path; this script is the write path. It is the producer half of
the same contract, so it shares the validator's conventions:

  * canonical content hash  - sha256 over the object document with the ``hash``
    field removed, serialized as compact JSON (separators ``","`` / ``":"``),
    keys sorted, UTF-8 encoded. This is the canonicalization ``--verify-hashes``
    recomputes, so a published file verifies against the shipped validator.
  * canonical serialization - compact UTF-8 JSON, no insignificant whitespace,
    absent optionals omitted, never ``null`` (M-2 / L-3). Object documents carry
    no mandated key order, so the written form is key-sorted and byte-stable.
  * typed diagnostics       - the same ``<CODE>: <field>: <message>`` surface and
    exit codes 0 valid, 1 invalid (typed, fail closed), 2 usage or IO error.
  * fail closed            - an unresolved version, an inconsistent version
    chain, a mismatched declared hash, or a conflicting authorship claim is a
    typed refusal, never a guess (L-16).

Append-only resolution is derived from the filesystem, never from the input:
the publisher reads ``<root>/objects/`` and computes the next version, so calling
it twice with unchanged content is an idempotent no-op (L-11) and calling it with
changed content appends exactly one new version.

Usage
-----

    sym-publish.py --root <delegation-dir> --by <role-id> new-object.json
    sym-publish.py --root <dir> --by cos --announce --to relay draft.json
    cat draft.json | sym-publish.py --root <dir> --by cos -
    sym-publish.py --root <dir> --by cos --dry-run draft.json

The positional input is a hash-less JSON object: the object's own header fields
(``v``, ``sup``, ``hash``, ``by``, ``at``) are assigned by the publisher. Any of
those keys may be supplied, but only when it agrees with what the publisher
resolved; a disagreement is a typed refusal. Content fields (``id``, ``type``,
``tk``, ``prj``, ``ttl``, ``body``, and the per-type surface) are the caller's.

Limits
------

The publisher enforces the object header block of SPEC.md section 4 and the
fail-closed write path. It does not re-implement the validator's per-type checks;
run ``sym-validate.py --verify-hashes --kind object`` on the published file for
the full contract. Routing-state rows (M-9) are out of scope here: the announce
packet names the new ref and the caller routes it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Locked vocabulary (mirrors sym-validate.py / SPEC.md sections 3 and 4)
# --------------------------------------------------------------------------

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REF_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}(:v[1-9][0-9]*)?$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

OBJECT_TYPES = [
    "task", "query", "claim", "hypothesis", "evidence", "plan", "action",
    "result", "decision", "constraint", "unknown", "risk", "artifact", "dispute",
]
TTL_CLASSES = ["ephemeral", "task", "project", "regulated"]

OBJECT_REQUIRED = ["id", "type", "v", "tk", "prj", "by", "at", "hash", "ttl", "body"]
OBJECT_ALLOWED = OBJECT_REQUIRED + [
    "sup", "deps", "acl", "cf", "cov", "err", "subj", "positions", "dtype",
    "need", "status", "resolution", "ext",
]
# Supplied by the caller: the object's own identity, classification, and content.
INPUT_REQUIRED = ["id", "type", "tk", "prj", "ttl", "body"]
# Assigned by the publisher; accepted from the caller only when it agrees.
MANAGED_KEYS = ("v", "sup", "hash", "by", "at")

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


def E(code, field, msg):
    return {"code": code, "field": field, "msg": msg}


# --------------------------------------------------------------------------
# Strict JSON parsing (duplicate keys, NaN/Infinity, UTF-8, BOM)
# --------------------------------------------------------------------------

class DuplicateKey(ValueError):
    def __init__(self, key):
        ValueError.__init__(self, "duplicate object key: %r" % (key,))
        self.key = key


def _pairs_hook(pairs):
    seen = set()
    for k, _v in pairs:
        if k in seen:
            raise DuplicateKey(k)
        seen.add(k)
    return dict(pairs)


def _no_constants(name):
    raise ValueError("non-numeric constant %r is not valid JSON" % (name,))


def parse_strict(text, findings):
    try:
        obj = json.loads(text, object_pairs_hook=_pairs_hook,
                         parse_constant=_no_constants)
    except DuplicateKey as exc:
        findings.append(E("ERR:SYN", "<document>", str(exc)))
        return None
    except ValueError as exc:
        findings.append(E("ERR:SYN", "<document>", "invalid JSON: %s" % exc))
        return None
    if not isinstance(obj, dict):
        findings.append(E("ERR:SYN", "<document>", "object document must be a JSON object"))
        return None
    return obj


def decode_utf8(raw, findings):
    """Strict UTF-8, no BOM (L-3)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        findings.append(E("ERR:SYN", "<document>", "UTF-8 BOM not permitted"))
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(E("ERR:SYN", "<document>", "not valid UTF-8: %s" % exc))
        return None


# --------------------------------------------------------------------------
# Canonical form and content hash (the rule --verify-hashes recomputes)
# --------------------------------------------------------------------------

def canonical_bytes(obj):
    """Compact, key-sorted, UTF-8 JSON - the byte-stable written form."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def content_hash(obj):
    """``sha256:<hex>`` over the canonical form with ``hash`` excluded."""
    body = {k: v for k, v in obj.items() if k != "hash"}
    return "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()


def fingerprint(obj):
    """Content-only digest used for idempotency.

    Ignores the publisher-assigned keys, so a retry of the same publication
    (same author, same content, a later ``at``) resolves to the version already
    on disk instead of appending a duplicate revision (L-11).
    """
    body = {k: v for k, v in obj.items() if k not in MANAGED_KEYS}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_ref(v):
    return isinstance(v, str) and bool(REF_RE.match(v))


# --------------------------------------------------------------------------
# Input checks (the caller's half of the header block)
# --------------------------------------------------------------------------

def check_input(obj, findings, by):
    for k in obj:
        if k not in OBJECT_ALLOWED:
            findings.append(E("ERR:SYN", k, "unknown object property"))
    for req in INPUT_REQUIRED:
        if req not in obj:
            findings.append(E("ERR:SYN", req, "required object field missing (not publisher-assigned)"))
    if not check_ref(obj.get("id")) or not ID_RE.match(str(obj.get("id", ""))):
        findings.append(E("ERR:SYN", "id", "violates ID grammar: %r" % (obj.get("id"),)))
    for fld in ("tk", "prj"):
        if not (isinstance(obj.get(fld), str) and ID_RE.match(obj[fld])):
            findings.append(E("ERR:SYN", fld, "violates ID grammar: %r" % (obj.get(fld),)))
    if obj.get("type") not in OBJECT_TYPES:
        findings.append(E("ERR:SYN", "type", "unknown object type %r (allowed: %s)"
                          % (obj.get("type"), ", ".join(OBJECT_TYPES))))
    if obj.get("ttl") not in TTL_CLASSES:
        findings.append(E("ERR:SYN", "ttl", "unknown retention class %r (allowed: %s)"
                          % (obj.get("ttl"), ", ".join(TTL_CLASSES))))
    if not isinstance(obj.get("body"), dict):
        findings.append(E("ERR:SYN", "body", "must be an object (content stored once)"))
    for fld in ("sup", "deps"):
        if fld in obj:
            if not isinstance(obj[fld], list):
                findings.append(E("ERR:SYN", fld, "must be an array of refs"))
            else:
                for i, r in enumerate(obj[fld]):
                    if not check_ref(r):
                        findings.append(E("ERR:SYN", "%s[%d]" % (fld, i),
                                          "not a valid REF: %r" % (r,)))
    if "acl" in obj and not isinstance(obj["acl"], list):
        findings.append(E("ERR:SYN", "acl", "must be an array of agent ids"))
    for fld in ("cf", "cov", "err"):
        if fld in obj:
            v = obj[fld]
            if not is_int(v) or not (0 <= v <= 99):
                findings.append(E("ERR:SYN", fld, "must be an integer 0-99, got %r" % (v,)))
    if "ext" in obj and not isinstance(obj["ext"], dict):
        findings.append(E("ERR:SYN", "ext", "must be an object"))
    if "at" in obj:
        if not isinstance(obj["at"], str) or not ISO_Z_RE.match(obj["at"]):
            findings.append(E("ERR:SYN", "at",
                              "must be ISO-8601 UTC (…Z): %r" % (obj["at"],)))
    # A supplied hash is verified against the document as given; a mismatch is a
    # refusal, never a silent recompute of someone else's integrity claim.
    if "hash" in obj:
        declared = obj["hash"]
        if not isinstance(declared, str) or not HASH_RE.match(declared):
            findings.append(E("ERR:SYN", "hash", "must be 'sha256:<64 hex>': %r" % (declared,)))
        else:
            recomputed = content_hash(obj)
            if recomputed != declared:
                findings.append(E(
                    "ERR:SYN", "hash",
                    "declared hash does not match the canonical content: declared %s "
                    "but the document hashes to %s (canonical form: compact JSON, "
                    "sorted keys, UTF-8, hash field excluded); omit 'hash' to have "
                    "the publisher compute it" % (declared[:23], recomputed[:23])))
    # Authorship: the object's declared author must be the publisher (L-7).
    if "by" in obj and obj["by"] != by:
        findings.append(E("ERR:AUTH", "by",
                          "declared author %r is not the publishing identity %r; "
                          "authorship is assigned by the publisher at publish time"
                          % (obj["by"], by)))


# --------------------------------------------------------------------------
# Append-only version resolution from the filesystem
# --------------------------------------------------------------------------

def next_version_ref(obj_id, version):
    """``<id>.md`` is version 1; later versions are ``<id>.v<N>.md`` (L-14)."""
    return "%s.md" % obj_id if version == 1 else "%s.v%d.md" % (obj_id, version)


def sup_for(obj_id, version):
    """``sup`` for a revision.

    SPEC.md section 4 rule 2 writes the predecessor as ``<id>.v<N-1>``, but L-5
    locks ``REF := ID [":v" VERSION]`` and forbids dotted ids, so that literal
    form is not expressible as a REF (the shipped validator rejects it with
    ERR:SYN). The publisher emits the legal versioned REF instead; the section 4
    shorthand is reported to the owner as a normative-doc question and is not
    changed here.
    """
    if version == 1:
        return None
    if version == 2:
        return [obj_id]
    return ["%s:v%d" % (obj_id, version - 1)]


def scan_versions(objects_dir, obj_id, findings):
    """Versions already published for ``obj_id``, or None after a refusal."""
    bare_re = re.compile(r"^%s\.md$" % re.escape(obj_id))
    ver_re = re.compile(r"^%s\.v([1-9][0-9]*)\.md$" % re.escape(obj_id))
    seen = {}
    try:
        names = sorted(os.listdir(objects_dir))
    except OSError as exc:
        findings.append(E("ERR:SYN", objects_dir, "cannot list objects directory: %s" % exc))
        return None
    for name in names:
        m = ver_re.match(name)
        if m:
            n = int(m.group(1))
            if n in seen:
                findings.append(E("ERR:VER", objects_dir,
                                  "two files claim version %d of %r: %s and %s"
                                  % (n, obj_id, seen[n], name)))
                return None
            seen[n] = name
            continue
        if bare_re.match(name):
            if 1 in seen:
                findings.append(E("ERR:VER", objects_dir,
                                  "two files claim version 1 of %r: %s and %s"
                                  % (obj_id, seen[1], name)))
                return None
            seen[1] = name
    if not seen:
        return {}
    highest = max(seen)
    missing = [n for n in range(1, highest + 1) if n not in seen]
    if missing:
        findings.append(E(
            "ERR:VER", objects_dir,
            "version chain for %r has a hole: present %s, missing %s; refusing to "
            "append to a broken lineage (L-16 fail closed)"
            % (obj_id, sorted(seen), missing)))
        return None
    return seen


def read_object(path, findings):
    try:
        with io.open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        findings.append(E("ERR:SYN", path, "cannot read published file: %s" % exc))
        return None
    text = decode_utf8(raw, findings)
    if text is None:
        return None
    return parse_strict(text.strip(), findings)


def write_once(path, payload, findings):
    """Create ``path`` and fail closed if it already exists (never rewrite)."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | int(getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        findings.append(E("ERR:VER", path,
                          "refuses to rewrite a published file (L-14): the target "
                          "already exists; publish a new version instead"))
        return False
    except OSError as exc:
        findings.append(E("ERR:SYN", path, "cannot write: %s" % exc))
        return False
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


# --------------------------------------------------------------------------
# Announce packet (SPEC.md section 4 rule 3)
# --------------------------------------------------------------------------

def announce_packet(obj, version, by, to, msg_id):
    """An ``assert`` naming the new ref, in canonical key order (L-4).

    ``update`` is reserved for a receiver-side mutation and requires ``ops``
    (validated), so a publication announce - a new version the receiver did not
    hold - is an ``assert`` with the versioned ref and the predecessor in
    ``base``. The line is compact and key-ordered, so it validates as a packet.
    """
    ref = "%s:v%d" % (obj["id"], version) if version > 1 else obj["id"]
    line = {
        "v": 2,
        "id": msg_id,
        "tk": obj["tk"],
        "prj": obj["prj"],
        "f": by,
        "t": to,
        "a": "assert",
        "s": ref,
        "rq": "rev",
    }
    if version > 1:
        line["base"] = "%s:v%d" % (obj["id"], version - 1)
    return line


def canonical_packet_line(line):
    return json.dumps(line, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def emit(findings, as_json=False):
    for f in findings:
        if as_json:
            continue
        sys.stdout.write("<publish>: %s: %s: %s\n" % (f["code"], f["field"], f["msg"]))
    if as_json:
        sys.stdout.write(json.dumps(
            {"ok": False, "findings": findings}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return EXIT_INVALID


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sym-publish.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Write-once object publisher for SYM-2P/1.0 (stdlib only). "
                    "Append-only versions with sup and an incremented v; refuses "
                    "to rewrite a published file.",
        epilog=(
            "exit codes: 0=published (or idempotent no-op), 1=refused (typed "
            "diagnostic), 2=usage/IO error.\n"
            "typed codes: ERR:SYN (input), ERR:VER (version/lineage), "
            "ERR:AUTH (authorship).\n"
            "examples:\n"
            "  sym-publish.py --root delegation/proj --by cos draft.json\n"
            "  sym-publish.py --root delegation/proj --by cos --announce --to relay draft.json\n"
            "  cat draft.json | sym-publish.py --root delegation/proj --by cos -\n"
            "  sym-publish.py --root delegation/proj --by cos --dry-run draft.json\n"
            "  sym-validate.py --verify-hashes --kind object delegation/proj/objects/e3.v2.md\n"
        ),
    )
    parser.add_argument("file", nargs="?", default="-", metavar="FILE",
                        help="hash-less object JSON; '-' reads stdin (default)")
    parser.add_argument("--root", metavar="DIR", required=True,
                        help="delegation directory for the project; objects are written "
                             "to <root>/objects/ (the coordinator owns placement)")
    parser.add_argument("--by", metavar="ID", required=True,
                        help="publishing role id (object 'by'; L-7 stable identity)")
    parser.add_argument("--at", metavar="ISO8601Z",
                        help="creation timestamp override (default: now, UTC)")
    parser.add_argument("--announce", action="store_true",
                        help="emit the canonical packet line naming the new ref")
    parser.add_argument("--to", metavar="ID",
                        help="announce recipient (required with --announce)")
    parser.add_argument("--msg-id", metavar="ID",
                        help="announce message id (default: pub-<content hash prefix>, "
                             "stable across retries)")
    parser.add_argument("--version", metavar="N", type=int,
                        help="require a specific version; a version already published "
                             "with different content is refused")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan, write nothing")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit a JSON report instead of text lines")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the OK line")
    args = parser.parse_args(argv)

    findings = []

    if not ID_RE.match(args.by or ""):
        sys.stderr.write("sym-publish.py: --by must be an ID, got %r\n" % (args.by,))
        return EXIT_USAGE
    if args.at and not ISO_Z_RE.match(args.at):
        sys.stderr.write("sym-publish.py: --at must be ISO-8601 UTC (…Z), got %r\n"
                         % (args.at,))
        return EXIT_USAGE
    if args.announce and not args.to:
        sys.stderr.write("sym-publish.py: --announce requires --to <recipient-id>\n")
        return EXIT_USAGE
    if args.to and not ID_RE.match(args.to):
        sys.stderr.write("sym-publish.py: --to must be an ID, got %r\n" % (args.to,))
        return EXIT_USAGE
    if args.msg_id and not ID_RE.match(args.msg_id):
        sys.stderr.write("sym-publish.py: --msg-id must be an ID, got %r\n"
                         % (args.msg_id,))
        return EXIT_USAGE
    if args.version is not None and args.version < 1:
        sys.stderr.write("sym-publish.py: --version must be an integer >= 1\n")
        return EXIT_USAGE

    if not os.path.isdir(args.root):
        sys.stderr.write("sym-publish.py: --root is not a directory: %s\n"
                         "(the publisher writes into <root>/objects/ and never "
                         "invents a delegation tree)\n" % args.root)
        return EXIT_USAGE
    objects_dir = os.path.join(args.root, "objects")

    if args.file == "-":
        raw = sys.stdin.buffer.read()
        locator = "<stdin>"
    else:
        locator = args.file
        try:
            with io.open(args.file, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            sys.stderr.write("sym-publish.py: cannot read %s: %s\n" % (args.file, exc))
            return EXIT_USAGE

    text = decode_utf8(raw, findings)
    obj = parse_strict(text.strip(), findings) if text is not None else None
    if obj is None:
        return emit(findings, args.as_json)

    check_input(obj, findings, args.by)
    if findings:
        return emit(findings, args.as_json)

    obj_id = obj["id"]
    if not os.path.isdir(objects_dir):
        if args.dry_run:
            pass
        else:
            try:
                os.makedirs(objects_dir)
            except OSError as exc:
                sys.stderr.write("sym-publish.py: cannot create %s: %s\n"
                                 % (objects_dir, exc))
                return EXIT_USAGE

    present = scan_versions(objects_dir, obj_id, findings)
    if present is None:
        return emit(findings, args.as_json)

    tip_version = max(present) if present else 0
    tip_path = os.path.join(objects_dir, next_version_ref(obj_id, tip_version))
    tip_obj = None
    if tip_version:
        tip_obj = read_object(tip_path, findings)
        if tip_obj is None:
            if not findings:
                findings.append(E("ERR:VER", tip_path,
                                  "published tip is unreadable; refusing to append "
                                  "to an unverified lineage"))
            return emit(findings, args.as_json)

    if tip_obj is not None and fingerprint(tip_obj) == fingerprint(obj):
        # Same author, same content: the publication already exists (L-11).
        version = tip_version
        no_op = True
    else:
        version = tip_version + 1
        no_op = False
    target = os.path.join(objects_dir, next_version_ref(obj_id, version))

    # Caller-supplied version and lineage must agree with what the disk says.
    if "v" in obj and obj["v"] != version:
        findings.append(E("ERR:VER", "v",
                          "declared v=%r but the published chain resolves to v=%d "
                          "(published: %s)"
                          % (obj["v"], version, sorted(present) or "none")))
    if "sup" in obj:
        wanted = sup_for(obj_id, version)
        if obj["sup"] != wanted:
            findings.append(E("ERR:VER", "sup",
                              "declared sup=%r does not match the resolved lineage %r"
                              % (obj["sup"], wanted)))
    if args.version is not None and args.version != version:
        findings.append(E("ERR:VER", "--version",
                          "requested v=%d but the chain resolves to v=%d (published: %s)"
                          % (args.version, version, sorted(present) or "none")))
    if findings:
        return emit(findings, args.as_json)

    stamp = args.at or obj.get("at") or _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    final = {k: v for k, v in obj.items() if k not in MANAGED_KEYS}
    final["by"] = args.by
    final["at"] = stamp
    final["v"] = version
    sup = sup_for(obj_id, version)
    if sup:
        final["sup"] = sup
    final["hash"] = content_hash(final)
    payload = canonical_bytes(final) + b"\n"
    ref = "%s:v%d" % (obj_id, version)

    packet_line = None
    if args.announce:
        msg_id = args.msg_id or ("pub-" + final["hash"][7:15])
        packet_line = canonical_packet_line(
            announce_packet(final, version, args.by, args.to, msg_id))

    if no_op:
        if not args.quiet:
            sys.stdout.write("OK %s %s already published (content unchanged, "
                             "nothing written)\n" % (ref, target))
        if args.announce:
            # Nothing new was published, so there is nothing to announce.
            pass
        return EXIT_OK

    if args.dry_run:
        sys.stdout.write("publisher: sym-publish.py\n")
        sys.stdout.write("mode: dry-run\n")
        sys.stdout.write("root: %s\n" % args.root)
        sys.stdout.write("would write (target-relative):\n")
        sys.stdout.write("  %s\n" % os.path.join("objects",
                                                 os.path.basename(target)))
        sys.stdout.write("ref: %s\n" % ref)
        sys.stdout.write("hash: %s\n" % final["hash"])
        if packet_line:
            sys.stdout.write("announce: %s\n" % packet_line)
        sys.stdout.write("result: dry-run, no files written\n")
        return EXIT_OK

    if not write_once(target, payload, findings):
        return emit(findings, args.as_json)

    if not args.quiet:
        sys.stdout.write("OK %s %s %s\n" % (ref, target, final["hash"]))
    if packet_line:
        sys.stdout.write(packet_line + "\n")
    sys.stdout.flush()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
