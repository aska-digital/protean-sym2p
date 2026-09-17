# Changelog

All notable changes to this repository are recorded here. The format is a short
entry per release: what changed, why, and how it was verified.

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
