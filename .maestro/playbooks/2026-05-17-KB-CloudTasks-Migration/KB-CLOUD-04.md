# KB Cloud Tasks Migration — Phase 4: Performance Improvements

Two targeted optimisations to cut pipeline runtime from a potential 40+ minutes to under
20 minutes for large imports:

1. **Parallelise Gemini windows** in `extractor.py` — process 4 windows concurrently
   instead of sequentially (estimated 4x speedup on the extraction step)
2. **Batch Firestore writes** in `staging.py` — group chunk doc writes into `WriteBatch`
   objects of 50 instead of one-per-chunk sequential writes

The existing sync `extract_qa_pairs` function and all current tests must continue to work
unchanged. The new async function is an additive entry point used by the Cloud Run endpoint.

Project: `/Users/ad4m/Projects/stilla-app`

- [x] Add `extract_qa_pairs_async` to `backend/bot/kb/extractor.py`:
  - Read `backend/bot/kb/extractor.py` fully before changing anything — understand:
    - How `extract_qa_pairs(turns)` builds the list of windows
    - The internal `_extract_from_turns(window_turns)` (or equivalent) single-window function
    - The retry logic and how `ChunkDraft` objects are returned
  - Add a new **async** public function `extract_qa_pairs_async` below the existing sync one:
    ```python
    async def extract_qa_pairs_async(
        turns: list[dict],
        *,
        max_concurrent_windows: int = 4,
    ) -> list[ChunkDraft]:
        """Async wrapper that processes Gemini extraction windows concurrently.

        Uses asyncio.to_thread to run the synchronous _extract_from_turns in a
        thread pool, with a semaphore to cap concurrent Gemini API calls.
        The existing sync extract_qa_pairs is unchanged and still used by tests.
        """
        import asyncio

        # Build the same windows the sync function would use
        windows = _build_windows(turns)  # use whatever internal helper exists
        if not windows:
            return []

        sem = asyncio.Semaphore(max_concurrent_windows)

        async def process_window(window_turns):
            async with sem:
                return await asyncio.to_thread(_extract_window, window_turns)
                # replace _extract_window with whatever the actual per-window function is called

        results = await asyncio.gather(*[process_window(w) for w in windows])
        # Flatten and deduplicate across windows (same logic as the sync version)
        all_chunks = [chunk for batch in results for chunk in batch]
        return _deduplicate_chunks(all_chunks)  # use existing dedup helper if any
    ```
  - Adapt the implementation to match the actual internals of the file — do not blindly paste
    the above; the helper function names (`_build_windows`, `_extract_window`) must match
    what actually exists in the file
  - If the sync function is monolithic (no internal helpers), extract the window-building
    logic into a private `_build_windows(turns)` helper first, then use it in both the
    sync and async versions
  - The existing `extract_qa_pairs` function body must remain unchanged
  - Run `cd backend && python -m pytest tests/unit/ -x -q 2>&1 | tail -20` — all unit tests
    must pass

- [x] Add `WriteBatch` grouping to `backend/bot/kb/staging.py`:
  - Read `backend/bot/kb/staging.py` fully before changing anything — understand:
    - The `stage_chunks(chunks, import_id, client)` function signature
    - Where `db.collection("kb_chunks").document(chunk_id).set(doc_data)` calls happen
    - The dedup check sequence (exact hash → embedding cosine similarity)
    - Where `core.audit.write_event("kb_chunk_staged", ...)` is called per chunk
  - Add a `batch_size: int = 50` parameter to `stage_chunks`
  - Replace sequential `doc_ref.set(doc_data)` calls with `WriteBatch` groups:
    ```python
    batch = db.batch()
    batch_count = 0

    for chunk in chunks:
        # ... existing dedup check logic stays unchanged ...
        doc_ref = db.collection("kb_chunks").document(chunk_id)
        batch.set(doc_ref, doc_data)
        batch_count += 1
        if batch_count >= batch_size:
            batch.commit()
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()
    ```
  - The audit event `kb_chunk_staged` can be emitted after each batch commit rather than
    per-chunk — emit one event per batch with a list of chunk_ids in the payload if the
    audit schema allows it, otherwise keep per-chunk emission outside the batch (it does
    not need to be transactional with the Firestore write)
  - The function signature change (`batch_size=50`) is backward-compatible; existing call
    sites that don't pass `batch_size` continue to work
  - Run `cd backend && python -m pytest tests/unit/ -x -q 2>&1 | tail -20` — all unit tests
    must pass
  - Run `cd backend && python -m pytest tests/ -x -q 2>&1 | tail -30` — full suite must pass

- [x] Update `backend/api/internal/kb_pipeline.py` to use `extract_qa_pairs_async`:
  - Read `backend/api/internal/kb_pipeline.py` (created in Phase 3)
  - Find the Gemini extraction step (Step 5) which currently calls:
    `await asyncio.to_thread(extract_qa_pairs, turns)`
  - Replace with the direct async call:
    `chunks = await extract_qa_pairs_async(turns, max_concurrent_windows=4)`
  - Update the import line to also import `extract_qa_pairs_async`
  - Do not change anything else in the file
