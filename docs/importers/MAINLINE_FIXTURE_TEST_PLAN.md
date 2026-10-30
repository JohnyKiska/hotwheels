# Mainline Importer v1: synthetic fixture test plan

**Status:** planning aid; the complete importer pipeline is not implemented yet.  
**Fixture file:** `backend/tests/fixtures/mainline_importer_v1_synthetic.json`

Every record in the fixture file is invented. It must not be treated as real catalog evidence.

## Scenarios

| Case | Expected behavior | Required safety check |
| --- | --- | --- |
| `new_release_candidate` | An unmatched record appears in preview as a candidate. | No canonical write before explicit confirmation. |
| `same_record_reimport` | An identical source record is recognized on re-import. | Re-running does not create duplicate candidates or evidence. |
| `wheel_type_difference` | Different wheel observations become a possible release/variation review. | Do not overwrite a confirmed value or create a new release automatically. |
| `base_marking_difference` | Different base markings are retained as evidence and sent for review. | Preserve the confirmed value until a human decision. |
| `identifier_collision` | Same SKU with conflicting model/year context is treated as a conflict. | Do not merge records based on SKU alone; retain an audit trail. |
| `conflicting_source_evidence` | Both sources' claims appear in the preview. | Preserve both observations and do not choose a winner silently. |
| `unknown_fields` | Incomplete data can still form a candidate. | Keep missing values unknown; do not infer them from adjacent records. |

## Current implementation boundary

The backend already has reusable foundations for Source, SourceRecord, Evidence, identifier normalization/lookup/registration, and evidence conflict detection. These can support later importer stages, but the repository does not yet provide the full import-run/batch/item workflow or an end-to-end preview/confirm/apply pipeline.

Therefore, this fixture set defines expected behavior; it does **not** claim that the importer currently passes these scenarios. The next implementation step should introduce a narrow importer contract and tests around existing services, then add orchestration and persistence only after the contract is agreed.

## Suggested verification order

1. Validate the fixture JSON and required keys.
2. Unit-test normalizing each synthetic source record.
3. Test matching and identifier collision behavior against an isolated in-memory SQLite database.
4. Test evidence preservation and conflict detection for wheel/base-marking disagreements.
5. Add idempotency tests for repeated processing of the same source snapshot.
6. Add preview/apply tests proving canonical entities remain unchanged until explicit confirmation.
7. Run the full backend test suite in CI and report the actual run result.

## Out of scope

- Network fetching or scraping.
- Real catalog data or images.
- Production database writes.
- Changes to root-level `collection.json`.
- Automatic selection of a winning source claim.
