---
name: sym2p
description: Use when validating or emitting SYM-2P/1.0 packets or durable objects. Stdlib validator with typed fail-closed diagnostics, brief and receipt packet templates, and a worked review-fix-verify-merge example.
version: 1.0.0
author: the Protean publication
license: MIT
---

# SYM-2P/1.0 — packet validator and object conventions

Canonical compact JSON over durable file artifacts is the only inter-agent
surface. This skill validates it and fails closed on anything ambiguous.

Provenance:
- Normative specification: `SPEC.md` in this repository (read that first).
- Evidence and provenance: `AUDIT/` (never normative).

This skill documents the shipped implementation. It states no rule that `SPEC.md`
does not already state.

## Quick start

    python3 scripts/protean-sym2p/sym-validate.py --help                  # exits 0
    python3 scripts/protean-sym2p/sym-validate.py packet.json             # one packet
    python3 scripts/protean-sym2p/sym-validate.py examples/review-fix-verify-merge.jsonl
    python3 scripts/protean-sym2p/sym-validate.py --kind object dispute.json
    python3 scripts/protean-sym2p/sym-validate.py --state receiver-state.json packets.jsonl
    python3 scripts/protean-sym2p/sym-validate.py --now 2026-09-17T03:00:00Z packet.json
    python3 scripts/protean-sym2p/sym-validate.py --strict-canonical packets.jsonl
    python3 scripts/protean-sym2p/sym-validate.py --canonicalize packets.jsonl
    python3 scripts/protean-sym2p/sym-validate.py --verify-hashes --kind object objects.jsonl
    python3 scripts/protean-sym2p/sym-publish.py --root <delegation-dir> --by <role-id> draft.json
    python3 tests/run-tests.py                              # focused suite

Exit codes: `0` every document valid · `1` at least one invalid (typed
diagnostics printed) · `2` usage / IO / configuration error.

`.jsonl` is read one object per line (the wire carrier). Any other suffix is
tried as one whole-file object first, then line by line.

## The locked surface this validates

- Wire field `v` is the integer `2`. "SYM-2P/1.0" is the profile name, not a
  wire value. A major version other than 2 is rejected.
- Required on every packet: `v,id,tk,prj,f,t,a`. Everything else is
  act-conditional and omitted when absent — never emitted as `null`.
- Canonical key order is exact:
  `v,id,tk,prj,f,t,a,s,st,cf,err,cov,ev,ce,cond,ops,rq,base,exp,auth,ext`.
  Reordering, extra keys, and unknown keys are rejections
  (`additionalProperties: false` on the envelope).
- Grammar: `ID := [a-z][a-z0-9_-]{0,31}`; `REF := ID [":v" [1-9][0-9]*]`.
  A version never hides inside the identifier.
- Enums are fixed and source-verbatim:
  acts `assign assert question answer propose accept reject challenge verify update escalate done`;
  requests `ack upd ver rev exec src exp full decide`;
  statuses `observed inferred assumed proposed disputed rejected verified`;
  error codes `ERR:SYN ERR:SEM ERR:REF ERR:VER ERR:EXP ERR:AUTH ERR:AMB ERR:POL`.
- Scores `cf`, `err`, `cov` are integers 0–99 and are routing signals only.
  Floats, booleans, and out-of-range values are rejected. Do not compare raw
  scores across heterogeneous profiles.
- `ev`/`ce` are unique arrays of REFs; `t` is a single recipient (a group send
  is N packets plus a routing-state row).
- `ops` (act `update`) are typed delta operations (`add|remove|set|move`) on a
  restricted JSON Pointer subset; wildcard mutation is rejected.

Objects (`--kind object`) carry the header block of `SPEC.md` section 4: `id,type,v,tk,prj,by,at,hash,ttl,body` plus `sup/deps/acl/ext` and
the per-type surface. `hash` is `sha256:<64 hex>` over canonical content;
`ttl` is one of `ephemeral|task|project|regulated`; a resolved `dispute` must
carry a resolution record whose `positions_preserved` has the same length as
`positions` (dissent is never deleted).

## Fail-closed semantics

Every rejection is a typed diagnostic on stdout as
`<file>:<line>: <CODE>: <field>: <message>`. The validator never guesses, never
partially applies, and never falls back to a lenient interpretation.

