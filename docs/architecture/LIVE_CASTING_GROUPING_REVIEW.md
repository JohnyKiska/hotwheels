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

### Reviewed remediation plan

The session read endpoint also returns a derived `reviewed_plan` in `reviewed_report_only` mode. It overlays only the latest decision for each proposal and classifies it as `accepted_by_reviewer`, `rejected_by_reviewer`, `needs_more_evidence`, or `pending_review`. Its summary counts these states and reports the number of decided items.

This derived plan does not rewrite the immutable snapshot or the append-only decision log. It always returns `writes_to_catalog=false`, `catalog_apply_authorized=false`, and `safe_to_apply_automatically=false`. An accepted decision means only that the reviewer agrees with the proposed candidate operation; it is not permission to execute that operation.

### API boundary

The implemented endpoints are:

- `POST /castings/grouping-review-sessions/from-catalog`: generate and persist a fresh immutable preview session.
- `GET /castings/grouping-review-sessions/{session_id}`: return the stored snapshot and current decision state.
- `POST /castings/grouping-review-sessions/{session_id}/decisions`: append a decision for one proposal.
- `GET /castings/grouping-review-sessions/{session_id}/decisions`: return the decision history.

Every decision write must verify that the session exists, is not stale, the proposal ID belongs to its stored snapshot, and the disposition is valid. Writes are limited to the review-workflow tables. The endpoint must never update Releases, Castings, identifiers, or Evidence.

### Audit and security constraints

The current local admin has no authenticated user identity. Until authentication is implemented, the reviewer field is explicitly an unverified operator-supplied label, not proof of identity. The backend must remain bound to localhost; it must not be exposed to a network.

The review tables are introduced by Alembic revision `20261105_casting_grouping_review`. The migration is code only until separately reviewed and explicitly applied to a selected database. It adds immutable-session and append-only-decision triggers in SQLite. No startup-time `create_all`, automatic migration, production initialization, or catalog data mutation is permitted.

### Apply remains a separate future capability

A later apply phase must be designed independently and must require all of the following before any catalog write:

1. a fresh, non-stale session and explicit per-operation approval;
2. a documented Evidence policy and sufficient approved evidence;
3. an authenticated/authorized reviewer identity;
4. a verified SQLite backup made with the SQLite backup API;
5. an apply operation ID, expected before-state, and transactional write plan;
6. append-only audit records, post-write verification, and a tested recovery/rollback procedure.

Until that separate phase is implemented and explicitly authorized, all review-session APIs remain catalog-read-only and no apply endpoint is exposed.



## Implementation status

The persistent workflow API and SQLAlchemy models are implemented on the feature branch. Session creation stores the complete preview payload and SHA-256 fingerprints for both the canonical snapshot and its catalog inputs. Reads and decision submissions recompute the preview fingerprints; a changed catalog input or changed preview contract makes the session stale, and stale sessions reject new decisions with HTTP 409.

Decision revisions are inserted as new rows and link to the previous decision for the same proposal. SQLite triggers prevent updates and deletes to both session snapshots and decision history. The workflow writes only to the two dedicated review tables and always returns `writes_to_catalog=false`.

The migration has not been run against any user, development, or production database. It must first be exercised against a disposable test database and reviewed independently.


### Review queue filters and interface languages

The local review queue supports filters for all proposals, pending decisions, accepted, rejected, and items needing more evidence. The interface currently offers Russian and English labels. The selected interface language and queue filter are stored in browser local storage, not in the catalog database.

Proposal action codes and decision dispositions remain stable language-neutral identifiers in API payloads and database rows (for example, `keep_existing_link_candidate` and `needs_more_evidence`). The UI translates these codes at display time. Catalog values such as product names, collector numbers, and reviewer comments are not automatically translated or modified. Additional interface languages can be added by extending the UI translation dictionary without migrating catalog data or changing stored codes.

## Admin UI review flow

The live admin preview now exposes an explicit **Start review and save snapshot** action. It creates a persistent review session from the selected product-line/year scope, then renders the session's proposal queue.

For each proposal, the operator can append one of three decisions (`accepted`, `rejected`, or `needs_more_evidence`) with a reviewer label and optional reason. A subsequent decision is appended as a new history event; it does not overwrite the previous event. Release IDs in the session are links to the existing read-only release detail drawer, where the operator can inspect Evidence and source metadata.

The UI reloads the session after each saved decision so it displays the latest server-side state. If the backend reports a stale session, decision controls are disabled; the operator must create a fresh session. The reviewer label is operator-supplied and is not an authenticated identity.

The **Apply changes** control remains disabled. This UI phase only writes to the dedicated review-session and review-decision tables; it never changes catalog entities, Release links, or Evidence.
