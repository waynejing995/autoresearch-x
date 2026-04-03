# Known Performance Issues — api-latency Test Case

These are the seeded bugs in server.py that the autoresearch-x iteration loop should discover and fix.

## BUG 1: Blocking time.sleep() in request handlers
- Location: `/api/items` (line ~63), `/api/items/{id}` (line ~92), `/api/stats` (line ~108)
- Impact: Blocks the async event loop, adds 50ms/20ms/30ms per request
- Fix: Remove sleep or replace with async sleep

## BUG 2: No data caching — reloads from disk every request
- Location: `_load_records()` called in every handler
- Impact: JSON parse of 10K records on every request
- Fix: Cache records in memory, invalidate on change

## BUG 3: O(n) linear scan for filtering
- Location: `/api/items` category filter
- Impact: Scans all 10K records per request
- Fix: Build category index on startup

## BUG 4: O(n²) string concatenation for serialization
- Location: `/api/items` response building
- Impact: String concat in loop instead of list comprehension
- Fix: Use `[json.dumps(item) for item in page_items]` then `json.dumps`

## BUG 5: Double JSON serialization
- Location: All endpoints — `json.loads(json.dumps(...))`
- Impact: Unnecessary encode/decode cycle
- Fix: Return dict directly to JSONResponse

## BUG 6: Full list scan for single item lookup
- Location: `/api/items/{item_id}`
- Impact: O(n) scan instead of O(1) dict lookup
- Fix: Build id→record dict on startup