| Situation | Result |
|---|---|
| invalid JSON, duplicate object key, BOM, non-UTF-8 | `ERR:SYN` |
| unknown enum, bad ID/REF grammar, float score, extra key, key-order break | `ERR:SYN` |
| `v` not exactly integer 2 | `ERR:SYN` |
| non-canonical whitespace under `--strict-canonical` | `ERR:SYN` |
| `update` without `base` or `ops` | `ERR:SYN` |
| challenge without `st:"disputed"`/counter-evidence; verify without evidence | `ERR:SEM` |
| resolved dispute with no resolution record, or a dropped losing position | `ERR:SEM` |
| `rq:"exec"` without an authorization envelope | `ERR:AUTH` |
| malformed authorization (bad scope/ref/timestamps, expiry before approval) | `ERR:AUTH` |
| `auth.expires_at` at or before `--now` | `ERR:EXP` |
| `base` older than the version in `--state` | `ERR:VER` (reports the receiver's current version; the packet must request `rq:"full"`) |
| `ext.err:"ERR:VER"` packet that does not request `rq:"full"` or omit `ext.have` | `ERR:VER` |
| `--require-refs` and an `ev`/`ce`/`s` ref is unknown | `ERR:REF` |
| multi-recipient `t` | `ERR:POL` |
| duplicate `(f,id)` in this run | `ERR:DUP` |
| object body hash mismatch (with `--verify-hashes`) | `ERR:SYN` on `hash` |

### Hash verification (opt-in)

`hash` was previously format-checked only. With `--verify-hashes`, the
validator recomputes the hash and fails closed on mismatch, enforcing the
documented rule (AUDIT/protean-sym2p/provenance.md): sha256 over the canonical
compact `body` with sorted keys. Header fields (`v`, `by`, `at`, `ttl`,
`acl`, `sup`, `deps`) sit outside the hash by design. The flag is opt-in —
enforcing content-hash integrity is a receiver-side policy choice — and is a
no-op for packets and `--canonicalize` runs. The test suite pins both
behaviors (mismatch rejected with the flag, format-only without it), including
a `--verify-hashes` run over the worked example so a future hash-scope change
fails loudly instead of silently.

### About `ERR:DUP`

`ERR:DUP` is a validator-local code, not a wire code. The live protocol is
idempotent: a retry keeps the original `id` and payload hash and the receiver
returns the prior terminal response without re-running work. A static
validator has no prior terminal response to return, so it fails closed rather
than assuming the duplicate is a legitimate retry. Pass
`--allow-duplicates` when you are deliberately replaying a stream; the duplicate
is then printed as a warning and the exit code stays 0.

### Stale base, never a silent merge

Without `--state`, `base` is only syntax-checked (a run with no receiver
knowledge cannot know what is current). With `--state`, a base older than the
receiver's version yields `ERR:VER` and the fix is explicit: resend with
`rq:"full"` for a snapshot, or recompute the delta against the current version.
The validator contains no merge path, so none can be invoked accidentally.

### Protected semantics (P0–P9)

`cond/ev/ce` (safety, evidence, counter-evidence), dispute positions with
`dtype`/`need` (dissent, scope, provenance), and `err/cov/cf`, `auth`, `base`,
`hash`, `exp` (uncertainty, irreversibility, approval, integrity) are preserved
by the act-conditional checks above. Dropping a P-class field for compression is
a defect, not an optimization — encode it, do not delete it.

## Publishing objects (the append-only write path)

`sym-publish.py` is the producer half of the object contract. M-5 requires
object writes to be append-only versions and the tooling to refuse to rewrite a
published file (L-14); the validator checks shape on the read path, and this is
the write path.

    python3 scripts/protean-sym2p/sym-publish.py --root <delegation-dir> --by <role-id> draft.json
    python3 scripts/protean-sym2p/sym-publish.py --root <dir> --by cos --announce --to relay draft.json
    cat draft.json | python3 scripts/protean-sym2p/sym-publish.py --root <dir> --by cos -
    python3 scripts/protean-sym2p/sym-publish.py --root <dir> --by cos --dry-run draft.json
    python3 scripts/protean-sym2p/sym-validate.py --verify-hashes --kind object <dir>/objects/<id>.v2.md

Exit codes match the validator: `0` published or an idempotent no-op, `1`
refused with a typed diagnostic, `2` usage or IO error. Typed codes: `ERR:SYN`
(input not canonical, not well-formed, or an unverifiable declared hash),
`ERR:VER` (version or lineage conflict, including a refusal to rewrite),
`ERR:AUTH` (the declared author is not the publishing identity).

- **Input is a hash-less object.** `id`, `type`, `tk`, `prj`, `ttl`, `body`, and
  the per-type surface are the caller's. `v`, `sup`, `hash`, `by`, `at` are
  assigned at publish time; supplying one is accepted only when it agrees with
  what the publisher resolved, and a disagreement is a typed refusal.
- **Version resolution is read from the filesystem**, never from the input:
  `<id>.md` is version 1 and revisions are `<id>.v<N>.md`, so a repeat publish of
  unchanged content is an idempotent no-op (L-11) and changed content appends
  exactly one version. A version-chain hole, two files claiming one version, or a
  published tip that does not parse is refused rather than appended to.
- **The refusal is a real one.** The file is created with `O_CREAT|O_EXCL`, so an
  existing published file cannot be overwritten even by a concurrent writer;
  `--version N` lets a caller pin the target, and a version already published
  with different content is refused.
- **The content hash is the one `--verify-hashes` recomputes** (compact JSON,
  sorted keys, UTF-8, `hash` field excluded), so a published file verifies
  against the shipped validator. A declared hash is verified against the
  document as given and never silently recomputed.
- **Output is canonical compact JSON, key-sorted** — the publisher normalizes
  whatever the caller emits, which is where canonicalize-before-send belongs:
  `--strict-canonical` stops being a trap for nondeterministic emitters.
- **`sup` is emitted as a legal REF.** SPEC.md section 4 rule 2 writes the
  predecessor as `<id>.v<N-1>`, but L-5 locks `REF := ID [":v" VERSION]` and
  forbids dotted ids, so the publisher emits `<id>` for version 2 and
  `<id>:v<N-1>` thereafter — the form the validator accepts. The section 4
  shorthand is a normative-doc question, not an implemented rule.
- **`--announce` emits the packet naming the new ref** (`a:"assert"`,
  `s` = the new versioned ref, `base` = the predecessor for a revision,
  `rq:"rev"`), in canonical key order so it validates as a packet. `update` is
  not used: it is a receiver-side mutation and requires `ops`. Routing-state rows
  (M-9) stay out of scope; the caller routes the announce.

The publisher enforces the header block and the write path, not the validator's
per-type checks. Run `sym-validate.py --verify-hashes --kind object` on the
published file for the full contract; the suite does exactly that for every case.

## Files

- `scripts/protean-sym2p/sym-validate.py` — the validator (stdlib only, Python 3.8+).
- `scripts/protean-sym2p/sym-publish.py` — the write-once object publisher
  (stdlib only, Python 3.8+).
- `templates/protean-sym2p/brief-packet.json` — canonical `assign` brief packet.
- `templates/protean-sym2p/receipt-packet.json` — canonical `done` receipt packet.
- `examples/protean-sym2p/review-fix-verify-merge.jsonl` — worked
  review → fix → verify → merge loop: inbound English scope, relay
  authorization, a stale-base attempt and its typed `ERR:VER` reply, the
  corrected delta, verification, a challenge plus dispute object, the authorized
  merge execution, and the closing `done` with a decision object holding the
  English user-facing summary.
- `tests/run-tests.py` and `tests/fixtures/**` — focused suite in two sections:
  validator cases (valid fixtures pass, malformed / stale / duplicate /
  protected-semantic fixtures fail with typed diagnostics) and publisher cases
  (append-only versioning, `sup` chain, overwrite refusal, idempotent no-op,
  and every published file re-validated with `--verify-hashes`).

Templates are pretty-printed for humans and stay valid JSON. The wire form is
compact: run `--canonicalize` to normalize a document before writing it as a
packet line, and `--strict-canonical` in review to prove it.

## English boundary

English is required at the user boundary (relay), in dispute records, and in
the authorization approval record, which holds the exact user-approved action
and scope. Packets carry a reference (`auth.ref` = `approval:<id>`), not the
private conversation. Keep the human-facing text inside object `body` fields or
`cond` strings — never invent prose fields inside a packet envelope.
