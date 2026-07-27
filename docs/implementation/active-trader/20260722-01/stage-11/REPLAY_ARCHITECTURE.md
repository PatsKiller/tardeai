# Replay Architecture — Stage 11
ReplayIndexEntry indexes by session/symbol/decision/simulation with source + data-quality +
`replay://` segment reference. Raw microstructure lives in the Stage 5 WAL/Parquet store, never
duplicated into PostgreSQL. Journal events carry the reference; the replay store (Stage 5) carries
the bytes. Indexing is deterministic and additive.
