# Artifact read path — filtering, pagination, batch, full projection

Consumer notes for domains and UIs (e.g. `math-app/math-ui`) on the
`GET /artifacts` / `POST /artifacts/batch` performance options added in
**PR-3**. These are *additive* — the cheap summary list is unchanged, you
opt in to the richer reads where you need them. None of this crosses the
§13 boundary: it's plain structured filtering the backend (Supabase) can
index; no embeddings, no semantic search.

## The four levers

| Lever | Endpoint | Replaces |
|---|---|---|
| **Full projection** | `GET /artifacts?…&full=true` | list summaries + a `GET /artifacts/{id}` per row |
| **Domain-field filter** | `GET /artifacts?artifact_type=note_page&source_note_id=<id>` | fetch-all + group client-side |
| **Pagination** | `GET /artifacts?…&limit=&offset=` | one big `limit` |
| **Batch hydrate** | `POST /artifacts/batch {ids:[…]}` | `GET /artifacts/{id}` per ref |

The default list response stays `ArtifactListResponse` (cheap
`ArtifactSummary` rows). With `full=true` it becomes
`FullArtifactListResponse` — `{ artifacts: Artifact[], total }` where
`Artifact` is the same discriminated union as `GET /artifacts/{id}`
(blob-backed artifacts get their `storage_url` hydrated, too).

## 1. Full projection — kill the per-id N+1 (PR-3a)

A gallery that lists summaries then fetches each by id is `1 + N`
requests. With `full=true` it's one:

```ts
// BEFORE: 1 + N
const summaries = (await fetchArtifacts({ artifactType: "daily_note" })).artifacts;
const full = await Promise.all(summaries.map(s => fetchArtifact(s.artifact_id)));

// AFTER: 1
const full = (await fetchArtifacts({ artifactType: "daily_note", full: true }))
  .artifacts as DailyNoteArtifact[];
```

There's no extra DB cost server-side — the list endpoint already loaded
the full rows; `full=true` just stops discarding the domain fields.

## 2. Domain-field filter — stop scanning the corpus (PR-3b)

`note_page` artifacts link to their parent via `source_note_id`. Instead
of fetching every `note_page` (`limit 200`) and grouping client-side,
filter server-side:

```ts
// AFTER: O(page), already scoped to one note, full payload inline
const pages = (await fetchArtifacts({
  artifactType: "note_page",
  source_note_id: noteId,   // equality filter on the FK
  full: true,
})).artifacts as NotePageArtifact[];
pages.sort((a, b) => a.page_index - b.page_index);
```

**Whitelist:** you can only filter on a field declared on that
`artifact_type` (e.g. `source_note_id`, `page_index` on `note_page`). A
non-declared field returns **`400`** with a clear message — never a
silent empty result. (Field names are validated against the registry and
bound as query parameters, so the filter can't inject SQL.)

> Scale note: the Supabase filter is `payload->>'field' = %s` — a
> seq-scan until a functional/JSONB index is added on the hot keys. Fine
> at current row counts; index when a table grows.

## 3. Pagination (PR-3c)

`limit` + `offset`, stable newest-first (`created_at desc`):

```ts
const page1 = await fetchArtifacts({ artifactType: "note_page", limit: 50, offset: 0 });
const page2 = await fetchArtifacts({ artifactType: "note_page", limit: 50, offset: 50 });
```

`total` reflects the returned page length (not a corpus-wide count) — no
extra count query, so latency stays O(page).

## 4. Batch hydrate `result.artifact_refs` (PR-3d)

Turning a job result's refs into artifacts is one round-trip, not N:

```ts
// BEFORE: N
const arts = await Promise.all(result.artifact_refs.map(fetchArtifact));

// AFTER: 1
const arts = await batchGetArtifacts(result.artifact_refs); // POST /artifacts/batch {ids}
```

Fail-loud: any missing id `404`s the whole batch (same contract as the
internal `get_many`); order is preserved.

## Result-ref correctness (PR-3e) — free win

A `SUCCEEDED` job now reliably carries its `artifact_refs` (persisted on
the record at completion, not re-derived). **Drop any retry/poll loop**
you added to work around intermittently-empty refs on a freshly
completed job.

## Client plumbing checklist (math-ui)

1. **Pull the regenerated `@aiplatform/sdk`** — confirm `schema.d.ts` has
   the `POST /artifacts/batch` path, `FullArtifactListResponse`,
   `BatchArtifactRequest`, and the `full`/`offset` params on
   `GET /artifacts`.
2. Extend `ListArtifactsParams` (`lib/platform/artifacts-client.ts`) with
   `offset?`, `full?`, and arbitrary field filters; pass them through as
   query params.
3. Add a typed `fetchArtifactsFull(...)` returning the
   `FullArtifactListResponse` shape (`Artifact[]`) so callers don't cast,
   and a `batchGetArtifacts(ids)` calling `POST /artifacts/batch`.
4. Refactor the two N+1s in `app/math-notes/page.tsx` (daily-note gallery
   + `note_page` grouping) per §1 and §2.

See [SDK & types (dev loop)](sdk-and-types.md) for regenerating the typed
contract.
