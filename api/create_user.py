#!/usr/bin/env python3
"""
Utilitário para criar/gerenciar usuários do sistema de Análise de Crédito.
Execute: python create_user.py

Os usuários são salvos diretamente na tabela `users` do banco de dados Turso.
"""

import json
import secrets
import smtplib
import sys
import os
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timedelta

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
TURSO_URL   = os.getenv("TURSO_URL",   "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")

# SMTP (lido do .env para envio de e-mail de boas-vindas)
_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_FROM_EMAIL = os.getenv("SMTP_USER", "noreply@vendemmia.com.br")
_BASE_URL   = os.getenv("ALLOWED_ORIGINS", "https://analisecredito.vendemmia.dev.br").split(",")[0].strip()

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


def _welcome_email_html(name: str, url: str) -> str:
    logo_url = f"{_BASE_URL}/logo.png"
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:40px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.10);">

      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 100%);padding:32px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td>
            <img src="{logo_url}" alt="Vendemmia" height="48"
                 style="height:48px;max-width:200px;object-fit:contain;display:block;" />
          </td>
          <td align="right" style="color:rgba(255,255,255,.5);font-size:11px;letter-spacing:.5px;text-transform:uppercase;vertical-align:bottom;">
            Análise de Crédito
          </td>
        </tr></table>
      </td></tr>

      <!-- Banner verde-boas-vindas -->
      <tr><td style="background:linear-gradient(90deg,#4f46e5,#7c3aed);padding:20px 40px;">
        <p style="margin:0;color:#fff;font-size:20px;font-weight:700;letter-spacing:.3px;">
          Bem-vindo ao sistema! 🎉
        </p>
        <p style="margin:6px 0 0;color:rgba(255,255,255,.75);font-size:13px;">
          Sua conta foi criada. Defina sua senha para começar.
        </p>
      </td></tr>

      <!-- Corpo -->
      <tr><td style="padding:36px 40px 28px;">
        <p style="margin:0 0 16px;font-size:16px;color:#1e1b4b;font-weight:700;">
          Olá, {name}!
        </p>
        <p style="margin:0 0 12px;font-size:14px;color:#555;line-height:1.7;">
          Você foi cadastrado no <strong>Sistema de Análise de Crédito da Vendemmia</strong>.
          Para ativar seu acesso, clique no botão abaixo e escolha uma senha segura.
        </p>
        <p style="margin:0 0 28px;font-size:13px;color:#888;line-height:1.6;">
          O link é <strong>válido por 24 horas</strong>. Após esse prazo, solicite um novo
          acesso ao administrador do sistema.
        </p>

        <!-- Botão -->
        <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
          <tr><td style="border-radius:12px;background:linear-gradient(135deg,#4f46e5,#7c3aed);box-shadow:0 4px 14px rgba(79,70,229,.4);">
            <a href="{url}"
               style="display:inline-block;padding:16px 40px;color:#fff;text-decoration:none;font-size:15px;font-weight:700;letter-spacing:.3px;border-radius:12px;">
              Definir minha senha
            </a>
          </td></tr>
        </table>

        <!-- Separador -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
          <tr>
            <td style="border-top:1px solid #ebebeb;"></td>
            <td style="padding:0 14px;color:#ccc;font-size:12px;white-space:nowrap;">ou copie o link</td>
            <td style="border-top:1px solid #ebebeb;"></td>
          </tr>
        </table>
        <p style="margin:0;font-size:12px;word-break:break-all;">
          <a href="{url}" style="color:#6366f1;">{url}</a>
        </p>
      </td></tr>

      <!-- Dica de segurança -->
      <tr><td style="padding:0 40px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:#f9f7ff;border:1px solid #e0d9ff;border-radius:10px;padding:16px 20px;">
          <tr><td>
            <p style="margin:0 0 6px;font-size:12px;font-weight:700;color:#4f46e5;text-transform:uppercase;letter-spacing:.5px;">
              Dica de segurança
            </p>
            <p style="margin:0;font-size:12px;color:#666;line-height:1.6;">
              Use uma senha com pelo menos 8 caracteres, combinando letras maiúsculas,
              minúsculas, números e símbolos. Nunca compartilhe sua senha com ninguém.
            </p>
          </td></tr>
        </table>
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding:20px 40px;background:#f9f9fb;border-top:1px solid #ebebeb;text-align:center;">
        <p style="margin:0 0 4px;font-size:11px;color:#aaa;">
          Sistema interno Vendemmia &middot; Não responda este e-mail
        </p>
        <p style="margin:0;font-size:11px;color:#ccc;">
          Se não esperava este e-mail, ignore-o. Sua conta não será ativada sem a definição de senha.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def send_welcome_email(name: str, email: str) -> bool:
    """Gera token 24h, salva no Turso e envia e-mail de boas-vindas. Retorna True se ok."""
    if not _SMTP_HOST:
        print("⚠ SMTP não configurado no .env — e-mail não enviado.")
        print(f"  Configure SMTP_HOST, SMTP_USER e SMTP_PASS no arquivo api/.env")
        return False

    # Garante que a tabela de tokens existe
    try:
        run_turso_stmt(
            "CREATE TABLE IF NOT EXISTS password_reset_tokens "
            "(token TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER DEFAULT 0)"
        )
    except Exception as e:
        print(f"⚠ Não foi possível criar tabela de tokens: {e}")
        return False

    token      = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    try:
        run_turso_stmt(
            "INSERT INTO password_reset_tokens (token, email, expires_at, used) VALUES (?,?,?,0)",
            [token, email, expires_at],
        )
    except Exception as e:
        print(f"⚠ Erro ao salvar token no banco: {e}")
        return False

    link = f"{_BASE_URL}/login.html?reset={token}&welcome=1"
    html = _welcome_email_html(name, link)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Bem-vindo ao Sistema de Análise de Crédito — Vendemmia"
    msg["From"]    = f"Vendemmia Análise de Crédito <{_FROM_EMAIL}>"
    msg["To"]      = email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=20) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if _SMTP_USER:
                s.login(_SMTP_USER, _SMTP_PASS)
            s.sendmail(_FROM_EMAIL, [email], msg.as_string())
        return True
    except Exception as e:
        print(f"⚠ Falha ao enviar e-mail: {e}")
        return False


