-- LQ-2509: schema-only (no rows) pg_dump of production trade_ai, 2026-11-12, for the tables watch_market_facts
-- and agent_watchlist_engine.get_symbol_strategy read. Owners, privileges, comments and the FK to watch_directives dropped.

CREATE TABLE public.market_quotes (
    id bigint NOT NULL,
    symbol text NOT NULL,
    source text DEFAULT 'yfinance'::text,
    price numeric,
    prev_close numeric,
    day_change numeric,
    day_change_pct numeric,
    volume bigint,
    avg_volume bigint,
    market_cap numeric,
    pe_ratio numeric,
    forward_pe numeric,
    dividend_yield numeric,
    ex_dividend_date date,
    fifty_two_week_high numeric,
    fifty_two_week_low numeric,
    earnings_date date,
    fetched_at timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE public.market_quotes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.market_quotes_id_seq OWNED BY public.market_quotes.id;

CREATE TABLE public.ui_prefs (
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.watchlist_analysis_maturity (
    symbol text NOT NULL,
    analysis_stage text DEFAULT 'raw_data_only'::text NOT NULL,
    raw_data_ready boolean DEFAULT false NOT NULL,
    strategy_card_ready boolean DEFAULT false NOT NULL,
    maria_status text DEFAULT 'not_required'::text NOT NULL,
    steph_status text DEFAULT 'not_required'::text NOT NULL,
    risk_status text DEFAULT 'not_required'::text NOT NULL,
    tax_status text DEFAULT 'not_required'::text NOT NULL,
    full_chain_status text DEFAULT 'not_required'::text NOT NULL,
    final_synthesis_status text DEFAULT 'pending'::text NOT NULL,
    escalation_policy text,
    required_agents text[],
    completed_agents text[],
    missing_agents text[],
    last_completed_agent text,
    last_completed_at timestamp with time zone,
    needs_iteration boolean DEFAULT true NOT NULL,
    iteration_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    decision_quality_status text DEFAULT 'pending'::text,
    actionable boolean DEFAULT false,
    CONSTRAINT watchlist_analysis_maturity_analysis_stage_check CHECK ((analysis_stage = ANY (ARRAY['raw_data_only'::text, 'strategy_card_ready'::text, 'routed'::text, 'specialist_review_partial'::text, 'specialist_review_complete'::text, 'full_chain_complete'::text, 'final_synthesis_complete'::text, 'needs_iteration'::text, 'failed'::text]))),
    CONSTRAINT watchlist_analysis_maturity_final_synthesis_status_check CHECK ((final_synthesis_status = ANY (ARRAY['pending'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text, 'tail_dormant'::text]))),
    CONSTRAINT watchlist_analysis_maturity_full_chain_status_check CHECK ((full_chain_status = ANY (ARRAY['not_required'::text, 'required'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT watchlist_analysis_maturity_maria_status_check CHECK ((maria_status = ANY (ARRAY['not_required'::text, 'required'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT watchlist_analysis_maturity_risk_status_check CHECK ((risk_status = ANY (ARRAY['not_required'::text, 'required'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT watchlist_analysis_maturity_steph_status_check CHECK ((steph_status = ANY (ARRAY['not_required'::text, 'required'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT watchlist_analysis_maturity_tax_status_check CHECK ((tax_status = ANY (ARRAY['not_required'::text, 'required'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text])))
);

CREATE TABLE public.watchlist_final_synthesis (
    symbol text NOT NULL,
    recommendation text NOT NULL,
    confidence numeric,
    action text,
    reason_codes text[],
    conflicts text[],
    unresolved text[],
    next_review_date date,
    synthesis_narrative text,
    input_agents text[],
    model_used text,
    raw_response text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    decision_quality_status text DEFAULT 'pending'::text,
    conflicts_detected jsonb DEFAULT '[]'::jsonb,
    gating_reasons jsonb DEFAULT '[]'::jsonb,
    actionable boolean DEFAULT false,
    human_review_required boolean DEFAULT false,
    decision_safety text DEFAULT 'pending'::text,
    safety_reasons jsonb DEFAULT '[]'::jsonb,
    portfolio_context_used boolean DEFAULT false,
    income_context_used boolean DEFAULT false,
    target_allocation_used boolean DEFAULT false,
    safety_overrides jsonb DEFAULT '{}'::jsonb,
    superseded boolean DEFAULT false,
    superseded_by text,
    synthesis_version integer DEFAULT 1,
    grok_recommendation text,
    chatgpt_recommendation text,
    models_agree boolean,
    dual_consensus_json jsonb,
    trigger_source text,
    trigger_id text,
    budget_tier text,
    budget_decision text,
    lane_used text,
    research_expires_at timestamp with time zone,
    research_reason text,
    downstream_outcome text,
    source_table text,
    source_row_id text,
    CONSTRAINT watchlist_final_synthesis_decision_quality_status_check CHECK ((decision_quality_status = ANY (ARRAY['actionable'::text, 'partial_review'::text, 'conflicting_agents'::text, 'missing_required_agent'::text, 'data_quality_warning'::text, 'data_quality_blocked'::text, 'tiny_position_low_priority'::text, 'stale_analysis'::text, 'needs_human_review'::text, 'pending'::text]))),
    CONSTRAINT watchlist_final_synthesis_decision_safety_check CHECK ((decision_safety = ANY (ARRAY['safe'::text, 'unsafe'::text, 'blocked'::text, 'pending'::text])))
);

CREATE TABLE public.watchlist_items (
    id integer NOT NULL,
    symbol text NOT NULL,
    asset_type text,
    source text NOT NULL,
    bucket text,
    status text DEFAULT 'active'::text NOT NULL,
    score numeric,
    trend text,
    backtest_score numeric,
    backtest_data jsonb DEFAULT '{}'::jsonb,
    trade_plan jsonb DEFAULT '{}'::jsonb,
    source_payload jsonb DEFAULT '{}'::jsonb,
    first_seen_at timestamp with time zone DEFAULT now(),
    last_seen_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    holdings_llm_summary jsonb,
    holdings_llm_health text,
    holdings_llm_action text,
    holdings_llm_confidence integer,
    holdings_llm_model text,
    holdings_llm_at timestamp with time zone,
    origin_system text,
    origin_detail jsonb,
    directive_id bigint,
    in_directive_watch boolean DEFAULT false,
    source_tier text,
    last_validated_at timestamp with time zone,
    seen_count integer DEFAULT 1,
    provenance_reason text,
    rsi numeric,
    setup_advisory text,
    last_enriched_at timestamp with time zone,
    price numeric,
    change_pct numeric,
    float_m numeric,
    rvol numeric,
    watch_score_kind text,
    hermes_composite_score numeric,
    hermes_rank integer,
    hermes_score_components jsonb,
    hermes_scored_at timestamp with time zone,
    discovery_query_id bigint,
    discovery_relationship text,
    scope_tier text,
    scope_expires_at timestamp with time zone,
    last_trigger_at timestamp with time zone,
    trigger_source text,
    first_seen_price numeric,
    realized_outcome text,
    thesis_win boolean,
    options_edge_score numeric,
    options_edge_detail jsonb,
    hermes_research_score numeric,
    hermes_research_detail jsonb,
    thesis_outcome_n integer,
    options_edge_n integer,
    hermes_research_n integer,
    subject_guid uuid,
    issuer_guid uuid
);

CREATE SEQUENCE public.watchlist_items_id_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.watchlist_items_id_seq1 OWNED BY public.watchlist_items.id;

CREATE TABLE public.watchlist_research_cards (
    symbol text NOT NULL,
    card jsonb DEFAULT '{}'::jsonb NOT NULL,
    research_status text,
    latest_summary text,
    latest_recommendation text,
    needs_iteration boolean DEFAULT false,
    confidence numeric,
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE public.watchlist_strategy_cards (
    symbol text NOT NULL,
    strategy_type text,
    latest_price numeric,
    support numeric,
    resistance numeric,
    ideal_entry numeric,
    add_zone_low numeric,
    add_zone_high numeric,
    stop_loss numeric,
    target_price numeric,
    risk_reward numeric,
    time_horizon text,
    position_size_note text,
    account_fit text,
    thesis text,
    catalyst_summary text,
    technical_summary text,
    risk_summary text,
    confidence numeric,
    needs_iteration boolean DEFAULT true,
    card jsonb DEFAULT '{}'::jsonb,
    updated_at timestamp with time zone DEFAULT now()
);

CREATE VIEW public.watchlist_symbol_master AS
 SELECT wi.symbol,
    array_agg(DISTINCT wi.source ORDER BY wi.source) AS sources,
    bool_or((wi.source = 'portfolio'::text)) AS in_portfolio,
    bool_or((wi.source = 'ai_discovered'::text)) AS in_ai_discovered,
    bool_or((wi.source = 'ai_watchlist'::text)) AS in_ai_watchlist,
    bool_or((wi.source = 'personal_watchlist'::text)) AS in_personal_watchlist,
    (array_agg(wi.asset_type ORDER BY wi.asset_type) FILTER (WHERE (wi.asset_type IS NOT NULL)))[1] AS asset_type,
    max(wi.score) AS score,
    max(wi.backtest_score) AS backtest_score,
    max(wi.updated_at) AS updated_at,
    sc.strategy_type,
    sc.latest_price,
    sc.support,
    sc.resistance,
    sc.ideal_entry,
    sc.stop_loss,
    sc.target_price,
    sc.risk_reward,
    sc.account_fit,
    sc.technical_summary,
    am.analysis_stage,
    am.maria_status,
    am.steph_status,
    am.risk_status,
    am.tax_status,
    am.full_chain_status,
    am.final_synthesis_status,
    am.required_agents,
    am.completed_agents,
    am.needs_iteration AS maturity_needs_iteration,
    am.escalation_policy,
    rc.latest_recommendation,
    rc.latest_summary AS research_summary,
    rc.confidence AS research_confidence,
    fs.recommendation AS synthesis_recommendation,
    fs.confidence AS synthesis_confidence,
    fs.action AS synthesis_action
   FROM ((((public.watchlist_items wi
     LEFT JOIN public.watchlist_strategy_cards sc ON ((sc.symbol = wi.symbol)))
     LEFT JOIN public.watchlist_analysis_maturity am ON ((am.symbol = wi.symbol)))
     LEFT JOIN public.watchlist_research_cards rc ON ((rc.symbol = wi.symbol)))
     LEFT JOIN public.watchlist_final_synthesis fs ON ((fs.symbol = wi.symbol)))
  WHERE (wi.status <> 'removed'::text)
  GROUP BY wi.symbol, sc.strategy_type, sc.latest_price, sc.support, sc.resistance, sc.ideal_entry, sc.stop_loss, sc.target_price, sc.risk_reward, sc.account_fit, sc.technical_summary, am.analysis_stage, am.maria_status, am.steph_status, am.risk_status, am.tax_status, am.full_chain_status, am.final_synthesis_status, am.required_agents, am.completed_agents, am.needs_iteration, am.escalation_policy, rc.latest_recommendation, rc.latest_summary, rc.confidence, fs.recommendation, fs.confidence, fs.action;

ALTER TABLE ONLY public.market_quotes ALTER COLUMN id SET DEFAULT nextval('public.market_quotes_id_seq'::regclass);

ALTER TABLE ONLY public.watchlist_items ALTER COLUMN id SET DEFAULT nextval('public.watchlist_items_id_seq1'::regclass);

ALTER TABLE ONLY public.market_quotes
    ADD CONSTRAINT market_quotes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ui_prefs
    ADD CONSTRAINT ui_prefs_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.watchlist_analysis_maturity
    ADD CONSTRAINT watchlist_analysis_maturity_pkey PRIMARY KEY (symbol);

ALTER TABLE ONLY public.watchlist_final_synthesis
    ADD CONSTRAINT watchlist_final_synthesis_pkey PRIMARY KEY (symbol);

ALTER TABLE ONLY public.watchlist_items
    ADD CONSTRAINT watchlist_items_pkey1 PRIMARY KEY (id);

ALTER TABLE ONLY public.watchlist_research_cards
    ADD CONSTRAINT watchlist_research_cards_pkey PRIMARY KEY (symbol);

ALTER TABLE ONLY public.watchlist_strategy_cards
    ADD CONSTRAINT watchlist_strategy_cards_pkey PRIMARY KEY (symbol);

CREATE INDEX idx_market_quotes_symbol_fetched_at_desc ON public.market_quotes USING btree (symbol, fetched_at DESC);

CREATE INDEX idx_wi_bucket ON public.watchlist_items USING btree (bucket);

CREATE INDEX idx_wi_scope_tier ON public.watchlist_items USING btree (scope_tier) WHERE (status = ANY (ARRAY['active'::text, 'researched'::text]));

CREATE INDEX idx_wi_source ON public.watchlist_items USING btree (source);

CREATE INDEX idx_wi_status ON public.watchlist_items USING btree (status);

CREATE INDEX idx_wi_symbol ON public.watchlist_items USING btree (symbol);

CREATE UNIQUE INDEX idx_wi_unique ON public.watchlist_items USING btree (symbol, source, COALESCE(bucket, '__none__'::text));

CREATE INDEX idx_wi_updated ON public.watchlist_items USING btree (updated_at DESC);

CREATE INDEX watchlist_items_subject_guid_idx ON public.watchlist_items USING btree (subject_guid) WHERE (subject_guid IS NOT NULL);


