# Project Manager

## Open the dashboard

Open [Project Manager](./index.html) through a local HTTP server or the project's static hosting. The dashboard loads `project-state.json` relative to this page. Do not open it through `file://`, because browsers normally block the JSON fetch in that mode.

For a quick local preview from the repository root:

```powershell
py -m http.server 8000
```

Then open `http://localhost:8000/docs/project-management/`.

## Canonical source

- `project-state.json` is the canonical project state.
- `project-state.schema.json` defines the version 1 data contract.
- GitHub on `integration/catalog-foundation` is the source of truth.
- Browser storage may keep an explicitly marked local draft, but must never silently replace the canonical state.
- Exported changes must be validated and reviewed before being committed.

## Dashboard workflow

1. Load the canonical JSON from GitHub.
2. Make changes in the dashboard. They remain in page memory until saved as a browser-local draft or exported.
3. Use **Save draft** only as a local convenience. It does not update GitHub.
4. Use **Export JSON** to download the complete state.
5. Review the exported file, validate it, and commit it to `docs/project-management/project-state.json`.
6. Reload from GitHub after the commit to confirm the canonical version.

The dashboard deliberately contains no GitHub token and does not write directly to the repository.

## Entity boundaries

- **Workstreams** group areas of work.
- **Components** describe what exists in the system (directories, files, services, databases, domain areas). Optional `completed_work` and `next_step` fields record progress and the next action without turning components into tasks.
- **Tasks** describe work to be done and carry status, priority, dependencies and acceptance criteria.
- **Decisions** record accepted or proposed project-level choices.
- **Blockers** track impediments separately from ordinary tasks.
- **Changelog** records meaningful state updates.

A component's status is not a task status. Do not calculate project completion by counting components and tasks together.

## Task statuses

`backlog`, `planned`, `in_progress`, `blocked`, `review`, `done`, `cancelled`.

## Work status

`not_assessed`, `planned`, `in_progress`, `blocked`, `review`, `done`, `needs_audit`.

## Safety rules

1. Do not put database files, credentials, tokens, or machine-specific secrets in this directory.
2. Do not store a GitHub token in the static browser application.
3. Validate imported JSON against the schema and check ID uniqueness and all cross-references.
4. Preserve the previous canonical JSON before replacing it.
5. Synchronize the external drive only after the GitHub version has been reviewed and committed.

## Current implementation boundary

The dashboard opens on a hierarchical project navigator with all component groups and their descendants, search, status filtering, expand/collapse controls, component details, linked tasks, and component progress/next-step fields. It also shows workstreams, tasks, components, decisions, blockers and changelog, and supports editing/creating tasks, components, decisions and blockers. Changes are validated against the embedded JSON Schema and cross-reference rules before being applied to page state. Blockers can be linked to existing tasks. Local drafts and JSON import/export are supported. Browser-level automated tests, GitHub write-back and external-drive synchronization remain follow-up work.


## External-drive snapshot

After the canonical Project Manager files have been reviewed and committed to `integration/catalog-foundation`, run `scripts/windows/sync-project-manager-to-external.ps1` from a clean local checkout to copy the approved portable snapshot to `HW-CATALOG-DATA/PROJECT-MANAGEMENT/`. The script copies only `index.html`, `project-state.json`, `project-state.schema.json`, and this README; it stages files, verifies SHA-256, preserves the previous destination under a timestamped name, and verifies the promoted snapshot. It requires the initialized external storage marker and a clean integration branch. Do not copy the repository wholesale, and do not touch `DATABASE`, `MEDIA`, `IMPORTS`, `EXPORTS`, `BACKUPS`, `LOGS`, `DEVICE_INFO.json`, or machine-specific settings as part of this Project Manager sync. The external copy is a portable snapshot, not the source of truth; GitHub remains canonical. See [External storage synchronization](../deployment/EXTERNAL_STORAGE_SYNC.md).
