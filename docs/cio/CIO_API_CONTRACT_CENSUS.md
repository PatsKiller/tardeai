# CIO API Contract Census

`scripts/cio_api_contract_census.py` emits `CIOApiContractCensus@v2`, a static
source census of the API calls made by the CIO, Advisory, Agents, Hermes and
Research Intelligence surfaces. It is advisory and has no execution authority.

## How it is computed

- **Consumers.** Starts at the five routed pages and follows local imports
  transitively (pages, components, hooks, lib). A literal containing
  `/api/v2/` or `/api/v3/` counts as a fetch when it is an argument of a fetch
  call (`useApi`, `fetch`, `getRows`, `post`, ...), when it is assigned to a
  variable that is passed to one, or when it is a route constant referenced
  elsewhere. Drill-context labels and prose are ignored. Each row records the
  consumer `file:line`, call, method, polling interval and whether the result
  is used.
- **Producers.** Parses the `scripts/api_v2.py` dispatch: the `ROUTES` dict,
  `base_path ==` / `in (...)`, `base_path.startswith` blocks and their
  `p == / p in / p.startswith` sub-dispatch (including the method context and
  route-prefix constants). It also parses agent-runtime `READ_ROUTES`. Each
  route maps to a producer function, and the function body (plus the first
  delegated `scripts/lib` function) is read with `ast` to find clock fields,
  `Name@vN` schemas, error envelopes and silent `except: pass`.

## Detections (computed, never hard-coded)

| Key | Meaning |
|---|---|
| `unused_fetches` | The bound result is never used. A name that appears only in a hook deps array or in string text does not count as a use. |
| `dead_calls` | No dispatch branch serves the route. A prefix block that has a sub-dispatch table 404s anything outside that table. |
| `unconsumed_routes` | A backend route in these families that no Command Center v3 file consumes. Alias spellings count as one route. |
| `duplicate_endpoint_families` / `duplicate_route_consumers` | One producer serves several consumed routes, or one route is fetched from several files. |
| `v2_v3_mixing` / `v2_v3_same_resource` | Families consumed through both API versions. |
| `polling_intervals` | `useApi` / `useJson` intervals. |
| `silent_exception_paths` | Handlers containing `except ...: pass`. |

## Result at 544078d09 + this branch (2026-10-02)

The census scanned 59 consumer files and parsed 1,187 backend routes. It found
116 endpoint rows, 92 of them in the five families. The other counts are:

- 0 dead calls;
- 0 unused fetches;
- 68 unconsumed routes;
- 5 duplicate route consumers;
- 3 families mixing v2 and v3 (Agents, CIO, Hermes);
- 59 polled endpoints;
- 17 handlers with a silent `except: pass`;
- 22 rows matched only by an unverified prefix (`/api/v3/maturity*`, Hermes
  discovery-inbox and agent-maturity delegate whole sub-paths);
- 7 handlers that could not be resolved.

**Fetches removed as proven dead.** Two `HermesHub` fetches were removed:

- `/api/v2/hermes/self-learning-overview` was fetched every 2 minutes into
  `selfLearn`. Its only use was an alias, `slData`, that nothing read.
- `/api/v2/hermes/promotion-review` was fetched every 2 minutes into `promo`.
  Its only mention was a `useMemo` deps array.

The census reported no other unused fetches.

Run:

```bash
python3 scripts/cio_api_contract_census.py --summary   # counts + findings
python3 scripts/cio_api_contract_census.py --json      # full rows
```

## Limits

This is a static parse. The runtime response shape, clocks and serving release
still need an API capture against the exact release. A clock or schema is
reported only when it appears in the handler or its first delegated lib
function. `unconsumed_routes` means no Command Center v3 consumer; Telegram,
the v2 dashboard or scripts may still call those routes.
