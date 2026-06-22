# Trade AI v12 -- Cloud Operating Cost Model

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.


**Last updated:** 2026-06-22
**Basis:** AWS pricing (US-East-1). Azure equivalents within ~5% at this scale.

---

## Current Self-Hosted Costs (Baseline)

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Server hardware (ms01-openclaw) | $0 (amortized) | Dedicated Linux server, already owned |
| Electricity | ~$15-25 | 24/7 server + Intel Arc B50 GPU |
| Finviz Elite subscription | $39.95 | Required for screener access |
| Internet / network | $0 (shared) | Home network |
| Cloud LLM fallback (minimal) | ~$5-15 | Rare fallback to xAI/Anthropic/OpenAI |
| News API subscriptions | $0-30 | Free tiers for most; some premium |
| Topic ingestion (17 topics daily) | $0 | YouTube API free tier, Google News RSS free |
| Alpaca | $0 | Free paper trading |
| **Total self-hosted** | **~$60-110/mo** | |

### Topic Intelligence Daily Cost Breakdown

| Source | Daily Calls | Cost |
|--------|-------------|------|
| YouTube Data API v3 | ~34 searches (3,400/10,000 free quota) | Free |
| Google News RSS | ~51 fetches | Free |
| YouTube transcript API | ~50 transcripts | Free |
| Brave Search (if renewed) | ~34 queries | $0.17/day ($5/mo) |
| Local LLM curation | ~67 calls, ~17 min GPU time | ~$0.02 electricity |
| Cloud LLM fallback | Rare | ~$0.01/day |
| **Daily topic total** | | **$0.00-$0.20/day** |

---

## Cloud Migration Cost Model

### Compute

| Service | Instance/SKU | Specs | Monthly Cost |
|---------|-------------|-------|-------------|
| **Portfolio Server** | ECS Fargate (1 vCPU, 2 GB) | Always-on, ~1 task | $30-40 |
| **OpenClaw Gateway** | ECS Fargate (0.5 vCPU, 1 GB) | Always-on, ~1 task | $15-20 |
| **LLM Inference (Option A: Self-hosted GPU)** | EC2 g5.xlarge (1x A10G, 4 vCPU, 16 GB) | On-demand, ~16 hrs/day | $400-520 |
| **LLM Inference (Option B: Spot GPU)** | EC2 g5.xlarge Spot | Same, with interruption risk | $140-180 |
| **LLM Inference (Option C: 100% Cloud LLM)** | None -- route all to cloud providers | See LLM API section | $0 compute |
| **Cron / Scheduler** | EventBridge Scheduler | 130+ rules | $1-2 |
| **Lambda (pipeline scripts)** | Lambda (256 MB, ~500 invocations/day) | Pipeline stage execution | $5-10 |

**Compute subtotal:** $50-590/mo (depending on LLM inference choice)

### Database

| Service | SKU | Specs | Monthly Cost |
|---------|-----|-------|-------------|
| **RDS PostgreSQL** | db.t4g.medium | 2 vCPU, 4 GB RAM, 100 GB gp3 | $65-80 |
| **RDS storage** | gp3, 100 GB | see `database.table_count` in LIVE_SYSTEM_FACTS | $10-12 |
| **RDS backups** | 7-day automated | Included in RDS | $0 |
| **ElastiCache (optional)** | cache.t4g.micro | JSON cache replacement | $12-15 |

**Database subtotal:** $75-107/mo

### Storage

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| **S3 (React SPA)** | ~50 MB static | $0.02 |
| **S3 (backups, logs)** | ~5 GB | $0.12 |
| **S3 (data files, caches)** | ~2 GB JSON files | $0.05 |
| **CloudFront (CDN)** | ~1 GB transfer/mo | $0.10 |

**Storage subtotal:** ~$1/mo

### LLM API Costs (If Using Cloud Providers Instead of Self-Hosted GPU)

| Provider | Use Case | Est. Calls/Day | Cost/1K tokens (input/output) | Monthly Est. |
|----------|---------|---------------|-------------------------------|-------------|
| **Anthropic (Claude Haiku)** | Strategy classification | ~55 symbols/week | $0.25/$1.25 per 1M tokens | $15-30 |
| **Anthropic (Claude Sonnet)** | Proposal review (4 chunks) | ~10 proposals/day | $3/$15 per 1M tokens | $20-50 |
| **xAI (Grok)** | Agent responses | ~50 queries/day | ~$5/$15 per 1M tokens | $10-25 |
| **OpenAI (GPT-4o)** | Fallback only | ~5 queries/day | $2.50/$10 per 1M tokens | $5-10 |

**LLM API subtotal (100% cloud):** $50-115/mo

### External Data APIs

| API | Current Tier | Monthly Cost |
|-----|-------------|-------------|
| **Finviz Elite** | Subscription | $39.95 |
| **NewsAPI** | Free / Developer | $0-29 |
| **Finnhub** | Free tier | $0 |
| **Polygon** | Free / Starter | $0-29 |
| **FMP** | Free tier | $0 |
| **AlphaVantage** | Free tier | $0 |
| **FRED** | Free (government) | $0 |
| **SEC EDGAR** | Free (government) | $0 |
| **Alpaca** | Free (paper) / Paid (live) | $0 / $9-99 |
| **Google Programmable Search** (stub) | Free tier (100 queries/day) | $0-5 |

