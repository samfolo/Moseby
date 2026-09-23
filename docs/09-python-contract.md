---
first_committed: "2026-09-19T20:24:20+01:00"
first_commit: "82fa85e"
---

# Making a small contract reviewable

## Objective

Use room search and guest updates as a small sample before modelling everything.
Make the shapes readable in Python and generate a contract a future frontend
could use, without maintaining the same fields twice.

## Thinking at this stage

- Pydantic models own request and response shapes. FastAPI supplies routes and
  operation metadata. Generate OpenAPI from them; no Python client was needed.
- Keep resource models separate from operation payloads, with names such as
  `SearchRoomsRequestPayload`. Short field descriptions should explain intent.
- Use shared types for amounts, ranges and identifiers instead of redefining them.
- Validation at the boundary checks shape. Availability, ownership and safe writes
  still need services and transactions.

### Naming and values

- Use PascalCase for Python classes and snake_case for fields.
- Choose readable resource prefixes and uppercase ULIDs, such as `room_…`.
  The preference was readability, not a larger ID space: ULIDs and UUIDs are both
  128-bit identifiers. A prefix catches type mix-ups, not missing or unauthorised records.
- Enum values carry their type name in SCREAMING_SNAKE_CASE, such as `BED_TYPE_KING`.
  Field masks instead match field names exactly, such as `dietary_requirements`.
- Allow explicit `UNKNOWN` where it describes something we do not know, such as
  a bed type. Do not silently use it for missing fields or operational decisions.
- An amount keeps the integer minor-unit value and currency together. Currency
  is a three-letter currency code, not a country code. Prices cannot be negative;
  that does not mean every possible financial amount must be positive.
- Number and amount ranges use `min_value` and `max_value`. An amount range also
  needs a currency. Validate that a supplied minimum is not above its maximum.
- One `DateRange` uses `min_date` and `max_date`, with timezone-aware timestamps.
  Both are required; the start is included and the end excluded. We removed the
  separate window/period names for the same shape.

### Searches and updates

- Search ID filters accept 1–100 IDs. Combine alternatives within each list and
  intersect different filters. The bed-type filter deliberately requires all listed types.
- Supplying an availability range means “available throughout these dates.”
  Omitting it means no dated availability filter, not a claim that every room is free.
- A guest update must distinguish an omitted field from an explicit null.
  The mask must exactly match the supplied keys, without duplicates or unknown fields.
- Validate the guest after merging changes with saved data. A partial payload alone
  cannot prove that a chosen contact preference has a usable contact field.

### QUERY and generated OpenAPI

[OpenAPI 3.2.1](https://spec.openapis.org/oas/v3.2.1.html#path-item-object) includes QUERY.
In our local check with FastAPI 0.141.1 and Pydantic 2.13.5, FastAPI accepted QUERY
bodies but omitted them from its generated specification. We added one shared
annotation pointing to the Pydantic request schema and exported version 3.2.1.
Changing the version number alone would not have fixed the missing body.

## Questions left open at this stage

- Would a chosen TypeScript generator and deployment proxy support QUERY correctly?
- What should the bed capacities, cursor ordering and supported currencies be?
- Which permissions and stateful checks belong to each operation?

The sample handlers initially returned 501; this pass checked the contract shape.
The [next review](10-domain-contract-review.md) extended it across the domain.
Use the root [README](../README.md) for current generation and check commands.
