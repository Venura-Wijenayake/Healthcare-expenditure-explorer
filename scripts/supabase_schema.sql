CREATE TABLE IF NOT EXISTS dataset_registry (
    dataset_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agency TEXT NOT NULL,
    category TEXT NOT NULL,
    granularity TEXT NOT NULL,
    storage_location TEXT NOT NULL,
    parquet_path TEXT,
    year_start INTEGER,
    year_end INTEGER,
    refresh_schedule TEXT,
    last_refreshed TIMESTAMPTZ,
    row_count INTEGER,
    contributor TEXT DEFAULT 'core-team',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metric_registry (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    metric_name TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    metric_unit TEXT,
    lower_is_better BOOLEAN,
    description TEXT,
    UNIQUE(dataset_key, metric_name)
);

CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    state TEXT,
    county TEXT,
    granularity TEXT NOT NULL,
    year INTEGER,
    month INTEGER,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC,
    metric_unit TEXT,
    sex TEXT,
    race TEXT,
    age_group TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_obs_state           ON observations(state);
CREATE INDEX IF NOT EXISTS idx_obs_metric          ON observations(metric_name);
CREATE INDEX IF NOT EXISTS idx_obs_dataset         ON observations(dataset_key);
CREATE INDEX IF NOT EXISTS idx_obs_year            ON observations(year);
CREATE INDEX IF NOT EXISTS idx_obs_state_metric_year ON observations(state, metric_name, year);
CREATE INDEX IF NOT EXISTS idx_obs_granularity     ON observations(granularity);

CREATE TABLE IF NOT EXISTS contributor_submissions (
    id BIGSERIAL PRIMARY KEY,
    github_username TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    agency TEXT NOT NULL,
    description TEXT NOT NULL,
    fetch_script_url TEXT,
    estimated_rows INTEGER,
    status TEXT DEFAULT 'pending',
    reviewer TEXT,
    reviewer_notes TEXT,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);
