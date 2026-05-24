#!/usr/bin/env python3
"""
Backup automático — Vendemmia Análise de Crédito
================================================
Uso manual:
    python backup.py              # cria um backup agora
    python backup.py --list       # lista backups existentes
    python backup.py --schedule   # agenda backup a cada 6 horas (loop contínuo)
    python backup.py --export     # exporta dados em JSON normalizado para migração SQL

Os arquivos são salvos em api/backups/ (gitignored).
Rotação automática: mantém os 30 backups mais recentes.
"""

import argparse
import json
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

BASE         = Path(__file__).parent
HISTORICO    = BASE / "historico"
DOCS         = BASE / "docs"
USERS_FILE   = BASE / "users.json"
BACKUPS_DIR  = BASE / "backups"
KEEP_BACKUPS = 30          # quantos ZIPs manter
SCHEDULE_HRS = 6           # intervalo de agendamento em horas


# ── Criação do backup ─────────────────────────────────────────────────────────

def create_backup() -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUPS_DIR / f"backup_{ts}.zip"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # Análises (JSON)
        hist_files = sorted(HISTORICO.glob("*.json")) if HISTORICO.exists() else []
        for f in hist_files:
            zf.write(f, f"historico/{f.name}")

        # Documentos (PDFs, planilhas)
        if DOCS.exists():
            for f in DOCS.rglob("*"):
                if f.is_file():
                    zf.write(f, f"docs/{f.relative_to(DOCS)}")

        # Usuários (hashes bcrypt — sem senha em texto plano)
        if USERS_FILE.exists():
            zf.write(USERS_FILE, "users.json")

        # Manifesto
        manifest = {
            "gerado_em":      datetime.now().isoformat(),
            "versao":         "2.0.0",
            "total_analises": len(hist_files),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return out


def rotate_backups() -> int:
    """Remove backups antigos, mantém os últimos KEEP_BACKUPS. Retorna qtd removida."""
    all_zips = sorted(BACKUPS_DIR.glob("backup_*.zip"))
    to_remove = all_zips[:-KEEP_BACKUPS] if len(all_zips) > KEEP_BACKUPS else []
    for f in to_remove:
        f.unlink()
    return len(to_remove)


# ── Listagem ──────────────────────────────────────────────────────────────────

def list_backups():
    if not BACKUPS_DIR.exists():
        print("Nenhum backup encontrado.")
        return
    files = sorted(BACKUPS_DIR.glob("backup_*.zip"), reverse=True)
    if not files:
        print("Nenhum backup encontrado.")
        return
    print(f"\n{'#':<4} {'Arquivo':<32} {'Tamanho':>10}  {'Data/Hora'}")
    print("─" * 72)
    for i, f in enumerate(files, 1):
        size = f.stat().st_size
        size_str = f"{size/1024:.1f} KB" if size < 1_000_000 else f"{size/1_048_576:.1f} MB"
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        print(f"{i:<4} {f.name:<32} {size_str:>10}  {ts}")
    print(f"\nTotal: {len(files)} backup(s) — rotação mantém os {KEEP_BACKUPS} mais recentes.")


# ── Exportação para migração de banco de dados ────────────────────────────────

def export_for_db() -> Path:
    """Gera um JSON normalizado pronto para INSERT em tabelas SQL."""
    analises, decisoes, documentos = [], [], []

    for f in sorted(HISTORICO.glob("*.json"), key=lambda x: x.stat().st_mtime) if HISTORICO.exists() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        ai  = d.get("analise_ia")      or {}
        rf  = d.get("receita_federal") or {}
        ts  = d.get("timestamps")      or {}
        cb  = d.get("created_by")      or {}
        dec = d.get("decisao_analista") or {}

        analises.append({
            "id":                    d.get("id"),
            "solicitacao_id":        d.get("solicitacao_id"),
            "empresa":               d.get("empresa"),
            "cnpj":                  d.get("cnpj"),
            "status":                d.get("status_solicitacao"),
            "solicitante_nome":      d.get("solicitante"),
            "solicitante_id":        cb.get("id"),
            "solicitante_email":     cb.get("email"),
            "score_ia":              ai.get("score"),
            "classificacao_ia":      ai.get("classificacao"),
            "recomendacao_ia":       ai.get("recomendacao"),
            "resumo_executivo":      ai.get("resumo_executivo"),
            "exposicao_recomendada": ai.get("exposicao_total_recomendada"),
            "modelo_ia":             d.get("modelo_ia"),
            "rf_situacao":           (rf.get("data") or {}).get("descricao_situacao_cadastral"),
            "rf_abertura":           (rf.get("data") or {}).get("data_inicio_atividade"),
            "criado_em":             ts.get("solicitacao_criada_at") or d.get("data_solicitacao"),
            "rf_consultada_em":      ts.get("rf_consultada_at"),
            "analise_ia_em":         ts.get("analise_ia_at"),
            "salvo_em":              ts.get("historico_salvo_at"),
        })

        if dec and dec.get("status"):
            decisoes.append({
                "analise_id":       d.get("id"),
                "status":           dec.get("status"),
                "limite_aprovado":  dec.get("limiteAprovado"),
                "limite_desp":      dec.get("limiteDesp"),
                "limite_imp":       dec.get("limiteImp"),
                "prazo_aprovado":   dec.get("prazoAprovado"),
                "obs_analista":     dec.get("analistaObs"),
                "parecer_tecnico":  dec.get("parecerTecnico"),
                "decisao_analista": dec.get("decisaoAnalista"),
                "decidido_em":      dec.get("decisao_at"),
            })

    if DOCS.exists():
        for sol_dir in DOCS.iterdir():
            if not sol_dir.is_dir():
                continue
            for tipo_dir in sol_dir.iterdir():
                if not tipo_dir.is_dir():
                    continue
                for arq in tipo_dir.iterdir():
                    if arq.is_file():
                        documentos.append({
                            "sol_id":        sol_dir.name,
                            "tipo":          tipo_dir.name,
                            "nome_arquivo":  arq.name,
                            "tamanho_bytes": arq.stat().st_size,
                            "path_relativo": str(arq.relative_to(DOCS)),
                        })

    export = {
        "exportado_em": datetime.now().isoformat(),
        "totais": {
            "analises":   len(analises),
            "decisoes":   len(decisoes),
            "documentos": len(documentos),
        },
        # Mapeamento sugerido para tabelas SQL:
        #   analises   → CREATE TABLE analises (id UUID PRIMARY KEY, ...)
        #   decisoes   → CREATE TABLE decisoes (analise_id UUID REFERENCES analises, ...)
        #   documentos → CREATE TABLE documentos (sol_id TEXT, tipo TEXT, nome_arquivo TEXT, ...)
        "analises":   analises,
        "decisoes":   decisoes,
        "documentos": documentos,
    }

    out = BACKUPS_DIR / f"export_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    BACKUPS_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ── Agendamento ───────────────────────────────────────────────────────────────

def run_scheduled():
    interval_sec = SCHEDULE_HRS * 3600
    print(f"Backup agendado a cada {SCHEDULE_HRS}h. Pressione Ctrl+C para parar.\n")
    while True:
        print(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] Criando backup...")
        out = create_backup()
        removed = rotate_backups()
        kb = out.stat().st_size / 1024
        print(f"  ✓ {out.name} ({kb:.1f} KB)")
        if removed:
            print(f"  ✓ {removed} backup(s) antigo(s) removido(s).")
        proxima = datetime.fromtimestamp(time.time() + interval_sec)
        print(f"  Próximo backup: {proxima.strftime('%d/%m/%Y %H:%M:%S')}\n")
        time.sleep(interval_sec)


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backup — Vendemmia Análise de Crédito")
    parser.add_argument("--list",     action="store_true", help="Lista backups existentes")
    parser.add_argument("--schedule", action="store_true", help=f"Agenda backup a cada {SCHEDULE_HRS}h")
    parser.add_argument("--export",   action="store_true", help="Exporta dados para migração SQL")
    args = parser.parse_args()

    if args.list:
        list_backups()

    elif args.schedule:
        run_scheduled()

    elif args.export:
        print("Exportando dados para migração de banco de dados...")
        out = export_for_db()
        kb  = out.stat().st_size / 1024
        print(f"✓ {out.name} ({kb:.1f} KB)")
        data = json.loads(out.read_text(encoding="utf-8"))
        t = data["totais"]
        print(f"  Análises: {t['analises']} | Decisões: {t['decisoes']} | Documentos: {t['documentos']}")

    else:
        print(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] Criando backup...")
        out     = create_backup()
        removed = rotate_backups()
        kb      = out.stat().st_size / 1024
        print(f"✓ {out.name} ({kb:.1f} KB)")
        if removed:
            print(f"✓ {removed} backup(s) antigo(s) removido(s).")


if __name__ == "__main__":
    main()
