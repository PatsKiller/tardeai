# Phase 2F Global Shadow Retrieval Comparison

**Date:** 2026-05-14T19:54:35.836895
**Production model:** nomic-embed-text (table: content_embeddings, 14894 docs)
**Shadow model:** qwen3-embedding:8b (table: content_embeddings_qwen3_shadow, 14874 docs)
**Queries:** 10 | **Top-K:** 10 | **Final-K (hybrid):** 10
**Hybrid enabled:** True

## Aggregate Metrics

| Metric | Nomic | Qwen3 | Hybrid | Delta (qwen3-nomic) |
|--------|-------|-------|--------|---------------------|
| Avg Similarity | 0.6963 | 0.6234 | 0.7038 | -0.0729 |
| Avg Diversity | 2.30 | 3.10 | 2.6 | +0.80 |
| Avg Latency (ms) | 155 | 1418 | -- | +1263 |
| Avg Overlap (top-10) | 0.0000 | -- | -- | -- |
| Consensus Rate | 0.0000 | -- | -- | -- |
| Empty Rate (nomic) | 0.0000 | -- | -- | -- |
| Empty Rate (qwen3) | 0.0000 | -- | -- | -- |

### Method Winner Counts

- **Nomic wins (higher avg sim):** 7
- **Qwen3 wins:** 1
- **Tie:** 2
- **Hybrid wins (vs best single):** 2

## Verdict: **INCONCLUSIVE**

No clear winner. Differences are within noise margin. Extend testing or refine query set.

## Per-Query Details (first 15)

### Q1: What is the current portfolio allocation breakdown by sector weight?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.7410 | Qwen3 avg sim: 0.5695
- Nomic diversity: 2 | Qwen3 diversity: 3
- Nomic latency: 125ms | Qwen3 latency: 2057ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [agent_synthesis:787981497] score=0.7489 -- AGNC synthesis: ADD
  2. [agent_synthesis:1323890577] score=0.7451 -- AAT synthesis: IGNORE
  3. [agent_synthesis:1884405972] score=0.7427 -- BHP synthesis: IGNORE

**Qwen3 top-3:**
  1. [social_post:1078] score=0.6345 -- Should I ditch minium volatility?
Hi everyone,

I’m reviewing my portfolio and w
  2. [social_post:87] score=0.5758 -- Dividend portfolio, 28 m
1000 schd  
1000 qqqi  
1000 spyi  
500 jepq  
500 jepi
  3. [news:1358] score=0.5738 -- Vanguard Portfolio Management (BAH) holds 6.55% — 7.9M shares disclosed - Stock 

**Hybrid top-3:**
  1. [agent_synthesis:787981497] score=0.7489 (nomic) -- AGNC synthesis: ADD
  2. [agent_synthesis:1323890577] score=0.7451 (nomic) -- AAT synthesis: IGNORE
  3. [agent_synthesis:1884405972] score=0.7427 (nomic) -- BHP synthesis: IGNORE

### Q2: Show the largest positions by market value in the defense portfolio.

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.7320 | Qwen3 avg sim: 0.6698
- Nomic diversity: 3 | Qwen3 diversity: 2
- Nomic latency: 252ms | Qwen3 latency: 2556ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [news:3045] score=0.7493 -- ONDS Stock at $9.47 🚀 | Hidden Defense Giant in the Making?
  2. [agent_synthesis:2000140831] score=0.7441 -- AVAV synthesis: IGNORE
  3. [agent_result:185156571] score=0.7395 -- LMT risk_agent: HOLD

**Qwen3 top-3:**
  1. [news:2650] score=0.7015 -- RTX Corporation (RTX): One of the Best Large Cap Defense Stocks to Buy According
  2. [news:3930] score=0.6993 -- Northrop Grumman Corporation (NOC): Among the Best Large Cap Defense Stocks to B
  3. [news:3948] score=0.6869 -- Is General Dynamics Corporation (GD) One of the Best Large Cap Defense Stocks to

