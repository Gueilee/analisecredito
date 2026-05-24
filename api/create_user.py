#!/usr/bin/env python3
"""
Utilitário para criar/gerenciar usuários do sistema de Análise de Crédito.
Execute: python create_user.py

Os usuários são salvos em users.json (gitignored).
"""

import json
import secrets
import sys
from pathlib import Path

try:
    from passlib.context import CryptContext
except ImportError:
    print("Instale as dependências: pip install -r requirements.txt")
    sys.exit(1)

USERS_FILE = Path(__file__).parent / "users.json"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def load_users() -> list:
    if not USERS_FILE.exists():
        return []
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def save_users(users: list) -> None:
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Salvo em {USERS_FILE}")


_ROLES = [
    ("Operações",     "Cria e envia análises; vê apenas seus próprios registros"),
    ("Financeiro",    "Aprova / nega crédito; vê todos os registros (RBAC + RLS completo)"),
    ("Administrador", "Acesso total — equivalente a Financeiro + gestão de usuários"),
    ("Diretor",       "Acesso total com perfil de diretoria"),
]


def add_user():
    print("\n── Adicionar usuário ──────────────────────────────")
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
    uid    = secrets.token_urlsafe(8)

    users = load_users()
    existing = next((u for u in users if u["email"] == email), None)
    if existing:
        print(f"⚠ Usuário {email} já existe. Atualizando senha...")
        existing["hashed_password"] = hashed
        existing["name"] = name
        existing["role"] = role
    else:
        users.append({
            "id":              uid,
            "name":            name,
            "email":           email,
            "hashed_password": hashed,
            "role":            role,
            "avatar":          avatar,
        })
        print(f"\n✓ Usuário criado: {name} <{email}> [{role}]")

    save_users(users)


def list_users():
    users = load_users()
    if not users:
        print("Nenhum usuário cadastrado. Execute: python create_user.py")
        return
    print(f"\n{'ID':<12} {'Nome':<25} {'E-mail':<35} {'Papel'}")
    print("-" * 90)
    for u in users:
        print(f"{u['id']:<12} {u['name']:<25} {u['email']:<35} {u.get('role','')}")


def remove_user():
    list_users()
    email = input("\nE-mail do usuário a remover: ").strip().lower()
    users = load_users()
    before = len(users)
    users  = [u for u in users if u["email"] != email]
    if len(users) == before:
        print(f"⚠ Usuário {email} não encontrado.")
        return
    save_users(users)
    print(f"✓ Usuário {email} removido.")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║  Gerenciador de Usuários — Vendemmia     ║")
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
