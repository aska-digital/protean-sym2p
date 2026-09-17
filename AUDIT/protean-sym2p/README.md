# AUDIT - evidence and provenance

Boundary: **`AUDIT/` carries evidence and provenance. Normative statements live
only in `../SPEC.md`.**

Nothing in this directory may be read as a rule. Where a file here and `SPEC.md`
disagree, `SPEC.md` governs and the disagreement is a defect in this directory.

Contents:

- `provenance.md` - the sources this projection was taken from, what was
  verified when the projection was made, and what was deliberately not carried
  across.
- `verification-log.md` - the exact commands run against this repository at
  projection time and their output.

Two things this directory deliberately does not do:

- It does not restate the analysis that produced the specification. The
  specification cites its own locked items; the mapping, assumption, and question
  tables that preceded it are summarized as the specification's migration
  boundary and open items.
- It does not close any open item. The nine open items are carried in `SPEC.md`
  section 10 exactly as open.
