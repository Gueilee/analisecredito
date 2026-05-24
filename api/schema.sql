-- Vendemmia Análise de Crédito — schema Turso/libSQL
-- Executar uma vez no banco de dados do grupo "credito"

CREATE TABLE IF NOT EXISTS solicitacoes (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pendente',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT,
    data        TEXT NOT NULL  -- JSON completo da solicitação
);

CREATE INDEX IF NOT EXISTS idx_sol_status  ON solicitacoes(status);
CREATE INDEX IF NOT EXISTS idx_sol_created ON solicitacoes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sol_by      ON solicitacoes(json_extract(created_by, '$.id'));

-- Documentos anexados (conteúdo base64, persistente no Turso)
CREATE TABLE IF NOT EXISTS documents (
    id         TEXT PRIMARY KEY,
    sol_id     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    nome       TEXT NOT NULL,
    content    TEXT NOT NULL,
    mime       TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_sol ON documents(sol_id);
