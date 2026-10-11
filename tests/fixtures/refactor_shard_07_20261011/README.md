Status: HISTORICAL TEST_FIXTURE
as_of: 2026-10-11
Measured at: 9f602186a958df4c2d9f36f04a0ad1809bfce808

These seven text fixtures are verbatim source snapshots from the shard's approved
base commit. They are loaded by test_refactor_shard_07_20261011.py only, with DB,
provider, packet, universe and worker boundaries replaced before invocation.
They are not alternative production entrypoints. No environment or data file
was copied. Tests compare actual old versus new CLI behavior under exact cron
arguments, including flags and defaults; the source snapshots cannot drift with
the refactored entrypoints.
