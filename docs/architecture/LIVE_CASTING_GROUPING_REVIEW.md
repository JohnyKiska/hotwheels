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
