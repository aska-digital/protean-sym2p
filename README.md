SYM-2P: a compact versioned agentic message language - one canonical JSON packet per line over durable text artifacts - with validator, enums, and fixtures.

# protean-sym2p

The protocol ingredient of the Protean Kit distribution. It carries the
normative specification, the stdlib validator, the packet templates, the worked
example, and the fixture suite.

## What it installs and where

| Path | Contents |
|---|---|
| `SPEC.md` | the normative specification |
| `skills/sym2p/` | the usage skill |
| `scripts/protean-sym2p/` | `sym-validate.py`, stdlib only |
| `templates/protean-sym2p/` | canonical brief and receipt packets |
| `examples/protean-sym2p/` | the worked review, fix, verify, merge loop |
| `AUDIT/protean-sym2p/` | evidence and provenance (never normative) |
| `gates/protean-sym2p/` | the leak gate and the blocklist |

## Install

```bash
bash install.sh --target <dir>
bash install.sh --target <dir> --dry-run
```

Bash and coreutils only, zero network calls, every written path printed, and no
`--target` means no run. A dry run writes nothing.

Installs alone with this command, resolving only its required dependencies listed
in its manifest entry. Optional relationships are reported, not fetched.

## Requirements and recommendations

Requires none. Recommends `protean-ops`: the protocol's routing-state rows are
records, and the ops ingredient carries the schemas and gates that check them.
The recommendation is documentary and never affects install order.

## Status: specified and built, with open items

`SPEC.md` defines the protocol. The validator, the templates, the worked example,
and the fixture suite ship with this repository and are exercised by its gates.
The validator implements the operational subset the specification names, and it
rejects against the full enums.

Open items O-1 to O-9 remain open and are carried in `SPEC.md` section 10. No open
item is closed by this repository, and none is presented as decided.

## Use

```bash
python3 scripts/protean-sym2p/sym-validate.py --help
python3 scripts/protean-sym2p/sym-validate.py <packet-or-stream>
python3 scripts/protean-sym2p/sym-validate.py --state <receiver-state.json> <packets.jsonl>
python3 scripts/protean-sym2p/sym-validate.py --strict-canonical <packets.jsonl>
python3 tests/run-tests.py
```

Exit codes: 0 every document valid, 1 at least one invalid with typed
diagnostics, 2 usage, IO, or configuration error. `.jsonl` is read one object per
line: that is the wire carrier.

## Gates

| Gate | Command (declared) |
|---|---|
| internal-name gate | `python3 gates/protean-sym2p/check-internal-names.py .` |
| protocol suite | `python3 tests/run-tests.py` |

The suite gives every valid fixture a pass and every malformed, stale, duplicate,
or protected-semantic fixture a typed rejection.

## Offline and cache behaviour

Used through the composer, this ingredient is fetched once from its pinned tag
and reused from a content-addressed cache keyed by commit SHA. `--offline`
performs zero network calls and fails closed when the cache entry is absent.

## Limits and open items

- Transport signing is not implemented (O-1). Integrity is a canonical sha256
  computed in process, on a single-machine trust assumption.
- Reference resolution and expiry checks need the caller to supply receiver state
  and a reference clock. Without them, those fields are syntax-checked only, and
  the skill says so.
- Phase 3 routing predicates are named and not implemented (O-3).
- The protocol's routing semantics are described here; the record schemas that
  carry routing state belong to `protean-ops`.

## License

MIT. The committed `LICENSE` file is authoritative.
