-- Vendemmia Análise de Crédito — schema Turso/libSQL
-- Executar UMA VEZ no banco de dados do grupo "credito"
-- Todos os CREATE usam IF NOT EXISTS — seguro rodar múltiplas vezes

-- ── 1. Solicitações de crédito ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS solicitacoes (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pendente',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sol_status  ON solicitacoes(status);
CREATE INDEX IF NOT EXISTS idx_sol_created ON solicitacoes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sol_by      ON solicitacoes(json_extract(created_by, '$.id'));

-- ── 2. Documentos anexados (base64, persistente) ────────────────────────────
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
CREATE INDEX IF NOT EXISTS idx_doc_sol  ON documents(sol_id);
CREATE INDEX IF NOT EXISTS idx_doc_tipo ON documents(sol_id, tipo);

-- ── 3. Análises financeiras (historico — migrado do filesystem) ──────────────
CREATE TABLE IF NOT EXISTS analises (
    id         TEXT PRIMARY KEY,
    sol_id     TEXT,
    empresa    TEXT NOT NULL DEFAULT '',
    cnpj       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pendente',
    created_by TEXT,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ana_sol     ON analises(sol_id);
CREATE INDEX IF NOT EXISTS idx_ana_cnpj    ON analises(cnpj);
CREATE INDEX IF NOT EXISTS idx_ana_status  ON analises(status);
CREATE INDEX IF NOT EXISTS idx_ana_created ON analises(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ana_by      ON analises(json_extract(created_by, '$.id'));
