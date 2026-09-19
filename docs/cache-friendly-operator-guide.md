# Operating SYM-2P with prompt-prefix caching

**Non-normative.** This is an operator's guide. The norm is `SPEC.md`; nothing
here changes a wire byte, an enum, a key order, a version, or a rule. This file
is not part of the installed payload (`protean-ingredient.json` lists the payload
paths) — it is repository documentation for whoever runs a project on this
protocol.

## Why this exists

`SPEC.md` section 8 rule 4 is deliberate and stays in force:

> Prompt-prefix reuse across calls is a platform-conditional optimization, not a
> channel. Byte-identical prefixes do not guarantee shared caching or identical
> generation across heterogeneous providers, so no correctness, latency, or cost
> claim may depend on it.

That rule forbids *depending* on prompt caching. It does not forbid *capturing*
it: reuse of an unchanged prefix is the cheapest saving in the design, larger
than any wire-format compression, and it is lost by accident rather than by
decision. So this guide covers the two things the rule leaves open — how to make
the prefix reusable, and how to observe whether a hit actually happened — and it
keeps the rule's boundary intact: every claim of value still has to be measured
(S-2, S-3), never assumed.

## 1. Shared prefix discipline

Give every agent in one project a **byte-identical** prefix, ordered static
first:

1. role definition (what this agent is, what it owns, what it must never do);
2. protocol specification and the fixed enums (section 3 of `SPEC.md`);
3. validation rules (the rejection surface the agents must not trip).

Then, and only then, dynamic content: task state, blackboard refs, packet
bodies, retrieved documents, the user's request.

Why ordering is the whole game: prefix matching starts at the first byte and
stops at the first difference. A stable head is what makes the tail's cost
avoidable at all; a single volatile token near the top makes everything after it
new again. Rules that follow:

- **One project, one prefix.** Two projects get two prefixes. Never one prefix
  per agent — per-agent differences belong in the dynamic tail, or the prefix
  stops being shared.
- **Build the prefix once and store it** (a checked-in file, an object, a
  constant). Do not assemble it per call from a template with substitutions;
  a template that interpolates a name, date, or counter into the head produces
  a different prefix every call.
- **Keep the static block ahead of the volatile block, always.** If a section is
  occasionally dynamic, it belongs in the tail — a mostly-static section that
  changes sometimes still invalidates everything after it every time it changes.

## 2. Enum and key stability

The fixed key order of L-4 and the fixed enum strings of section 3 are what make
packets comparable across senders, signable, and log-stable. The same property is
what makes the static prefix reusable across calls: identical bytes are the
precondition for reuse.

So, operationally: do not reword enum values, do not "improve" the wording of the
protocol block per call, do not re-serialize the static block with a different
key order or different whitespace, and do not let a formatter or a pretty-printer
touch it. A rewritten head is a new prefix.

Section 8 rule 5 states the boundary that keeps this honest:

> Canonical key order buys comparability, signing, and logging stability. It is a
> validation discipline, not a generation guarantee fleet-wide.

