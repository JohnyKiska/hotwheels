# Live Casting grouping review

The local admin page exposes a read-only preview for an explicitly selected product line and catalog year.

- Endpoint: `POST /castings/grouping-preview/from-catalog`
- Default admin scope: Mainline, 2024
- Grouping key: `product_line + catalog_year + collector_number`
- SKU remains a Release identifier; model names are descriptive only.
- Missing or contradictory collector-number evidence is sent to manual review.
- Existing Casting links are compared with proposed groups. A legacy Casting spanning multiple proposed keys is flagged as a split conflict.
- The preview performs SELECT-only reads and returns `writes_to_catalog=false`. It does not create, merge, split, or reassign catalog records.

The product line is supplied explicitly because the current Release schema does not store a canonical product-line field. Evidence with review status `rejected` is excluded. Other review states remain visible to the preview and are not treated as approved truth.

Run locally on localhost only. The wider backend includes write-capable endpoints and is not suitable for public exposure without authentication and authorization.


## Remediation report

The catalog preview also returns a `remediation_plan` in `report_only` mode. Each proposed group is classified as one of:

- `keep_existing_link_candidate`: one existing Casting is linked only to this proposed group.
- `split_candidate_manual_review`: an existing Casting spans multiple proposed groups.
- `merge_candidate_manual_review`: one proposed group currently spans multiple existing Castings.
- `new_casting_candidate`: no existing Casting link is present.
- `manual_review`: the group has unresolved identity conflicts.

Evidence review-state counts are included per release and summarized in the report. The report explicitly sets `safe_to_apply_automatically=false`; pending or otherwise unapproved evidence must not be treated as confirmed identity. No action in this report writes to the catalog.

## Persistent review workflow design

The next review phase must persist human decisions without applying any Casting or Release changes.

### Review session snapshot

A review session is created from a freshly generated catalog preview. It stores:

- a generated session ID and creation timestamp;
- the exact scope (product line and catalog year);
- the grouping contract/version and grouping key;
- the complete immutable preview/remediation payload;
- a SHA-256 fingerprint of the canonicalized snapshot;
- the catalog input fingerprint used to detect stale decisions.

The stored snapshot is immutable. A changed catalog input or a changed preview fingerprint makes the session stale; stale sessions cannot be approved for a future apply operation and must be regenerated.

### Individual decisions

Each remediation item receives a separate decision record keyed by session ID and proposal ID. A decision records the selected disposition, reviewer label, optional reason, and timestamp. Supported review dispositions are:

- `accepted`: reviewer agrees that the proposed operation is the right candidate;
- `rejected`: reviewer rejects the proposed operation;
- `needs_more_evidence`: the proposal cannot be decided with current evidence.

A decision is not an approval to mutate catalog data. In particular, accepting a split candidate does not split a Casting, and accepting a keep candidate does not confirm the identity.

Decision history is append-only. A changed decision is recorded as a new event with a reference to the prior decision rather than overwriting history.

### API boundary

The planned endpoints are:

- `POST /castings/grouping-review-sessions/from-catalog`: generate and persist a fresh immutable preview session.
- `GET /castings/grouping-review-sessions/{session_id}`: return the stored snapshot and current decision state.
- `POST /castings/grouping-review-sessions/{session_id}/decisions`: append a decision for one proposal.
- `GET /castings/grouping-review-sessions/{session_id}/decisions`: return the decision history.

Every decision write must verify that the session exists, is not stale, the proposal ID belongs to its stored snapshot, and the disposition is valid. Writes are limited to the review-workflow tables. The endpoint must never update Releases, Castings, identifiers, or Evidence.

### Audit and security constraints

The current local admin has no authenticated user identity. Until authentication is implemented, the reviewer field is explicitly an unverified operator-supplied label, not proof of identity. The backend must remain bound to localhost; it must not be exposed to a network.

The review tables require an Alembic migration. The migration is code only until separately reviewed and explicitly applied to a selected database. No startup-time `create_all`, automatic migration, production initialization, or catalog data mutation is permitted.

### Apply remains a separate future capability

A later apply phase must be designed independently and must require all of the following before any catalog write:

1. a fresh, non-stale session and explicit per-operation approval;
2. a documented Evidence policy and sufficient approved evidence;
3. an authenticated/authorized reviewer identity;
4. a verified SQLite backup made with the SQLite backup API;
5. an apply operation ID, expected before-state, and transactional write plan;
6. append-only audit records, post-write verification, and a tested recovery/rollback procedure.

Until that separate phase is implemented and explicitly authorized, all review-session APIs remain catalog-read-only and no apply endpoint is exposed.

