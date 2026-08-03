"""llm_cache.py — SQLite-backed LLM prompt+response cache ("Curated Messages").

Every cached hit saves a metered DeepSeek API call. Cache keys are content-hash based
with per-tier TTLs. Only reuses when: exact prompt hash match, TTL not expired,
model version same, data freshness unchanged.

Tiers (from config/inference_layers.yaml:cache):
  - deterministic:  Same symbol + same RSI/SMA/price/analyst input — 15 min TTL
  - research:       Same news snapshot for a symbol — 1 hour TTL
  - entry_plan:     Same symbol with price/RSI within tolerance — 30 min TTL
  - cio_synthesis:  Same symbol + same data snapshot — 2 hours TTL
  - catalyst:       Same news article — 24 hours TTL

Database: data/runtime/llm_cache.sqlite (single file, no server needed).

Usage:
    from lib.llm_cache import llm_cache_get, llm_cache_put, llm_cache_invalidate_symbol

    cached = llm_cache_get("symbol:data_hash:task", "deepseek-chat")
    if cached is None:
        result = generate(prompt, ...)
        llm_cache_put("symbol:data_hash:task", "deepseek-chat", result, ttl_hours=0.25)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CACHE_DIR = _PROJECT_ROOT / "data" / "runtime"
_CACHE_DB = _CACHE_DIR / "llm_cache.sqlite"

# Tier TTL defaults (hours) — overridable via env
TTL_DEFAULTS = {
    "deterministic": float(os.environ.get("LLM_CACHE_TTL_DETERMINISTIC", "0.25")),   # 15 min
    "research":      float(os.environ.get("LLM_CACHE_TTL_RESEARCH", "1")),            # 1 hour
    "entry_plan":    float(os.environ.get("LLM_CACHE_TTL_ENTRY_PLAN", "0.5")),        # 30 min
    "cio_synthesis": float(os.environ.get("LLM_CACHE_TTL_CIO", "2")),                 # 2 hours
    "catalyst":      float(os.environ.get("LLM_CACHE_TTL_CATALYST", "24")),           # 24 hours
    "default":       float(os.environ.get("LLM_CACHE_TTL_DEFAULT", "1")),             # 1 hour
}

# Max entries per tier
MAX_ENTRIES = {
    "deterministic": int(os.environ.get("LLM_CACHE_MAX_DETERMINISTIC", "5000")),
    "research":      int(os.environ.get("LLM_CACHE_MAX_RESEARCH", "2000")),
    "entry_plan":    int(os.environ.get("LLM_CACHE_MAX_ENTRY_PLAN", "1000")),
    "cio_synthesis": int(os.environ.get("LLM_CACHE_MAX_CIO", "500")),
    "catalyst":      int(os.environ.get("LLM_CACHE_MAX_CATALYST", "10000")),
    "default":       int(os.environ.get("LLM_CACHE_MAX_DEFAULT", "1000")),
}

_CACHE_ENABLED = os.environ.get("LLM_CACHE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

_lock = threading.Lock()


def _ensure_db() -> sqlite3.Connection:
    """Ensure the cache DB and table exist. Returns a new connection."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            cache_key TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            response TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'default',
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd_est REAL DEFAULT 0.0,
            created_at REAL NOT NULL,
            metadata_json TEXT,
            PRIMARY KEY (cache_key, model)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_llm_cache_tier_created
        ON llm_cache(tier, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_llm_cache_model
        ON llm_cache(model)
    """)
    conn.commit()
    return conn


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:32]


def llm_cache_get(cache_key: str, model: str) -> str | None:
    """Look up a cached response. Returns None on miss or expired entry."""
    if not _CACHE_ENABLED:
        return None
    with _lock:
        try:
            conn = _ensure_db()
            row = conn.execute(
                "SELECT response, tier, created_at FROM llm_cache WHERE cache_key = ? AND model = ?",
                (cache_key, model),
            ).fetchone()
            conn.close()
            if row is None:
                return None
            response, tier, created_at = row
            ttl_hours = TTL_DEFAULTS.get(tier, TTL_DEFAULTS["default"])
            if time.time() - created_at > ttl_hours * 3600:
                return None  # expired
            return response
        except Exception as e:
            print(f"  [llm-cache] Lookup error: {e}")
            return None


def llm_cache_put(
    cache_key: str,
    model: str,
    response: str,
    ttl_hours: float | None = None,
    *,
    prompt: str = "",
    tier: str = "default",
    input_tokens: int = 0,
    output_tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Store a response in the cache."""
    if not _CACHE_ENABLED:
        return False
    with _lock:
        try:
            conn = _ensure_db()
            prompt_hash = _hash_prompt(prompt) if prompt else ""
            now = time.time()
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_cache
                (cache_key, model, prompt_hash, response, tier, input_tokens, output_tokens,
                 created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    model,
                    prompt_hash,
                    response,
                    tier,
                    input_tokens,
                    output_tokens,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            # Enforce per-tier max entries
            max_entries = MAX_ENTRIES.get(tier, MAX_ENTRIES["default"])
            count = conn.execute(
                "SELECT COUNT(*) FROM llm_cache WHERE tier = ?", (tier,)
            ).fetchone()[0]
            if count > max_entries:
                excess = count - max_entries
                conn.execute(
                    """
                    DELETE FROM llm_cache WHERE rowid IN (
                        SELECT rowid FROM llm_cache WHERE tier = ?
                        ORDER BY created_at ASC LIMIT ?
                    )
                    """,
                    (tier, excess),
                )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"  [llm-cache] Store error: {e}")
            return False


def llm_cache_invalidate_symbol(symbol: str) -> int:
    """Invalidate all cache entries for a given symbol. Returns count of deleted rows."""
    if not _CACHE_ENABLED:
        return 0
    with _lock:
        try:
            conn = _ensure_db()
            cursor = conn.execute(
                "DELETE FROM llm_cache WHERE cache_key LIKE ?",
                (f"%{symbol}%",),
            )
            count = cursor.rowcount
            conn.commit()
            conn.close()
            if count:
                print(f"  [llm-cache] Invalidated {count} entries for {symbol}")
            return count
        except Exception as e:
            print(f"  [llm-cache] Invalidation error: {e}")
            return 0


def llm_cache_invalidate_tier(tier: str) -> int:
    """Invalidate all entries in a given tier."""
    if not _CACHE_ENABLED:
        return 0
    with _lock:
        try:
            conn = _ensure_db()
            cursor = conn.execute("DELETE FROM llm_cache WHERE tier = ?", (tier,))
            count = cursor.rowcount
            conn.commit()
            conn.close()
            print(f"  [llm-cache] Invalidated {count} entries in tier '{tier}'")
            return count
        except Exception as e:
            print(f"  [llm-cache] Tier invalidation error: {e}")
            return 0


def llm_cache_stats() -> dict[str, Any]:
    """Return cache stats for monitoring."""
    if not _CACHE_ENABLED:
        return {"enabled": False}
    try:
        conn = _ensure_db()
        total = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
        tiers = {}
        for row in conn.execute(
            "SELECT tier, COUNT(*), MIN(created_at), MAX(created_at) FROM llm_cache GROUP BY tier"
        ):
            tiers[row[0]] = {
                "count": row[1],
                "oldest": row[2],
                "newest": row[3],
            }
        conn.close()
        return {
            "enabled": True,
            "db_path": str(_CACHE_DB),
            "total_entries": total,
            "tiers": tiers,
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}


def build_cache_key(symbol: str, data_version_hash: str, task_type: str) -> str:
    """Standard cache key builder: symbol:data_version_hash:task_type."""
    return f"{symbol}:{data_version_hash}:{task_type}"


def build_data_version_hash(**fields) -> str:
    """Build a deterministic version hash from key data fields.
    Used to detect when underlying data has changed, invalidating the cache.
    Pass keyword args like: price=142.50, rsi=55.2, catalyst_count=3
    """
    raw = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ── cached_generate wrapper ──

def cached_generate(
    cache_key: str,
    model: str,
    generate_fn,
    *generate_args,
    tier: str = "default",
    ttl_hours: float | None = None,
    prompt: str = "",
    **generate_kwargs,
) -> str:
    """Cache-aware LLM generation wrapper.

    Args:
        cache_key: Unique key for this prompt+data combination (see build_cache_key)
        model: Model identifier (e.g. 'deepseek-chat', 'deepseek-reasoner')
        generate_fn: Function that generates text when cache misses
        *generate_args: Positional args passed to generate_fn
        tier: Cache tier name (determines TTL and max entries)
        ttl_hours: Override tier TTL (default: uses tier default from TTL_DEFAULTS)
        prompt: Original prompt text (for hash tracking)
        **generate_kwargs: Keyword args passed to generate_fn

    Returns:
        Generated text (either from cache or fresh).
    """
    # Check cache
    cached = llm_cache_get(cache_key, model)
    if cached is not None:
        print(f"  [llm-cache] HIT {cache_key[:60]} ({tier})")
        return cached

    # Miss — generate
    print(f"  [llm-cache] MISS {cache_key[:60]} ({tier})")
    result = generate_fn(*generate_args, **generate_kwargs)

    # Store in cache
    if result:
        llm_cache_put(
            cache_key,
            model,
            result,
            ttl_hours=ttl_hours,
            prompt=prompt,
            tier=tier,
        )
    return result


if __name__ == "__main__":
    # Quick smoke test
    k = build_cache_key("AAPL", build_data_version_hash(price=142.50, rsi=55.2), "agent_analysis")
    print(f"Cache key: {k}")
    print(f"Data version hash: {build_data_version_hash(price=142.50, rsi=55.2)}")
    print(f"Stats: {json.dumps(llm_cache_stats(), indent=2)}")