**Hybrid top-3:**
  1. [news:3045] score=0.7493 (nomic) -- ONDS Stock at $9.47 🚀 | Hidden Defense Giant in the Making?
  2. [agent_synthesis:2000140831] score=0.7441 (nomic) -- AVAV synthesis: IGNORE
  3. [agent_result:185156571] score=0.7395 (nomic) -- LMT risk_agent: HOLD

### Q3: How has the RTX position size changed over the last 90 days?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.6734 | Qwen3 avg sim: 0.6776
- Nomic diversity: 4 | Qwen3 diversity: 2
- Nomic latency: 254ms | Qwen3 latency: 3134ms
- Model source tags: {'qwen3': 7, 'nomic': 3}

**Nomic top-3:**
  1. [social_post:2138] score=0.6964 -- A few days ago, you probably already saw this kind of take—nothing really surpri
  2. [social_post:1674] score=0.6959 -- $BA built a large position over last month. Hold on to it.
  3. [youtube:262] score=0.6754 -- 🔥 Bitcoin on the Brink: Will This Week’s Charts Signal a Massive Bounce or a Bru

**Qwen3 top-3:**
  1. [news:1737] score=0.7023 -- A Look At RTX (RTX) Valuation After Recent Share Price Weakness And Backlog Grow
  2. [news:1285] score=0.7004 -- How The RTX (RTX) Investment Story Is Shifting As Analysts Reassess Risk And Ups
  3. [agent_result:1574781074] score=0.6753 -- RTX risk_agent: HOLD

**Hybrid top-3:**
  1. [news:1737] score=0.7023 (qwen3) -- A Look At RTX (RTX) Valuation After Recent Share Price Weakness And Backlog Grow
  2. [news:1285] score=0.7004 (qwen3) -- How The RTX (RTX) Investment Story Is Shifting As Analysts Reassess Risk And Ups
  3. [social_post:2138] score=0.6964 (nomic) -- A few days ago, you probably already saw this kind of take—nothing really surpri

### Q4: Which holdings currently have unrealized losses exceeding 5%?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.7230 | Qwen3 avg sim: 0.5170
- Nomic diversity: 3 | Qwen3 diversity: 5
- Nomic latency: 357ms | Qwen3 latency: 3660ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [social_post:80] score=0.7363 -- $CLX is a Buying Opportunity
The Clorox Company ($CLX), is down 10% today due to
  2. [news:147] score=0.7328 -- PennantPark: Fiscal Q1 Earnings Snapshot
  3. [social_post:1070] score=0.7323 -- Performance of Self Storage REITs
I invested $50K in a REIT called Reliant Real 

**Qwen3 top-3:**
  1. [social_post:1696] score=0.5308 -- @Iwannagofast1 currently my 50% is stuck in $MSFT and $NKE and im losing patienc
  2. [agent_synthesis:1409375234] score=0.5268 -- SP500-D synthesis: HOLD
  3. [agent_result:1134547591] score=0.5197 -- DOES risk_agent: HOLD

**Hybrid top-3:**
  1. [social_post:80] score=0.7363 (nomic) -- $CLX is a Buying Opportunity
The Clorox Company ($CLX), is down 10% today due to
  2. [news:147] score=0.7328 (nomic) -- PennantPark: Fiscal Q1 Earnings Snapshot
  3. [social_post:1070] score=0.7323 (nomic) -- Performance of Self Storage REITs
I invested $50K in a REIT called Reliant Real 

### Q5: What is the current watchlist thesis for RKLB and when was it added?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.6731 | Qwen3 avg sim: 0.6769
- Nomic diversity: 2 | Qwen3 diversity: 3
- Nomic latency: 38ms | Qwen3 latency: 757ms
- Model source tags: {'nomic': 3, 'qwen3': 7}

**Nomic top-3:**
  1. [social_post:861] score=0.7228 -- $ADVB $RMBS $VIAV $RIOT $NEE watchlist
  2. [social_post:1945] score=0.7150 -- $UPDOG.X $TOSHI.X Adding to watchlist. Trending UpDog 🙌
  3. [social_post:2004] score=0.6852 -- $UPDOG.X $JASMY.X Added to watchlist! Trending higher UpDog!

