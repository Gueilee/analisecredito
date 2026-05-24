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