In other words: byte-stability makes a prefix *eligible* for reuse. It does not
promise a hit. A hit additionally requires that the provider supports it, that
the prefix clears that provider's minimum length for the model in use, and that
the call lands in the same cache scope (account/organization, model, and the
provider's retention window). Treat eligibility and hit rate as two different
numbers — the second one is measured, per section 4 below.

## 3. What not to do

Each of these silently destroys hits. None of them raises an error; the only
symptom is a bill that never goes down.

- **Per-agent personalization at the top.** A name, a greeting, a tone tweak, a
  "you are the third specialist" line — all of it belongs after the static block.
- **Timestamps, request ids, nonces, "the current time is …"** anywhere in the
  prefix region. A clock in the head means no two calls ever share a prefix.
- **Task state, blackboard refs, packet bodies, or fetched documents before the
  static block.** Order is static head, dynamic tail.
- **Re-serializing the static block per call** (key order drift, whitespace
  drift, re-escaped non-ASCII, a different `ensure_ascii` setting). Different
  bytes, different prefix.
- **Rotating models per call**, or per agent, inside one project: cache scope is
  per model, so a mixed fleet shares nothing.
- **Optional sections in the head** ("include the compliance block if …"). A head
  that varies by call is not a head.
- **Putting meaning in the prefix.** The prefix is instructions, not a channel:
  nothing may be transmitted by an agent editing its prefix, and no agent may
  infer anything from another agent's cache state or assume a cache is warm
  (section 8 rules 2 and 3; L-18). If a receiver needs something, it is in the
  object or it is requested explicitly with `rq:"src"`, `"full"`, or `"exp"`
  (section 8 rule 6) — never inferred from what "should already be cached".

## 4. Measurement: observe the hit, do not assume it

Confirm hits on the provider actually in use, from the response usage fields —
the provider's numbers are authoritative, and reasoning about it is not.

**Anthropic (Claude API).** Caching is opt-in: you mark the end of the reusable
content with a `cache_control` breakpoint, and prompt prefixes are assembled in
the order tools → system → messages. `usage.cache_creation_input_tokens` reports
tokens written to the cache; `usage.cache_read_input_tokens` reports tokens read
from it. A working prefix writes on the first call and reads on the next
identical call. Zero on both, across repeated identical prefixes, means no cache
formed — usually a prefix below that model's minimum cacheable length, or drift
in the head. The default cache lifetime is short (minutes); an extended lifetime
is available.

**OpenAI (Chat Completions / Responses).** Caching is automatic — no markers —
for prompts at or above the documented minimum length (1,024 tokens), and the
match extends in 128-token increments, so a hit often covers slightly less than
the whole stable prefix. `usage.prompt_tokens_details.cached_tokens` reports how
many input tokens were a hit; it is a subset of `prompt_tokens`, not an extra
field. Zero there means no hit.

**Verify the specifics against current provider documentation before quoting
any number.** Cache floors, retention windows, and the write/read price
multipliers are model-dependent and change:

- Anthropic: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching>
- OpenAI: <https://platform.openai.com/docs/guides/prompt-caching>

How to read the counters:

| Observation | Reading |
|---|---|
| write on every call, read never | the prefix is drifting, or is under the provider's floor |
| read on repeated identical calls | reuse is happening; measure the saving before claiming it |
| write on the first call, read thereafter, and the read counter tracks the static block size | the discipline in sections 1-3 is holding |
| either counter always zero, on a prefix you believe is stable | check the head for a timestamp, an id, or a re-serialization before blaming the provider |

Then keep the claim honest. A hit is a *cost and latency* effect on input tokens
for that call. It says nothing about task quality, and it does not reduce the
number of rounds, the storage, or the coordinator overhead — which is precisely
what S-3 requires to be counted before any economic claim is made. Prompt
caching is one term in that ledger, not the verdict.

## 5. What the discipline must never change

- **No correctness dependency.** A run must produce the same results with
  caching disabled. Before relying on a cached prefix in a project, run the same
  task with caching off and confirm the outcome is identical. If it is not, the
  prefix is carrying meaning and the discipline is wrong (L-18).
- **No channel, no shared state.** A warm cache is not memory, not a shared
  blackboard, and not evidence of anything another agent did. Everything an agent
  needs is in the object it was given or is requested explicitly (section 8).
- **No wire change.** The prefix is English/instructions around the protocol, not
  part of it. Packet bytes, key order, enums, and the profile version are
  untouched by anything in this guide, and no version increment follows from
  adopting it.
- **No new claim.** Sections 1-4 make the optimization observable. They do not
  make it guaranteed, and they do not license an unmeasured cost or latency
  claim — including in a reader-facing document.

## Related

- `SPEC.md` section 8 (no-latent-channel rule) and L-18 — the rule this guide is
  subordinate to.
- `SPEC.md` section 3 (fixed enums and key order), L-4 — the stability this guide
  depends on.
- `SPEC.md` section 11, S-2, S-3, S-9 — what still has to be measured before any
  value claim is made.
