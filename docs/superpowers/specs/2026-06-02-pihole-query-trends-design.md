# Pi-hole Query Trends — Design Spec

**Date:** 2026-06-02
**Status:** Approved, ready for implementation planning

## Context

The MCP server has rich Pi-hole tools for blocking management and real-time query inspection, but no way to see DNS activity over time. This spec adds `get_query_trends` — a single tool that returns 24 hours of hourly DNS volume plus automatic spike detection.

## Architecture

No new files. One new method `get_query_trends()` added to `PiholeClient` in `src/tools/pihole.py`, registered as `@mcp.tool()` in `src/server.py`. Tests appended to `tests/test_pihole.py`.

## Data Source

Pi-hole v6 endpoint: `GET /api/history`

Returns 144 data points at 10-minute intervals covering the last 24 hours:
```json
{"history": [{"timestamp": 1717200000, "total": 24, "blocked": 6}, ...]}
```

The client aggregates these into 24 hourly buckets by grouping on `timestamp // 3600 * 3600`.

## Tool

### `get_query_trends() -> dict`

No parameters. Returns 24 hourly buckets plus a summary.

**Success response:**
```python
{
    "success": True,
    "hours": [
        {
            "hour": "2026-06-02T14:00:00+00:00",  # ISO 8601, UTC, start of hour
            "total": 342,
            "blocked": 89,
            "block_pct": 26.0,
            "is_spike": False
        },
        # ... 24 entries, oldest first
    ],
    "summary": {
        "total_24h": 8234,
        "blocked_24h": 2103,
        "block_pct_24h": 25.5,
        "avg_per_hour": 343.1,
        "spike_hours": ["2026-06-02T02:00:00+00:00", "2026-06-02T03:00:00+00:00"]
    }
}
```

**Spike detection:** An hour is flagged as a spike when `total > 2 × avg_per_hour`. The `spike_hours` list contains the ISO timestamp of each flagged hour. If no hours exceed the threshold, `spike_hours` is an empty list.

`block_pct` is rounded to one decimal place. If `total == 0` for a bucket, `block_pct` is `0.0`.

**Failure response (Pi-hole unreachable or auth failure):**
```python
{"success": False, "error": "...", "suggestion": "...", "attempted": "..."}
```

## Aggregation Logic

```python
from collections import defaultdict
from datetime import datetime, timezone

buckets = defaultdict(lambda: {"total": 0, "blocked": 0})
for point in history:
    hour_ts = (point["timestamp"] // 3600) * 3600
    buckets[hour_ts]["total"] += point.get("total", 0)
    buckets[hour_ts]["blocked"] += point.get("blocked", 0)

# Sort oldest-first, compute block_pct and is_spike per bucket
```

## Error Handling

Follows existing `PiholeClient` pattern:
- Auth failure → `{"success": False, "error": "Authentication failed", ...}`
- HTTP error → `{"success": False, "error": "HTTP <status>", ...}`
- Connection error → `{"success": False, "error": str(e), ...}`
- Empty history (Pi-hole has no data yet) → `{"success": True, "hours": [], "summary": {"total_24h": 0, ...}}`

## Testing

Appended to `tests/test_pihole.py`. Mock `GET /api/history` with `respx`. Tests:

1. **Success path** — mock returns 6 data points spanning 2 hours, verify aggregation, block_pct, is_spike
2. **Spike detection** — mock returns data where one hour is >2× average, verify that hour has `is_spike: True` and appears in `spike_hours`
3. **Empty history** — mock returns `{"history": []}`, verify `success: True`, empty hours list, zeroed summary
4. **Auth failure** — mock login returns error 700, verify `success: False`

~4 new tests.

## What's Not In Scope

- Configurable time window (fixed 24h)
- Per-client trend breakdown (separate future feature)
- Trend comparison across days
- Push alerts or scheduled monitoring