**Qwen3 top-3:**
  1. [news:1976] score=0.7037 -- Is Rocket Lab Corporation (RKLB) A Good Stock To Buy Now? - Yahoo Finance
  2. [agent_result:2013828622] score=0.6919 -- RKLB risk_agent: HOLD
  3. [agent_result:1977388259] score=0.6919 -- RKLB risk_agent: HOLD

**Hybrid top-3:**
  1. [social_post:861] score=0.7228 (nomic) -- $ADVB $RMBS $VIAV $RIOT $NEE watchlist
  2. [social_post:1945] score=0.7150 (nomic) -- $UPDOG.X $TOSHI.X Adding to watchlist. Trending UpDog 🙌
  3. [news:1976] score=0.7037 (qwen3) -- Is Rocket Lab Corporation (RKLB) A Good Stock To Buy Now? - Yahoo Finance

### Q6: Show all watchlist symbols with a defense sector classification.

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.7438 | Qwen3 avg sim: 0.6275
- Nomic diversity: 1 | Qwen3 diversity: 2
- Nomic latency: 100ms | Qwen3 latency: 404ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [news:3044] score=0.7727 -- BREAKING: Iran War Creates Massive Winners – Banks, Weapons &amp; AI Surge
  2. [news:3043] score=0.7629 -- New AI Drone Defense Stock Just Hit NYSE — AVEX 🚁 #Shorts
  3. [news:3084] score=0.7615 -- Why This Defense ETF Could Keep Rallying as the Iran Conflict Escalates - Market

**Qwen3 top-3:**
  1. [youtube:627] score=0.6422 -- My Top 10 stocks position 1 2
  2. [news:3623] score=0.6379 -- Gap & Go Day Trading Tool - Key Levels, Alerts & Setup Grading — Indicator by Da
  3. [news:3647] score=0.6346 -- Industrial Select Sector SPDR Fund(XLI) Stock Options Chain | Quotes & News - Mo

**Hybrid top-3:**
  1. [news:3044] score=0.7727 (nomic) -- BREAKING: Iran War Creates Massive Winners – Banks, Weapons &amp; AI Surge
  2. [news:3043] score=0.7629 (nomic) -- New AI Drone Defense Stock Just Hit NYSE — AVEX 🚁 #Shorts
  3. [news:3084] score=0.7615 (nomic) -- Why This Defense ETF Could Keep Rallying as the Iran Conflict Escalates - Market

### Q7: Find the most recent analyst note or catalyst for PLTR on the watchlist.

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.7277 | Qwen3 avg sim: 0.6722
- Nomic diversity: 3 | Qwen3 diversity: 3
- Nomic latency: 104ms | Qwen3 latency: 398ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [agent_result:1078841848] score=0.7383 -- MAAY maria: RESEARCH_MORE
  2. [social_post:707] score=0.7333 -- THE MAY OUTLOOK FOR US MARKETS. 
   
What are the charts signalling going into M
  3. [agent_result:1406529631] score=0.7321 -- NBTX maria: HOLD

**Qwen3 top-3:**
  1. [social_post:875] score=0.7001 -- $PLTR where’s it going next?
  2. [social_post:872] score=0.6838 -- $PLTR adding
  3. [social_post:499] score=0.6777 -- $DRS If anyone interested in defense stocks is interested, $PLTR needs to be bou

**Hybrid top-3:**
  1. [agent_result:1078841848] score=0.7383 (nomic) -- MAAY maria: RESEARCH_MORE
  2. [social_post:707] score=0.7333 (nomic) -- THE MAY OUTLOOK FOR US MARKETS. 
   
What are the charts signalling going into M
  3. [agent_result:1406529631] score=0.7321 (nomic) -- NBTX maria: HOLD

