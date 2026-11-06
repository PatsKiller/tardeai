# PII gate: a file the scanner cannot read is never clean

**Status:** active with `scripts/check_no_pii.py` (FQ-154, 2026-11-05). Owner: the privacy gate, not any single lane.

## The defect this replaces

`_decode` returned `None` for any file with a NUL byte in its first 8 KiB, and both callers (`scan_tree`, `scan_range`)
treated `None` as "nothing found". Every PNG, JPEG, PDF and archive in this repository was therefore **reported clean
without being read**. Two screenshots of the live `/ops/closed-loop` page reached a public branch through that silence.

A scanner that cannot read a file and says nothing has reported it clean. That is rule 8 (`exit code 0 is not evidence
of work`) applied to a gate.

## The rule now

1. **Unreadable is a finding.** `binary_unreadable` is emitted for every file the scanner cannot decode, in `--tree`,
   `--range` and `--staged`, including a binary a change *adds* (a binary carries no text hunks, so it used to skip the
   range scan entirely).
2. **The only silence is a register** in `config/pii_binary_review.json`, and there are two, never mixed:

   ```json
   {
     "schema": "PiiBinaryReview@v2",
     "files": {
       "docs/evidence/example/synthetic-card.png": {
         "reason": "synthetic fixture: rendered from synthetic fixtures, no account, symbol or operator page",
         "reviewed_by": "<session or person who opened the file>",
         "reviewed_at": "2026-11-05T14:00:00Z",
         "sha256": "<sha256 of the exact blob that was reviewed>"
       }
     },
     "grandfathered": {
       "docs/ops/packets/…/before-412.png": {
         "reason": "grandfathered, unreviewed: present when this gate landed 2026-11-05",
         "sha256": "<sha256 of the exact blob in the gate-landing commit>"
       }
     },
     "grandfathered_count": 150,
     "grandfathered_sha256": "<sha256 of the sorted grandfathered paths joined by \\n>"
   }
   ```

   - `files` is a **review**: every entry needs reason, reviewer, date and the blob's `sha256`, or the loader raises
     `ScanError`. A record without a digest is malformed, never an exemption.
   - `grandfathered` is a **frozen enumeration** of the files already in the tree when the gate landed. It keeps `main`
     green without claiming anyone looked at them. **Nothing new may join**: a pattern wide enough to admit `hero.png`
     admits the next screenshot too, which is the defect this gate exists to stop — so it is a path list, never a glob.
   - **The enumeration is judged against a trusted ref, not against itself.** Every grandfathered path must exist in
     the tree of that ref, or the scan raises `ScanError` (fail closed): `--range` uses the range base, `--staged` uses
     `HEAD`, and `--tree` uses the **gate-landing commit** — the commit that added the register, derived from history
     so it cannot move with the change under test. A change cannot add a binary, its register entry and an updated
     count/digest in one go; an unresolvable trusted ref is an error, never an empty fence.
   - **Registration is bound to content.** Each record pins the blob's `sha256`; a different blob at a registered path
     is a `binary_review_mismatch` finding until a person reviews the new content and records its digest. The register
     is evidence about a file, not a permanent path allowlist.
   - **Removal is one-way.** Review a file or delete it, then remove it from the enumeration; its `grandfathered_count`
     and `grandfathered_sha256` move with it. A path in both registers fails the scan, and a grandfathered path that is
     no longer an unreadable tracked file is a `binary_baseline_drift` finding — the list can only shrink, one
     reviewed-or-deleted file at a time.
   - **A `--staged` scan reads the register from the index**, the same snapshot as the binary contents it judges: an
     unstaged review record cannot authorize a commit that does not contain it. Absent from the index means nothing is
     exempt (fail closed).
   - The register must be its canonical rendering — `scripts/lib/ci_gates.render()` — and a test enforces that.
3. **There is no ratchet for these categories.** `binary_unreadable`, `binary_review_mismatch` and
   `binary_baseline_drift` are deliberately not in `RATCHETED`, so they never appear in `config/pii_baseline.json` and
   `--tree --write-baseline` refuses while any unreadable file lacks a valid exemption. A baseline count is a permission
   slip; permission-by-silence is the defect.
4. **The count prints on every run**, including when it is zero:
   `binaries: N unreadable not registered, R reviewed, G grandfathered, D baseline drift, M content mismatch`. A count
   that only appears on failure cannot show growth.
5. **`--tree` fails the existing tree** on any unregistered, mismatched or drifted entry.
   `--tree --list-binaries` prints the paths (never the contents) so a reviewer can triage without opening anything.

## How to clear a finding

1. Open the file and look at it — this is the review the gate cannot do for you.
2. If it carries no personal or identifying data, move it from `grandfathered` to `files` with a `reason` that says what
   the file is and why, its `sha256`, and update `grandfathered_count` / `grandfathered_sha256` (or run the helper the
   PR describes).
3. If it does, remove it, and treat the branch as public from the moment it was pushed: a later delete does not scrub it.
4. Never register a file to make the gate green. A capture of a live page is never committed, reviewed or not.
5. A registered file's content changed? That is a new review: re-open the new blob, then update its `sha256`.

## Not covered here

The scanner still cannot read text inside an image (OCR) or an encrypted archive. Registration is a human statement
about the file, and it is only as good as the review behind it.
