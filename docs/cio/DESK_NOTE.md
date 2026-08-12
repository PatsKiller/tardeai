# Desk note product (synthesis v1.1)

**Code:** [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py)  
**Artifact (host):** `data/cio/cio_desk_note_latest.md`  
**Authority:** READ_ONLY · pins live `desk@vN`

The desk note is a **portfolio-grade advisory memo** for material focus: thesis header, book snapshot, filtered situations with distinct thesis-fit, cross-position view, recommendations, learning bias, and revisit/ack. It is meant for operators and Telegram/API surfaces — not a full wealth-management report.

---

## Section schema (v1.1)

| # | Section | Content |
|---|---|---|
| 1 | Thesis header | Full summary, structured risk posture, principles |
| 2 | Portfolio snapshot | Book value, cash vs band, heat, stops_active, top weights |
| 3 | Material situations | Desk-filtered; **distinct** thesis-fit per situation; multi-domain; plan_id + pin |
| 4 | Cross-position view | Concentration cluster, cash runway, correlated sleeves, heat interpretation |
| 5 | Desk recommendations | Numbered hold/stage/escalate under current pin |
| 5b | Deeper analysis | What would change the call (cash / SCHD-class / DD names) |
| 6 | Learning log | Active operator biases (deduped) |
| 7 | Revisit + ack | Plan ids, revisit triggers, `/cio thesis`, READ_ONLY footer |

v1.1 quality fixes (live in code):

- No mid-sentence truncation (`_full_sentence`)  
- Distinct thesis-fit per situation (not one boilerplate for all)  
- API/CLI snapshot parity intent  
- Deduped learning log rows  
- Deeper analysis subsection  

Optional contrast: thin single-situation card vs full desk note (`render_situation_card_contrast`).

---

## Inputs collected

From `collect_desk_inputs()` / related helpers:

- Live pin + thesis context (`safe_current_pin`, thesis store)  
- Data Broker / snapshot: portfolio, cash, holdings, risk  
- Open material plans (S1/S5/S6/S8 class focus typical)  
- Operator learning rows  

Fail-closed behavior: missing domains degrade to `DATA_UNAVAILABLE` rather than inventing numbers. Without thesis, note still labels READ_ONLY but depth suffers.

---

## Regenerate commands

```bash
cd <repo-root>

# Render to stdout (same generator used for structured payload)
PYTHONPATH=scripts python3 scripts/lib/cio_desk_synthesis.py

# Structured payload + persist latest note
PYTHONPATH=scripts python3 -c "
from scripts.lib.cio_desk_synthesis import generate_desk_synthesis_v1
from pathlib import Path
out = generate_desk_synthesis_v1()
Path('data/cio/cio_desk_note_latest.md').write_text(out['note'] + '\n')
print(out.get('thesis_version'), out.get('as_of'), out.get('authority'))
"

# Pin check
PYTHONPATH=scripts python3 -c "
from scripts.lib.cio_theses import safe_current_pin, safe_context_block
print(safe_current_pin())
print((safe_context_block(full=True) or {}).get('stance'))
"
```

API/UI: Command Center `/v3/cio` may surface plans and desk hub when the release tree includes the route + `api_v3_cio` handlers. Deep links use path form `/v3/cio?plan=<plan_id>`; absolute URLs are deployment config (Tailscale/LAN pattern), not a public CDN story.

Telegram push of the full desk note is optional host ops — do not assume every regenerate auto-sends.

---

## Quality bar vs MS / Schwab-style reports

| Desk note v1.1 **does** | **Does not** (see ROADMAP_GAPS) |
|---|---|
| Thesis-aware multi-situation synthesis | Full IPS / policy portfolio construction |
| Book-level cash, concentration, heat | Tax-lot, estate, liability matching |
| Explicit hold/stage under defensive_observe | Order tickets or auto-rebalance |
| Learning-informed bias (e.g. defer SCHD) | Guaranteed LLM prose on every plan |
| Hermes research **counts** when domain present | Continuous MS-grade research narratives |
| Clear READ_ONLY footer | Suitability letters / compliance packages |

Treat the desk note as **operator advisory depth**, not client-facing wealth reporting.

---

## Related

- [THESIS.md](./THESIS.md)  
- [LEARNING_LOOP.md](./LEARNING_LOOP.md)  
- [ROADMAP_GAPS.md](./ROADMAP_GAPS.md)  
- Operator snapshot packet: [CIO_DESK_OPERATING_PACKET.md](./CIO_DESK_OPERATING_PACKET.md)  
