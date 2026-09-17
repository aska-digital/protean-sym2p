# Provenance

## Sources

This repository is a projection of a private protocol specification lane. Three
private artifacts fed it:

| Source, described generically | Role in this projection |
|---|---|
| A protocol architecture lock | normative content: the locked items, the field table, the enums, the object conventions, the failure table, the protected semantics, the migration boundary, the open items, and the acceptance criteria |
| An input audit of the protocol's source material | evidence only: the mapping, assumption, adaptation, and question tables that informed the migration boundary and the open items. Summarized, not restated. |
| A protocol build lane (validator, templates, examples, tests) | the implementing tooling, projected here as `scripts/`, `templates/`, `examples/`, and `tests/` |

The private artifacts are not shipped and are not cited by path. Their content
reaches this repository only through the projection recorded above.

## What the projection changed

- Artifact headers, author lines, absolute paths, session identifiers, and ledger
  citations were removed.
- Role identifiers were replaced with neutral placeholders: `relay`, `cos`,
  `research`, `arch`, `design`, `builder`, `qa`. The wire grammar is unchanged:
  every placeholder is a legal `ID` under the locked grammar.
- Task identifiers in fixtures and examples were renamed to neutral values. The
  example file was renamed to `review-fix-verify-merge.jsonl`.
- Object hashes in the worked example were recomputed after the identifier
  renames, so the example stays internally consistent. Object hashes are sha256
  over the canonical compact body with sorted keys.

## What the projection did not change

- The wire field, the required field set, the exact canonical key order, the
  grammar, the enums, the error codes, the failure semantics, the protected
  semantics, and the acceptance criteria are carried as specified.
- No open item was resolved. The nine open items ship open.

## Limits

- Nothing here was verified against a live multi-agent deployment. The
  verification recorded in `verification-log.md` is a single-machine, static
  check of the shipped files.
- Transport signing is not implemented (open item O-1), so integrity rests on
  canonical sha256 computed in process.