**Data API subtotal:** $40-163/mo

### Networking / Egress

| Item | Estimate | Monthly Cost |
|------|----------|-------------|
| **ALB (Application Load Balancer)** | 1 ALB, minimal traffic | $16-18 |
| **Data transfer (egress)** | ~10 GB/mo | $0.90 |
| **NAT Gateway** (if VPC private subnets) | 1 NAT GW | $32 |
| **VPC** | 1 VPC | $0 |

**Networking subtotal:** $17-51/mo

### Observability

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| **CloudWatch Logs** | ~5 GB/mo ingestion | $2.50 |
| **CloudWatch Metrics** | ~50 custom metrics | $15 |
| **CloudWatch Alarms** | ~10 alarms | $1 |
| **SNS (alerts to Telegram/email)** | ~200 notifications/day | $0.50 |

**Observability subtotal:** ~$19/mo

---

## Scenario Summary

### Option A: Self-Hosted GPU on EC2 (Maximum Control)

| Category | Low | Medium | High |
|----------|-----|--------|------|
| Compute (GPU on-demand) | $450 | $530 | $590 |
| Database | $75 | $85 | $107 |
| Storage | $1 | $1 | $1 |
| Data APIs | $40 | $80 | $163 |
| Networking | $17 | $35 | $51 |
| Observability | $15 | $19 | $25 |
| **Total** | **$598** | **$750** | **$937** |

### Option B: Spot GPU Instance (Cost Optimized)

| Category | Low | Medium | High |
|----------|-----|--------|------|
| Compute (GPU spot) | $190 | $230 | $250 |
| Database | $75 | $85 | $107 |
| Storage | $1 | $1 | $1 |
| Data APIs | $40 | $80 | $163 |
| Networking | $17 | $35 | $51 |
| Observability | $15 | $19 | $25 |
| **Total** | **$338** | **$450** | **$597** |

### Option C: 100% Cloud LLM (No GPU, Simplest)

| Category | Low | Medium | High |
|----------|-----|--------|------|
| Compute (no GPU) | $50 | $65 | $75 |
| LLM API | $50 | $80 | $115 |
| Database | $75 | $85 | $107 |
| Storage | $1 | $1 | $1 |
| Data APIs | $40 | $80 | $163 |
| Networking | $17 | $35 | $51 |
| Observability | $15 | $19 | $25 |
| **Total** | **$248** | **$365** | **$537** |

### Option D: Hybrid (Current Architecture in Cloud)

Keep existing self-hosted server, add cloud services selectively:

| Category | Low | Medium | High |
|----------|-----|--------|------|
| Self-hosted (electricity + hardware) | $25 | $30 | $40 |
| Managed DB (RDS) | $75 | $85 | $107 |
| Cloud LLM (supplemental) | $5 | $15 | $30 |
| Data APIs | $40 | $80 | $163 |
| **Total** | **$145** | **$210** | **$340** |

---

## Primary Cost Drivers

| Rank | Driver | Impact | Control |
|------|--------|--------|---------|
| 1 | **GPU compute for LLM** | $140-520/mo in cloud | Use spot instances; schedule GPU off-hours; or route to cloud APIs |
| 2 | **Managed database** | $75-107/mo | Use smallest viable instance; consider Aurora Serverless v2 for auto-scaling |
| 3 | **Data API subscriptions** | $40-163/mo | Stay on free tiers; batch API calls; cache aggressively |
| 4 | **NAT Gateway** (if used) | $32/mo fixed | Avoid if possible; use VPC endpoints instead |
| 5 | **Cloud LLM API calls** | $50-115/mo if 100% cloud | Prompt caching; batch processing; smaller models for classification |
| 6 | **ALB** | $16-18/mo fixed | Required for HTTPS; no way to avoid |

---

## Recommendations

1. **Option C (100% Cloud LLM)** is the sweet spot for this workload at **$250-365/mo**. The qwen3:14b local model can be replaced by Claude Haiku for classification (cheaper per-call than GPU instance costs) and Claude Sonnet for review tasks.

2. **Option D (Hybrid)** is the lowest cost at **$145-210/mo** -- keep the self-hosted server for compute/LLM and add only managed DB for reliability.

3. **GPU cloud instances only make sense** if you need to scale beyond the Intel Arc B50's capacity (14B parameter ceiling) or need HA/redundancy for the LLM layer.

4. **Reserve instances** (1-year commit) would reduce Option A by ~30% but lock in the spend.

---

## Cost Monitoring Setup

In cloud deployment, enable:

| Tool | Purpose |
|------|---------|
| AWS Cost Explorer | Monthly spend tracking by service |
| AWS Budgets | Alert at $300, $500, $750 thresholds |
| CloudWatch billing alarm | Real-time spend notification |
| Per-service tagging | `project:trade-ai-v12` tag on all resources |
| LLM budget tracking | Existing `.env` budget counter per provider |
