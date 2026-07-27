# Drive Sync Runbook — Stage 11
Idempotent Drive manifest/hash workflow (proven across stages 0-11): create stage folder → upload
each artifact → re-download → SHA-256 compare → write manifest → commit manifest. Canonical root
Trade_AI_Docs_v2 (folder id 1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR); path
implementation/active-trader/<run_id>/stage-XX/. Lane: gog CLI (john@jwwhiting.com). NO secrets or
raw market-data uploaded. Unit tests use mocks; the actual sync in each stage verifies hashes live.
