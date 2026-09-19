# Changelog

All notable changes to this repository are recorded here. The format is a short
entry per release: what changed, why, and how it was verified.

## Unreleased

- **What:** `scripts/protean-sym2p/sym-publish.py`, the write-once object
  publisher (stdlib only): it assigns `v`, `sup`, `hash`, `by`, and `at`,
  resolves the next version from `<root>/objects/` (never from the input), writes
  canonical compact JSON, refuses to rewrite a published file, and can emit the
  canonical packet announcing the new ref. `tests/run-tests.py` gains a second
  section that exercises that write path end to end and re-validates every
  published file with `sym-validate.py --verify-hashes`, so the write path and
  the read path are proved to agree on the canonical content hash.
- **Why:** M-5 states that "the tooling refuses to rewrite a published file", and
  append-only versioning (L-14) was convention plus install docs: nothing
  enforced it on the write path, so `sym-validate.py` checked object shape only.
- **Verification:** `python3 tests/run-tests.py` — 70/70 cases (33 validator, 37
  publisher) with every published file independently hash-verified;
  `python3 gates/protean-sym2p/check-internal-names.py .` clean;
  `python3 -m unittest discover -s tests` OK. Full output in the pull request.
- **Contract:** unchanged. No wire bytes, no enum, no key order, no gate, no
  install target, and no manifest entry changed; `scripts/protean-sym2p/` was
  already a declared payload path, and adding an optional file to it is a
  compatible addition (CONTRIBUTING).
- **Not changed:** `SPEC.md`. The publisher emits `sup` as a legal REF and the
  section 4 rule 2 shorthand is left as filed for the owner (`<id>.v<N-1>` is not
  expressible under L-5's grammar).

## 1.0.0

- **What:** the first release of the `protean-sym2p` ingredient: the capability payload,
  the machine descriptor `protean-ingredient.json`, the standalone installer
  `install.sh`, the declared gates under `gates/protean-sym2p/`, and the test suite under
  `tests/`.
- **Why:** the capability was previously reachable only from inside a private
  working tree. This repository is its single public home, installable on its own.
- **Verification:** the declared gates and `python3 -m unittest discover -s tests`
  pass from a clean checkout of this commit. See the pull request body for the
  commands and their output.
- **Contract:** `SYM-2P: a compact versioned agentic message language - one canonical JSON packet per line over durable text artifacts - with validator, enums, and fixtures.`
- **License:** MIT. The committed `LICENSE` file is authoritative.
