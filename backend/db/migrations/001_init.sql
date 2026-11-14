-- Live state for Crumbly (Lakebase / Postgres). Every step persists here so a crash resumes instead of restarting.

-- Human-friendly ids: INC-0042, PO-0087 (seeded history uses the numbers below these).
CREATE SEQUENCE IF NOT EXISTS incident_seq START 42;
CREATE SEQUENCE IF NOT EXISTS po_seq START 87;

-- One row per supply incident; `state` caches the latest computed artefacts (shortage, coverage, ranking) for fast UI reads.
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  ingredient TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',          -- open | needs_owner | resolved | resolved_partial
  stage TEXT NOT NULL DEFAULT 'detect',         -- detect | understand | investigate | coordinate | decide | execute | update
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  trigger_message_id TEXT,
  original_po TEXT,
  shortage_kg NUMERIC,
  deadline TIMESTAMPTZ,                         -- earliest affected bake time
  production_date DATE,
  summary TEXT,
  state JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Append-only event log: powers the timeline, replay and analytics export.
CREATE TABLE IF NOT EXISTS incident_events (
  id BIGSERIAL PRIMARY KEY,
  incident_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage TEXT NOT NULL,
  actor TEXT NOT NULL CHECK (actor IN ('production_agent','sourcing_agent','recovery_agent','execution_service','owner','system')),
  type TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS incident_events_incident ON incident_events (incident_id, id);

-- Enforce append-only: row updates and deletes are rejected (demo reset uses TRUNCATE).
CREATE OR REPLACE FUNCTION reject_event_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'incident_events is append-only'; END $$;
DROP TRIGGER IF EXISTS incident_events_append_only ON incident_events;
CREATE TRIGGER incident_events_append_only BEFORE UPDATE OR DELETE ON incident_events
  FOR EACH ROW EXECUTE FUNCTION reject_event_change();

-- Every inbound/outbound email; thread_id is the Message-ID of the first outbound message in the thread.
CREATE TABLE IF NOT EXISTS email_messages (
  message_id TEXT PRIMARY KEY,
  thread_id TEXT,
  incident_id TEXT,
  supplier TEXT,
  direction TEXT NOT NULL,                      -- inbound | outbound
  kind TEXT,                                    -- trigger | enquiry | followup | chase | po | correction | reply | other
  from_addr TEXT,
  to_addr TEXT,
  subject TEXT,
  body TEXT,
  in_reply_to TEXT,
  sent_or_received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed BOOLEAN NOT NULL DEFAULT false
);

-- One conversation per supplier per incident, with chase/drop timers.
CREATE TABLE IF NOT EXISTS supplier_threads (
  incident_id TEXT NOT NULL,
  supplier TEXT NOT NULL,
  thread_id TEXT,
  email TEXT,
  is_new BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL,                         -- contacted | quoted | incomplete | chased | dropped | excluded | ordered
  note TEXT,
  followups INT NOT NULL DEFAULT 0,
  last_contact_at TIMESTAMPTZ,
  chase_due_at TIMESTAMPTZ,
  drop_due_at TIMESTAMPTZ,
  PRIMARY KEY (incident_id, supplier)
);

-- Mirror of silver_quotes for fast UI reads. A supplier reply can hold several offers (e.g. a capacity-limited early van).
CREATE TABLE IF NOT EXISTS quotes (
  quote_id BIGSERIAL PRIMARY KEY,
  incident_id TEXT NOT NULL,
  supplier TEXT NOT NULL,
  label TEXT,                                   -- e.g. 'standard van' / 'early van'
  sku TEXT,
  packs INT,
  max_packs INT,                                -- capacity limit, if the offer is partial
  pack_size_kg NUMERIC,
  unit_price NUMERIC,
  goods_price NUMERIC,
  delivery_charge NUMERIC,
  vat_rate NUMERIC,
  total NUMERIC,
  arrival_at TIMESTAMPTZ,
  arrival_text TEXT,
  missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,       -- fields as stated by the supplier (merged across replies), before arithmetic
  source_message_id TEXT,
  parse_path TEXT,                              -- ai_query | llm_client
  parsed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded BOOLEAN NOT NULL DEFAULT false,    -- replaced by a newer reply from the same supplier
  excluded_reason TEXT                          -- set by owner feedback
);

-- Purchase orders; idempotency_key = incident_id:supplier:attempt guarantees no duplicate PO.
CREATE TABLE IF NOT EXISTS purchase_orders (
  po_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  supplier TEXT NOT NULL,
  lines JSONB NOT NULL,
  total NUMERIC NOT NULL,
  arrival_at TIMESTAMPTZ,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,                         -- sending | sent | confirmed | mismatch | accepted_adjusted | correction_requested | received
  approved_by TEXT NOT NULL DEFAULT 'auto',     -- auto | owner
  message_id TEXT,
  sent_at TIMESTAMPTZ,
  confirmation JSONB,
  match_result JSONB
);

-- The owner's hard rules (single row). Only an explicit owner action changes these.
CREATE TABLE IF NOT EXISTS rules (
  id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  spending_limit_per_incident NUMERIC NOT NULL,
  auto_order_enabled BOOLEAN NOT NULL,
  arrival_buffer_min INT NOT NULL,
  delivery_window_start TEXT NOT NULL,
  delivery_window_end TEXT NOT NULL,
  chase_after_min INT NOT NULL,
  drop_after_min INT NOT NULL,
  new_supplier_requires_approval BOOLEAN NOT NULL DEFAULT true,
  postcode_area TEXT NOT NULL DEFAULT 'SE1',
  production_start TEXT NOT NULL DEFAULT '06:00'
);

-- "Not this one" feedback from the owner.
CREATE TABLE IF NOT EXISTS owner_feedback (
  id BIGSERIAL PRIMARY KEY,
  incident_id TEXT,
  quote_id BIGINT,
  supplier TEXT,
  ingredient TEXT,
  amount NUMERIC,
  reason TEXT NOT NULL CHECK (reason IN ('too_expensive','dont_trust_supplier','later_is_fine','other')),
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Soft preferences and suggested rule changes (suggestions stay unconfirmed until the owner accepts).
CREATE TABLE IF NOT EXISTS preferences (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('owner','suggested')),
  confirmed BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Decisions waiting for the owner (approve order, mismatch, new supplier, no option, rule suggestion...).
CREATE TABLE IF NOT EXISTS pending_decisions (
  id BIGSERIAL PRIMARY KEY,
  incident_id TEXT,
  kind TEXT NOT NULL,
  title TEXT,
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  options JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',          -- open | resolved | superseded
  chosen TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- Mirror of supplier_research (Linkup) for the UI.
CREATE TABLE IF NOT EXISTS research (
  research_id BIGSERIAL PRIMARY KEY,
  incident_id TEXT NOT NULL,
  supplier TEXT NOT NULL,
  claim TEXT NOT NULL,
  value TEXT,
  status TEXT NOT NULL CHECK (status IN ('confirmed','conflicting','unverified')),
  source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Help-assistant chat history per owner.
CREATE TABLE IF NOT EXISTS assistant_messages (
  id BIGSERIAL PRIMARY KEY,
  owner_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  card JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Small key/value store for demo settings (current scenario).
CREATE TABLE IF NOT EXISTS demo_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
