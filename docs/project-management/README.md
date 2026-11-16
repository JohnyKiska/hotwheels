# Project Manager data

## Canonical source

- `project-state.json` is the canonical project state.
- `project-state.schema.json` defines the version 1 data contract.
- GitHub on `integration/catalog-foundation` is the source of truth.
- Browser storage may keep an explicitly marked local draft, but must never silently replace the canonical state.
- Exported changes must be validated and reviewed before being committed.

## Entity boundaries

- **Workstreams** group areas of work.
- **Components** describe what exists in the system (directories, files, services, databases, domain areas).
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
