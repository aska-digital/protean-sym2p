# Verification log

Commands run against this repository when the projection was made, with their
real output. Host: macOS, Python 3.9.6. Nothing here is normative; the
normative specification is `../../SPEC.md`.

## internal-name leak gate

    $ python3 gates/check-internal-names.py .
    exit: 0

        clean: 42 files scanned, 0 findings

## protocol fixture suite

    $ python3 tests/run-tests.py
    exit: 0

        PASS help exits 0                                         exit=0
        PASS template/brief-packet.json                           exit=0
        PASS template/receipt-packet.json                         exit=0
        PASS worked example (auto)                                exit=0
        PASS worked example (strict canonical)                    exit=0
        PASS valid packet-assert                                  exit=0
        ... (21 lines omitted)
        PASS non-canonical serialization                          exit=1
        PASS duplicate allowed -> warning only                    exit=0
        PASS unreadable input is a usage/IO error                 exit=2
        
        30/30 cases passed
        ALL PASS

## validator usage surface

    $ python3 scripts/protean-sym2p/sym-validate.py --help
    exit: 0

        usage: sym-validate.py [-h] [--kind {auto,packet,object}] [--state FILE]
                               [--require-refs] [--now ISO8601Z] [--allow-duplicates]
                               [--strict-canonical] [--canonicalize] [--json]
                               [--quiet]
                               [FILE ...]
        
        ... (25 lines omitted)
        examples:
          sym-validate.py packet.json
          sym-validate.py --kind packet examples/protean-sym2p/review-fix-verify-merge.jsonl
          sym-validate.py --state state.json --require-refs packets.jsonl
          sym-validate.py --now 2026-09-17T00:00:00Z --strict-canonical packets.jsonl
          sym-validate.py --canonicalize packets.jsonl

## templates and worked example

    $ python3 scripts/protean-sym2p/sym-validate.py --quiet templates/protean-sym2p/brief-packet.json templates/protean-sym2p/receipt-packet.json examples/protean-sym2p/review-fix-verify-merge.jsonl
    exit: 0

        

## worked example in strict canonical mode

    $ python3 scripts/protean-sym2p/sym-validate.py --strict-canonical --quiet examples/protean-sym2p/review-fix-verify-merge.jsonl
    exit: 0

        

## unreadable input (defect fixed during projection)

    $ python3 scripts/protean-sym2p/sym-validate.py /tmp/absent-input.jsonl
    exit: 2

        /tmp/absent-input.jsonl: ERR:SYN: cannot read file: [Errno 2] No such file or directory: '/tmp/absent-input.jsonl'

## standalone installer dry run

    $ bash install.sh --target /tmp/audit-install --dry-run
    exit: 0

        installer: protean-sym2p 1.0.0
        mode: dry-run
        target: /tmp/audit-install
        network calls: 0
        install targets:
          SPEC.md
          skills/sym2p
          scripts/protean-sym2p
          templates/protean-sym2p
          examples/protean-sym2p
          AUDIT/protean-sym2p
        planned writes (target-relative):
          /tmp/audit-install/SPEC.md
          /tmp/audit-install/skills/sym2p/SKILL.md
          /tmp/audit-install/scripts/protean-sym2p/sym-validate.py
          /tmp/audit-install/templates/protean-sym2p/brief-packet.json
          /tmp/audit-install/templates/protean-sym2p/receipt-packet.json
          /tmp/audit-install/examples/protean-sym2p/review-fix-verify-merge.jsonl
          /tmp/audit-install/AUDIT/protean-sym2p/README.md
          /tmp/audit-install/AUDIT/protean-sym2p/provenance.md
        result: dry-run, no files written

