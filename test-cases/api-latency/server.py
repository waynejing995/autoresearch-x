import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

DATA_FILE = Path(__file__).parent / "data" / "records.json"
_records_cache = None


def _load_records():
    global _records_cache
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return []


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
    _generate_records()


@app.get("/api/items")
def get_items(
    category: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=1000),
):
    records = _load_records()

    if category:
        records = [r for r in records if r["category"] == category]

    start = (page - 1) * size
    end = start + size
    page_items = records[start:end]

    result_str = ""
    for item in page_items:
        result_str += json.dumps(item) + ","
    result_str = "[" + result_str.rstrip(",") + "]"

    parsed = json.loads(result_str)
    return JSONResponse(content={"items": parsed, "total": len(records)})


@app.get("/api/items/{item_id}")
def get_item(item_id: int):
    records = _load_records()
    for r in records:
        if r["id"] == item_id:
            return JSONResponse(content=json.loads(json.dumps(r)))

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
