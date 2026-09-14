-- Schéma de la base "fraud" (data warehouse des transactions temps réel)

CREATE TABLE IF NOT EXISTS transactions (
    trans_num       TEXT PRIMARY KEY,                    -- clé de déduplication (l'API peut renvoyer la même tx plusieurs fois)
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    trans_time      TIMESTAMPTZ NOT NULL,                -- issu de current_time (epoch ms) renvoyé par l'API
    cc_num          BIGINT,
    merchant        TEXT,
    category        TEXT,
    amt             NUMERIC(12, 2),
    first_name      TEXT,
    last_name       TEXT,
    gender          CHAR(1),
    street          TEXT,
    city            TEXT,
    state           TEXT,
    zip             INTEGER,
    lat             DOUBLE PRECISION,
    long            DOUBLE PRECISION,
    city_pop        INTEGER,
    job             TEXT,
    dob             DATE,
    merch_lat       DOUBLE PRECISION,
    merch_long      DOUBLE PRECISION,
    is_fraud_truth  SMALLINT,                            -- label fourni par l'API, jamais utilisé pour prédire (monitoring)
    fraud_proba     DOUBLE PRECISION,
    is_fraud_pred   SMALLINT,
    model_version   TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_trans_time ON transactions (trans_time);
CREATE INDEX IF NOT EXISTS idx_transactions_is_fraud_pred ON transactions (is_fraud_pred) WHERE is_fraud_pred = 1;

CREATE TABLE IF NOT EXISTS fraud_alerts (
    id          SERIAL PRIMARY KEY,
    trans_num   TEXT NOT NULL REFERENCES transactions (trans_num),
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel     TEXT NOT NULL,                           -- discord | email
    status      TEXT NOT NULL,                           -- sent | failed
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS daily_reports (
    report_date     DATE PRIMARY KEY,
    nb_transactions INTEGER NOT NULL,
    nb_frauds       INTEGER NOT NULL,
    total_amount    NUMERIC(14, 2) NOT NULL,
    fraud_amount    NUMERIC(14, 2) NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB                                -- détail (top catégories, états, précision live, ...)
);
