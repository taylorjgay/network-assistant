# Local DNS Records — Design Spec

**Date:** 2026-06-28

## Background

Pi-hole v6 supports custom local DNS records stored in FTL config (`dns.hosts`). These map hostnames to IPs for devices on the LAN without needing a full DNS server. We discovered the need while debugging `homeserver.local` (which failed due to macOS mDNS hijacking `.local`), and added `homeserver.lan` manually. This feature exposes that functionality as MCP tools and a dashboard UI card.

**API endpoints (confirmed via debug session):**
- `GET /api/config/dns/hosts` → `{"config": {"dns": {"hosts": ["ip hostname", ...]}}}`
- `PUT /api/config/dns/hosts/{url-encoded "ip hostname"}` → 201 on success
- `DELETE /api/config/dns/hosts/{url-encoded "ip hostname"}` → 204 on success

## Backend — PiholeClient (pihole.py)

Three new methods on `PiholeClient`. All follow the existing error-handling pattern: `{"success": True, ...}` on success, `{"success": False, "error": ..., "suggestion": ..., "attempted": url}` on failure.

### `get_local_dns_records() -> dict`

- `GET /api/config/dns/hosts`
- Parses each `"ip hostname"` string into `{"ip": ..., "hostname": ...}`
- Returns `{"success": True, "records": [{"ip": "...", "hostname": "..."}]}`
- Empty list is a valid success state

### `add_local_dns_record(ip: str, hostname: str) -> dict`

- URL-encodes `f"{ip} {hostname}"` and `PUT`s to `/api/config/dns/hosts/{encoded}`
- No request body needed — the entry is fully specified in the path
- Returns `{"success": True, "ip": ip, "hostname": hostname}`
- 409 conflict → suggestion: "Record already exists"

### `remove_local_dns_record(ip: str, hostname: str) -> dict`

- URL-encodes `f"{ip} {hostname}"` and `DELETE`s `/api/config/dns/hosts/{encoded}`
- Returns `{"success": True, "ip": ip, "hostname": hostname}`
- 404 → suggestion: "Record not found — check ip and hostname match exactly"

## MCP Tools (server.py)

Three tools registered with `@mcp.tool()`, thin wrappers following the existing pattern:

```python
def get_local_dns_records() -> dict: ...
def add_local_dns_record(ip: str, hostname: str) -> dict: ...
def remove_local_dns_record(ip: str, hostname: str) -> dict: ...
```

## Dashboard API Routes (server.py)

Three `@mcp.custom_route` handlers:

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/pihole/local-dns` | list all records |
| POST | `/api/pihole/local-dns` | add record (body: `{ip, hostname}`) |
| DELETE | `/api/pihole/local-dns/{ip}/{hostname:path}` | remove record |

`{hostname:path}` allows dots in the hostname without percent-encoding issues in the route match.

## API Handlers (api.py)

Three async functions following the `asyncio.to_thread` pattern:

```python
async def pihole_local_dns(cfg) -> dict: ...
async def pihole_add_local_dns(cfg, ip, hostname) -> dict: ...
async def pihole_remove_local_dns(cfg, ip, hostname) -> dict: ...
```

## Frontend

### types.ts

```ts
export interface LocalDnsRecord {
  ip: string
  hostname: string
}

export interface LocalDnsRecords {
  success: boolean
  records: LocalDnsRecord[]
  error?: string
}
```

### api.ts

```ts
getLocalDns: () => get<LocalDnsRecords>('/pihole/local-dns'),
addLocalDns: (ip: string, hostname: string) =>
  post<{ success: boolean; error?: string }>('/pihole/local-dns', { ip, hostname }),
removeLocalDns: (ip: string, hostname: string) =>
  del<{ success: boolean; error?: string }>(
    `/pihole/local-dns/${encodeURIComponent(ip)}/${encodeURIComponent(hostname)}`
  ),
```

### DnsPage.tsx

New `AddLocalDnsDialog` component (two inputs: Hostname + IP, Enter submits) and a "Local DNS Records" card appended after the Domain Lists card. The card contains:

- Header: "Local DNS Records" + refresh button + "Add Record" dialog trigger
- Table columns: Hostname | IP | (remove button)
- Rows sorted alphabetically by hostname
- Empty state: "No local DNS records"
- Remove button: red ✕, calls `api.removeLocalDns`, invalidates query, shows toast

## Tests (test_pihole.py)

7 new tests:

1. `test_get_local_dns_records_success` — parses `["1.2.3.4 foo.lan"]` into records list
2. `test_get_local_dns_records_empty` — empty hosts array → `{"success": True, "records": []}`
3. `test_get_local_dns_records_auth_failure` — returns `success: False`
4. `test_add_local_dns_record_success` — 201 response → `{"success": True, "ip": ..., "hostname": ...}`
5. `test_add_local_dns_record_conflict` — 409 response → `success: False`, suggestion mentions "already exists"
6. `test_remove_local_dns_record_success` — 204 response → `{"success": True}`
7. `test_remove_local_dns_record_not_found` — 404 response → `success: False`, suggestion mentions "not found"

## Out of Scope

- Input validation of IP format (Pi-hole rejects invalid IPs with a clear error)
- CNAME records (Pi-hole v6 supports them at `/api/config/dns/cnameRecords` — separate feature)
- Bulk import
