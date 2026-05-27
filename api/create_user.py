#!/usr/bin/env python3
"""
Utilitário para criar/gerenciar usuários do sistema de Análise de Crédito.
Execute: python create_user.py

Os usuários são salvos diretamente na tabela `users` do banco de dados Turso.
"""

import json
import secrets
import sys
import os
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

try:
    from passlib.context import CryptContext
except ImportError:
    print("Instale as dependências: pip install -r requirements.txt")
    sys.exit(1)

# Load env variables manually from .env (in case it is run without dotenv package)
def load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def run_turso_stmt(sql: str, args: list = None) -> list:
    if not TURSO_URL or not TURSO_TOKEN:
        print("\n⚠ TURSO_URL ou TURSO_TOKEN não configurados no arquivo .env!")
        print("Certifique-se de configurar as credenciais no arquivo 'api/.env'.")
        sys.exit(1)
        
    http_url = TURSO_URL.replace("libsql://", "https://") + "/v2/pipeline"
    
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "null"} if a is None else {"type": "text", "value": str(a)} for a in args]
        
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }
    
    req = urllib.request.Request(
        http_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            
        res = res_data["results"][0]["response"]["result"]
        cols = [c["name"] for c in res["cols"]]
        rows = []
        for row in res["rows"]:
            rows.append(dict(zip(cols, [v.get("value") if v.get("type") != "null" else None for v in row])))
        return rows
    except Exception as e:
        print(f"\n⚠ Erro ao conectar ao Turso: {e}")
        print("Verifique se a tabela 'users' foi criada no banco executando o schema.sql.")
        sys.exit(1)


_ROLES = [
    ("Operações",     "Cria e envia análises; vê apenas seus próprios registros"),
    ("Financeiro",    "Aprova / nega crédito; vê todos os registros (RBAC + RLS completo)"),
    ("Administrador", "Acesso total — equivalente a Financeiro + gestão de usuários"),
    ("Diretor",       "Acesso total com perfil de diretoria"),
]


def add_user():
    print("\n── Adicionar / Atualizar usuário ────────────────────────")
    name  = input("Nome completo: ").strip()
    email = input("E-mail (@vendemmia.com.br): ").strip().lower()

    print("\nPapéis disponíveis:")
    for i, (r, desc) in enumerate(_ROLES, 1):
        print(f"  [{i}] {r:<15} — {desc}")
    role_choice = input(f"Papel [1-{len(_ROLES)}] (Enter = Operações): ").strip()
    try:
        role = _ROLES[int(role_choice) - 1][0] if role_choice else "Operações"
    except (ValueError, IndexError):
        role = role_choice or "Operações"

    avatar = (name[:2]).upper()

    import getpass
    while True:
        pw  = getpass.getpass("Senha (min. 8 caracteres): ")
        pw2 = getpass.getpass("Confirme a senha: ")
        if pw != pw2:
            print("⚠ Senhas não coincidem. Tente novamente.")
            continue
        if len(pw) < 8:
            print("⚠ Senha muito curta (mínimo 8 caracteres).")
            continue
        break

    hashed = pwd_context.hash(pw)
    uid    = "u_" + secrets.token_urlsafe(8)
    now_iso = datetime.utcnow().isoformat()

    try:
        # Check if user already exists
        existing = run_turso_stmt("SELECT id FROM users WHERE email = ?", [email])
        if existing:
            print(f"\n⚠ Usuário {email} já existe. Atualizando dados e senha no banco...")
            run_turso_stmt(
                "UPDATE users SET name = ?, hashed_password = ?, role = ?, avatar = ?, updated_at = ? WHERE email = ?",
                [name, hashed, role, avatar, now_iso, email]
            )
        else:
            run_turso_stmt(
                "INSERT INTO users (id, name, email, hashed_password, role, avatar, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [uid, name, email, hashed, role, avatar, now_iso, now_iso]
            )
            print(f"\n✓ Usuário criado com sucesso no banco: {name} <{email}> [{role}]")
    except Exception as e:
        print(f"\n⚠ Erro ao salvar usuário no banco: {e}")


def list_users():
    try:
        users = run_turso_stmt("SELECT id, name, email, role FROM users")
        if not users:
            print("\nNenhum usuário cadastrado no banco de dados.")
            return
        print(f"\n{'ID':<15} {'Nome':<25} {'E-mail':<35} {'Papel'}")
        print("-" * 90)
        for u in users:
            print(f"{u['id']:<15} {u['name']:<25} {u['email']:<35} {u.get('role','')}")
    except Exception as e:
        print(f"\n⚠ Erro ao listar usuários: {e}")


def remove_user():
    list_users()
    email = input("\nE-mail do usuário a remover: ").strip().lower()
    try:
        existing = run_turso_stmt("SELECT id FROM users WHERE email = ?", [email])
        if not existing:
            print(f"⚠ Usuário {email} não encontrado.")
            return
        run_turso_stmt("DELETE FROM users WHERE email = ?", [email])
        print(f"✓ Usuário {email} removido do banco de dados com sucesso.")
    except Exception as e:
        print(f"\n⚠ Erro ao remover usuário: {e}")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║  Gerenciador de Usuários — Banco Turso   ║")
    print("╚══════════════════════════════════════════╝")

    while True:
        print("\n[1] Adicionar / atualizar usuário")
        print("[2] Listar usuários")
        print("[3] Remover usuário")
        print("[0] Sair")
        choice = input("\nOpção: ").strip()
        if choice == "1":
            add_user()
        elif choice == "2":
            list_users()
        elif choice == "3":
            remove_user()
        elif choice == "0":
            break
        else:
            print("Opção inválida.")
