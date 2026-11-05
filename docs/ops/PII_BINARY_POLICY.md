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
2. **The only silence is a reviewed registration** in `config/pii_binary_review.json`:

   ```json
   {
     "schema": "PiiBinaryReview@v1",
     "files": {
       "docs/evidence/example/synthetic-card.png": {
         "reason": "synthetic fixture: rendered from synthetic fixtures, no account, symbol or operator page",
         "reviewed_by": "<session or person who opened the file>",
         "reviewed_at": "2026-11-05T14:00:00Z"
       }
     }
   }
   ```

   Every entry needs all three fields; the loader raises `ScanError` (fail closed) otherwise. The register must be its
   canonical rendering — `scripts/lib/ci_gates.render()` — and a test enforces that.
3. **There is no ratchet for this category.** `binary_unreadable` is deliberately not in `RATCHETED`, so it never
   appears in `config/pii_baseline.json` and `--tree --write-baseline` refuses while any unreadable file is
   unregistered. A baseline count is a permission slip; permission-by-silence is the defect.
4. **`--tree` fails the existing tree**, not only new commits. `--tree --list-binaries` prints the paths (never the
   contents) so a reviewer can triage without opening anything.

## How to clear a finding

1. Open the file and look at it — this is the review the gate cannot do for you.
2. If it carries no personal or identifying data, register it with a `reason` that says what the file is and why.
3. If it does, remove it, and treat the branch as public from the moment it was pushed: a later delete does not scrub it.
4. Never register a file to make the gate green. A capture of a live page is never committed, reviewed or not.

## Not covered here

The scanner still cannot read text inside an image (OCR) or an encrypted archive. Registration is a human statement
about the file, and it is only as good as the review behind it.
