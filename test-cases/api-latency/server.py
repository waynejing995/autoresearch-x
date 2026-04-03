import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

DATA_FILE = Path(__file__).parent / "data" / "records.json"
_records_cache = None
_id_index = {}  # O(1) lookup by id
_category_index = {}  # O(1) lookup by category


def _load_records():
    global _records_cache
    if _records_cache is not None:
        return _records_cache
    if DATA_FILE.exists():
        _records_cache = json.loads(DATA_FILE.read_text())
        return _records_cache
    return []


def _build_indexes(records):
    """Build lookup indexes for O(1) access."""
    global _id_index, _category_index
    _id_index = {r["id"]: r for r in records}
    _category_index = {}
    for r in records:
        cat = r["category"]
        if cat not in _category_index:
            _category_index[cat] = []
        _category_index[cat].append(r)


def _generate_records(n=10000):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(n):
        records.append(
            {
                "id": i,
                "name": f"item_{i}",
                "value": i * 1.5,
                "category": f"cat_{i % 50}",
                "tags": [f"tag_{j}" for j in range(i % 10)],
            }
        )
    DATA_FILE.write_text(json.dumps(records))
    return records


@app.on_event("startup")
def startup():
    records = _generate_records()
    _build_indexes(records)


@app.get("/api/items")
def get_items(
    category: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=1000),
):
    if category:
        records = _category_index.get(category, [])
    else:
        records = _load_records()

    start = (page - 1) * size
    end = start + size
    page_items = records[start:end]

    return JSONResponse(content={"items": page_items, "total": len(records)})


@app.get("/api/items/{item_id}")
def get_item(item_id: int):
    r = _id_index.get(item_id)
    if r:
        return JSONResponse(content=r)
    return JSONResponse(content={"error": "not found"}, status_code=404)


@app.get("/api/stats")
def get_stats():
    records = _load_records()

    categories = {}
    for r in records:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "total_value": 0}
        categories[cat]["count"] += 1
        categories[cat]["total_value"] += r["value"]

    data_hash = hashlib.md5(json.dumps(records).encode()).hexdigest()

    return JSONResponse(
        content={
            "categories": categories,
            "total_records": len(records),
            "data_hash": data_hash,
        }
    )


@app.get("/health")
def health():
    return {"status": "ok"}
