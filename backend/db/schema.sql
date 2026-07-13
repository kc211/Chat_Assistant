CREATE TABLE IF NOT EXISTS documents (
    doc_id      UUID PRIMARY KEY,
    filename    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    num_chunks  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id       UUID PRIMARY KEY,
    goal          TEXT NOT NULL,
    doc_id        UUID REFERENCES documents(doc_id),
    status        TEXT NOT NULL DEFAULT 'running',
    final_result  TEXT,
    error         TEXT,
    trace         JSONB NOT NULL DEFAULT '[]',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