### Q8: Which watchlist entries have been pending longer than 30 days without action?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.6464 | Qwen3 avg sim: 0.5586
- Nomic diversity: 2 | Qwen3 diversity: 3
- Nomic latency: 106ms | Qwen3 latency: 399ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [social_post:861] score=0.6775 -- $ADVB $RMBS $VIAV $RIOT $NEE watchlist
  2. [social_post:1945] score=0.6591 -- $UPDOG.X $TOSHI.X Adding to watchlist. Trending UpDog 🙌
  3. [social_post:1974] score=0.6506 -- $UPDOG.X $SPITCOIN.X Added to watchlist. Has potential to go UpDog 🙌

**Qwen3 top-3:**
  1. [agent_result:152406386] score=0.5895 -- CCLD risk_agent: WAIT
  2. [agent_result:149302173] score=0.5797 -- OSS risk_agent: WAIT
  3. [agent_result:131477658] score=0.5777 -- INFU risk_agent: WAIT

**Hybrid top-3:**
  1. [social_post:861] score=0.6775 (nomic) -- $ADVB $RMBS $VIAV $RIOT $NEE watchlist
  2. [social_post:1945] score=0.6591 (nomic) -- $UPDOG.X $TOSHI.X Adding to watchlist. Trending UpDog 🙌
  3. [social_post:1974] score=0.6506 (nomic) -- $UPDOG.X $SPITCOIN.X Added to watchlist. Has potential to go UpDog 🙌

### Q9: What prior evidence exists for RTX recovery watch after stop-out?

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.6282 | Qwen3 avg sim: 0.6708
- Nomic diversity: 2 | Qwen3 diversity: 4
- Nomic latency: 108ms | Qwen3 latency: 407ms
- Model source tags: {'qwen3': 10}

**Nomic top-3:**
  1. [social_post:1844] score=0.6374 -- You don't have to make up losses from the stock that caused them
I know that's o
  2. [agent_result:279511830] score=0.6365 -- DRS risk_agent: TRIM
  3. [social_post:101] score=0.6325 -- We analyzed 151,422 dividend ex-date events across 2,344 securities going back 1

**Qwen3 top-3:**
  1. [decision_outcome:20] score=0.6948 -- RTX outcome: HOLD
  2. [decision_outcome:21] score=0.6948 -- RTX outcome: HOLD
  3. [decision_outcome:22] score=0.6948 -- RTX outcome: HOLD

**Hybrid top-3:**
  1. [decision_outcome:20] score=0.6948 (qwen3) -- RTX outcome: HOLD
  2. [decision_outcome:21] score=0.6948 (qwen3) -- RTX outcome: HOLD
  3. [decision_outcome:22] score=0.6948 (qwen3) -- RTX outcome: HOLD

### Q10: Show recovery watch candidates that have reclaimed their 50-day moving average.

- Overlap: 0.00 | Consensus items: 0
- Nomic avg sim: 0.6744 | Qwen3 avg sim: 0.5943
- Nomic diversity: 1 | Qwen3 diversity: 4
- Nomic latency: 103ms | Qwen3 latency: 402ms
- Model source tags: {'nomic': 10}

**Nomic top-3:**
  1. [agent_result:1815835655] score=0.6848 -- ADTN risk_agent: TRIM
  2. [agent_result:1148386193] score=0.6832 -- CEG steph: RESEARCH_MORE
  3. [agent_result:456464988] score=0.6829 -- ACWI risk_agent: BUY

**Qwen3 top-3:**
  1. [youtube:246] score=0.6108 -- Bitcoin Weekly Candle Close 🚨 Breakout or Bull Trap?
  2. [news:3623] score=0.6099 -- Gap & Go Day Trading Tool - Key Levels, Alerts & Setup Grading — Indicator by Da
  3. [youtube:253] score=0.6067 -- Bitcoin Weekly Candle Close LIVE 🔴🐻 Key Levels & Macro Breakdown

**Hybrid top-3:**
  1. [agent_result:1815835655] score=0.6848 (nomic) -- ADTN risk_agent: TRIM
  2. [agent_result:1148386193] score=0.6832 (nomic) -- CEG steph: RESEARCH_MORE
  3. [agent_result:456464988] score=0.6829 (nomic) -- ACWI risk_agent: BUY

---
*Generated by compare_phase2f_global_shadow_retrieval.py*