_ROLES = [
    ("Operações",     "Cria, envia e edita análises; faz consultas na tela de Consulta"),
    ("Financeiro",    "Aprova / nega crédito; faz consultas na tela de Consulta"),
    ("Administrador", "Acesso total em todas as telas, funções e criação de usuários"),
    ("Diretor",       "Acesso total com perfil de diretoria (sem tela de criação de usuários)"),
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
    uid     = "u_" + secrets.token_urlsafe(8)
    now_iso = datetime.utcnow().isoformat()

    import getpass

    try:
        existing = run_turso_stmt("SELECT id FROM users WHERE email = ?", [email])

        if existing:
            # Atualização: senha obrigatória
            print(f"\n⚠ Usuário {email} já existe. Informe nova senha para atualizar.")
            while True:
                pw  = getpass.getpass("Nova senha (min. 8 caracteres): ")
                pw2 = getpass.getpass("Confirme a senha: ")
                if pw != pw2:
                    print("⚠ Senhas não coincidem. Tente novamente.")
                    continue
                if len(pw) < 8:
                    print("⚠ Senha muito curta (mínimo 8 caracteres).")
                    continue
                break
            hashed = pwd_context.hash(pw)
            run_turso_stmt(
                "UPDATE users SET name = ?, hashed_password = ?, role = ?, avatar = ?, updated_at = ? WHERE email = ?",
                [name, hashed, role, avatar, now_iso, email]
            )
            print(f"\n✓ Usuário {email} atualizado com sucesso.")

        else:
            # Criação: oferecer e-mail de boas-vindas
            print("\nComo definir a senha do novo usuário?")
            print("  [1] Enviar e-mail de boas-vindas (usuário define a própria senha) ← recomendado")
            print("  [2] Definir senha agora (você informa e repassa ao usuário)")
            opcao = input("Opção [1/2] (Enter = 1): ").strip() or "1"

            if opcao == "1":
                # Cria sem senha — usuário define pelo link do e-mail
                run_turso_stmt(
                    "INSERT INTO users (id, name, email, hashed_password, role, avatar, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [uid, name, email, "", role, avatar, now_iso, now_iso]
                )
                print(f"\n✓ Usuário criado: {name} <{email}> [{role}]")
                print("  Enviando e-mail de boas-vindas...", end=" ", flush=True)
                ok = send_welcome_email(name, email)
                if ok:
                    print("✓ E-mail enviado!")
                    print(f"  O usuário receberá um link válido por 24 horas para definir a senha.")
                else:
                    print("✗ Falha no envio.")
                    print("  Verifique as configurações de SMTP no arquivo api/.env")
            else:
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
                run_turso_stmt(
                    "INSERT INTO users (id, name, email, hashed_password, role, avatar, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [uid, name, email, hashed, role, avatar, now_iso, now_iso]
                )
                print(f"\n✓ Usuário criado com sucesso no banco: {name} <{email}> [{role}]")
                print("  Repasse a senha ao usuário com segurança.")

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
