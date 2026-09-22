# Protean Hub Council — SYM-2P Rework Proposal

**Proposal date:** 2026-09-20 (UTC)
**Author:** Protean Hub Council
**Status:** PROPOSAL — UNMERGED. Owner review required.

---

## 0. Reading key

Claims carry exactly one tag:

- **FACT [S#]** — attested by a primary source in `source-ledger.json`, HTTP 200 verified on 2026-09-20.
- **RECOMMENDATION** — Council judgment grounded in cited facts.
- **ASSUMPTION** — premise the proposal rests on; must be confirmed before the dependent phase proceeds.
- **OPEN** — cannot be decided by architecture/design seats; requires owner or Council decision.

---

## 1. Executive summary

This proposal reworks the SYM-2P protocol to integrate with the Public Verifiable Provenance Hub (Workstream A) while improving its own E2EE, identity, and selective-disclosure layers. The key change: SYM-2P events gain a CloudEvents outer envelope, the existing wire packet (`v: 2`, canonical key order, act-conditional fields) remains intact inside, and a narrow contract ensures the hub logs only hashes and signatures — never plaintext.

**FACT:** RFC 9901 — *Selective Disclosure for JSON Web Tokens (SD-JWT)* — defines hash-based selective disclosure and optional holder binding. The RFC Editor labels it an IETF Proposed Standard. [S5]

**FACT:** RFC 9420 (MLS, Proposed Standard, July 2023) is the only IETF standard for E2EE group messaging. It provides forward secrecy, post-compromise security, and scalable group key agreement via TreeKEM. [S4]

**FACT:** W3C DIDs v1.0 (Recommendation) defines URIs that resolve to key-bearing documents without a central registry. `did:web` can be hosted on static Pages at `/.well-known/did.json`. [S8]

**FACT:** CloudEvents v1.0 (CNCF) is a standardized event envelope with bindings for HTTP, Kafka, etc. [S10]

---

## 2. Scope and non-scope

### In scope
- CloudEvents v1.0 as the outer envelope for all SYM-2P events
- SD-JWT (RFC 9901) selective disclosure for credential claims
- DID-based identity (`did:web` for agents/services)
- 1:1 E2EE using libsodium sealed boxes / Noise IK (Stage 1)
- MLS adoption gated on measured need for >2-party confidential sessions (Stage 2)
- Key lifecycle (creation, rotation, revocation, recovery) with transparency-log backing
- Version negotiation via `hub_contract` field in CloudEvents extensions
- Conformance test vectors and validator updates

### Not in scope (this proposal)
- Implementation code or wire-lock changes — this is a spec-level proposal only
- Architecture lock for the provenance hub (covered by Workstream A proposal)
- Wire format changes inside the existing SYM-2P/1.0 packet grammar
- BBS+/ZK signatures (deferred — no predicate-proof use case on the table)
- ActivityPub federation (deferred — not needed for initial deployment)

---

## 3. CloudEvents outer envelope

**RECOMMENDATION:** Every SYM-2P event that needs provenance is a CloudEvents v1.0 JSON envelope:

```json
{
  "specversion": "1.0",
  "type": "com.protean.sym2p.provenance.v1",
  "source": "did:web:example.org:agent:alice",
  "id": "uuid-or-ulid",
  "time": "2026-09-20T12:00:00Z",
  "data": { ... existing SYM-2P packet ... },
  "hub_contract": "1.0",
  "datacontenttype": "application/vnd.protean.sym2p.v2+json"
}
```

SYM-2P kinds map to `com.protean.sym2p.<kind>.v1` type values. For confidential packets, the `data` representation and `datacontenttype` must be fixed together in the conformance schema. A JSON event MUST NOT label an encoded ciphertext as `application/vnd.protean.sym2p.v2+json` unless the bytes are actually that media type; the binary binding or an explicit base64 representation must be selected before implementation.

FACT [S10]: CloudEvents defines `specversion, type, source, id, time, data` and extension attributes — `hub_contract` and `datacontenttype` are extensions specific to this protocol.

### Compatibility with existing packets
The existing SYM-2P/1.0 packet (wire `v: 2`, canonical key order, act-conditional fields — the locked surface in the validator) is unchanged. It rides inside the CloudEvents `data` field. The rework adds payloads *around* the packet, never inside the envelope grammar. Existing validators continue to work on the inner packet.

### Version negotiation
Contract version is negotiated via the `hub_contract` field in CloudEvents extension attributes. CloudEvents intermediaries may ignore extension attributes, so this is a SYM-2P contract rule, not a CloudEvents guarantee: a SYM-2P-aware receiver MUST reject an unknown major version and MUST NOT route or persist the event as verified.

---

## 4. E2EE: Noise IK for 1:1, MLS gated

**RECOMMENDATION (resolves B-decision 1):** Use Noise IK for interactive 1:1 channels. Treat libsodium sealed boxes as a separate one-way envelope primitive, not as an equivalent channel protocol. Sealed boxes provide recipient confidentiality but do not authenticate the sender; sender authenticity comes from the existing packet signature or a separate signature over the ciphertext.

### Stage 1 — 1:1 and small-n confidential pipes (ship first)
- **Cryptography:** Noise IK for interactive 1:1 channels, using the DID-bound static keys and ephemeral handshake keys. Use libsodium sealed boxes only for one-way recipient-encrypted envelopes.
- **Properties:** authenticated key establishment for the intended peer, forward secrecy from the ephemeral handshake keys, and no custom ratchet. Sender authentication is supplied by the Noise handshake or an explicit packet signature; it is not a property of a sealed box.
- **No Delivery Service dependency.** Direct peer-to-peer encryption using DIDs as key discovery.
- **Ciphertext provenance:** For any E2EE message that must be provable later, the sender submits `SHA-256(ciphertext)` + DSSE signature to the hub log at send time. The plaintext never exists outside the channel; the proof exists regardless of whether any recipient ever discloses.
- FACT [S4] counterevidence: MLS is heavyweight for small deployments and introduces group epoch and Delivery Service coordination. Noise IK is the selected Stage-1 channel handshake; MLS remains gated for groups.

### Stage 2 — MLS (gated on measured need)
- **Adoption condition:** A named consumer with >=3 parties AND a confidentiality requirement.
- **Protocol:** RFC 9420 MLS, TreeKEM, forward secrecy, post-compromise security.
- **Hub integration unchanged:** CloudEvents envelope rides inside MLS `message/mls` application messages; ciphertext hash is logged at send time regardless of transport.
- **RECOMMENDATION:** Do not invent a custom ratchet under any stage.

**OPEN — Confidential-channel consumer list.** The Stage-2 MLS gate fires on measured need; the Council should name the candidate consumers now so K3 has a concrete test.

---

## 5. Selective disclosure: SD-JWT (RFC 9901)

**RECOMMENDATION (resolves B-decision 2):** SD-JWT VC (RFC 9901) as the mandatory selective disclosure mechanism.

- FACT [S5]: SD-JWT defines per-claim hashing and disclosure strings with Holder Binding.
- FACT [S7]: SD-JWT VC variant wraps W3C VC-DM 2.0 claims inside an SD-JWT.
- **Disclosure flow:** The sender includes an SD-JWT VC in the credential field of the SYM-2P packet. The recipient selectively discloses claim subsets by revealing the corresponding salt and disclosure strings. The verifier learns only the disclosed values.
- **Holder-binding:** SD-JWT provides holder binding via the `cnf` claim (public key confirmation), verifying that the presenter controls the private key corresponding to the DID.
- **BBS+/ZK deferred:** No predicate-proof use case on the table; unstandardized crypto is an audit liability. Deferred to a future extension.

---

## 6. Identity: DID/OIDC hybrid

**RECOMMENDATION (resolves B-decision 3):**

### Humans
OIDC identity (GitHub/Google) with ephemeral signing certs, Fulcio-style. FACT [S3][S9]: this is the production-proven path — no key custody for humans, natural fit with the GitHub-centric stack.

### Agents / services
`did:web` resolution follows the DID method's path mapping. For example, `did:web:example.org` resolves at `https://example.org/.well-known/did.json`, while `did:web:example.org:agent:alice` resolves at `https://example.org/agent/alice/did.json`. A GitHub Pages deployment can host either form, but the proposal must select one exact identifier shape before implementation.

### Bridge
SD-JWT VC when an agent must present a derived credential with selective disclosure.

### Key lifecycle (all events logged)

| Event | Logged action |
|---|---|
| Creation | DID Document key list registered in log at creation |
| Rotation | Pre-announced effective-from STH + grace period; old and new keys both verify during grace |
| Revocation | Signed revocation record in log + compact W3C Status List cache on Pages |
| Recovery | Pre-registered recovery set >=2 keys; quorum-signed recovery record + 72h dispute window |

**OPEN — Cold recovery key custody.** Confirm a party holds an offline recovery key; otherwise the recovery story weakens to manual ceremony.

---

## 7. Signed/ciphertext hash provenance

For any confidential message that must be provable later:

1. Sender computes `SHA-256(ciphertext)` at send time.
2. Sender signs a DSSE envelope `{ payload_hash, issuer_id, log_timestamp }`.
3. Sender submits the DSSE envelope to the hub log.
4. Later, a recipient reveals the ciphertext.
5. Any verifier recomputes `SHA-256(ciphertext)`, matches against the log entry, and checks the DSSE signature against the issuer's log-derived key state.

This makes "receipt without reading" possible: the existence proof is created at send time regardless of whether the plaintext is ever disclosed. FACT [S1][S2]: Merkle transparency provides the inclusion proof.

---

## 8. Conformance test vectors

**RECOMMENDATION:** The SYM-2P validator suite (existing `sym-protocol` tests) must pass unchanged. New test fixtures for:

1. CloudEvents-wrapped valid SYM-2P packets (all existing kinds).
2. CloudEvents-wrapped packets with unknown `hub_contract` major version -> reject (fail-closed).
3. SD-JWT selective disclosure: full disclosure, subset disclosure, withheld claims.
4. Ciphertext hash provenance: round-trip through log hash-matching.
5. Key lifecycle: rotation grace-period acceptance, revocation post-window rejection.
6. Version negotiation: known and unknown major versions.

---

## 9. Threat model (for the SYM-2P layer)

| Adversary | Capability | Countermeasure | Residual risk |
|---|---|---|---|
| Passive network observer | Intercept SYM-2P packets | E2EE (sealed-box or MLS) | Traffic analysis metadata — accepted for v1 |
| Active MITM | Interpose on key exchange | Noise IK handshake; DID-based key discovery | First-use TOFU before a DID is log-registered |
| Key thief | Use compromised long-lived key | Short rotation windows; revocation; recovery dispute window | Compromise inside grace window — accepted tradeoff |
| Recipient (over-disclosure) | Leak disclosed claims | Cannot be prevented post-disclosure; holder binding limits credential re-use | Inherent to selective disclosure model |
| Sender (repudiation) | Deny having sent message | DSSE signature + logged hash at send time | Key compromise before send |
| MLS Delivery Service (Stage 2) | Observe group membership | MLS assumes untrusted DS; ciphertext-hash logging provides receipt | Group metadata (who is in the group) — accepted |

---

## 10. Phased workstream

This workstream runs parallel to the hub's Workstream A, decoupled after P0 contract freeze.

- **P0 — Contract freeze (no code).** Lock: CloudEvents type registry, DID document shape + recovery-set rules, SD-JWT claim registry, hub_contract version scheme, invariants for E2EE ciphertext logging. Exit: schemas reviewed and owner-ratified.
- **P4 — SYM-2P Stage 1.** 1:1 sealed-box channel + ciphertext-hash logging at send + SD-JWT disclosure flow. Exit: test vectors pass; validator suite still green (wire lock unbroken).
- **P5 — Conditional extensions (each owner-gated):** MLS adoption (Stage 2); additional DID methods; predicate-proof credentials (BBS+/ZK); ActivityPub federation.

### Kill condition
- K3: No consumer for confidential channels materializes by end of P4 -> drop Stage 2 (MLS) permanently from the roadmap; Stage 1 remains.

---

## 11. Unresolved decisions (open for owner + Sparky feedback)

1. **RESOLVED — E2EE Stage 1 algorithm:** Noise IK is selected for interactive 1:1 channels. Sealed boxes remain a one-way envelope primitive and do not provide sender authentication.
2. **OPEN — SD-JWT claim registry.** The exact VC context URI and claim type namespace for SYM-2P credentials.
3. **OPEN — DID document shape for ephemeral agents.** The proposal must choose one exact `did:web` identifier mapping, or explicitly adopt `did:key` for agents without hosted documents.
4. **OPEN — Cold recovery key custody.** Who holds the offline key for agent DID recovery.
5. **OPEN — Confidential-channel consumer list.** Which consumers need >2-party E2EE.
6. **OPEN — Conformance test ownership.** Who authors and maintains the SYM-2P rework conformance suite.

---

## 12. Source attribution

All facts are sourced from primary sources (IETF RFCs, W3C Recommendations, OpenID spec, CNCF spec, official vendor docs) verified HTTP 200 on 2026-09-20. See `source-ledger.json` for full details.

---

*This proposal describes the SYM-2P rework protocol improvements. It is intentionally unmerged — owner review and Sparky team feedback required before any implementation proceeds.*