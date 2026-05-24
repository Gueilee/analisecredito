"""
Vendemmia — Análise de Crédito  |  API Backend
FastAPI + BrasilAPI (Receita Federal) + Claude AI
"""

import asyncio
import base64
import io
import json
import os
import re
import secrets
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import openpyxl
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

_ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

# ── Diretórios de dados ───────────────────────────────────────────────────────
# No Vercel o sistema de arquivos é read-only; usa /tmp para dados temporários
_IS_VERCEL = bool(os.getenv("VERCEL"))
_TMP_BASE  = Path("/tmp") if _IS_VERCEL else Path(__file__).parent

HISTORICO_DIR = _TMP_BASE / "historico"
HISTORICO_DIR.mkdir(exist_ok=True)

DOCS_DIR = _TMP_BASE / "docs"
DOCS_DIR.mkdir(exist_ok=True)

BACKUPS_DIR = _TMP_BASE / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)

# ── Turso / libSQL ────────────────────────────────────────────────────────────
_TURSO_URL   = os.getenv("TURSO_URL",   "")
_TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")


def _turso_ok() -> bool:
    return bool(_TURSO_URL and _TURSO_TOKEN)


def _turso_http() -> str:
    return _TURSO_URL.replace("libsql://", "https://")


async def _turso(stmts: list) -> dict:
    if not _turso_ok():
        raise HTTPException(503, "Banco de dados Turso não configurado.")
    url = f"{_turso_http()}/v2/pipeline"
    payload = {"requests": [{"type": "execute", "stmt": s} for s in stmts] + [{"type": "close"}]}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {_TURSO_TOKEN}"})
    r.raise_for_status()
    return r.json()


async def _turso_query(sql: str, args: list | None = None) -> list[dict]:
    stmt: dict = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "null"} if a is None else {"type": "text", "value": str(a)} for a in args]
    result = await _turso([stmt])
    res  = result["results"][0]["response"]["result"]
    cols = [c["name"] for c in res["cols"]]
    return [
        dict(zip(cols, [v.get("value") if v.get("type") != "null" else None for v in row]))
        for row in res["rows"]
    ]


async def _turso_exec(sql: str, args: list | None = None) -> None:
    stmt: dict = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "null"} if a is None else {"type": "text", "value": str(a)} for a in args]
    await _turso([stmt])


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Vendemmia Credit API",
    version="2.0.0",
    docs_url=None,   # desabilita /docs em produção
    redoc_url=None,  # desabilita /redoc em produção
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (origens configuradas via .env) ──────────────────────────────────────
_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Security Headers Middleware ───────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({
        "X-Content-Type-Options":  "nosniff",
        "X-Frame-Options":         "DENY",
        "X-XSS-Protection":        "1; mode=block",
        "Referrer-Policy":         "strict-origin-when-cross-origin",
        "Permissions-Policy":      "camera=(), microphone=(), geolocation=()",
        "Cache-Control":           "no-store",
    })
    if os.getenv("HTTPS_ONLY", "false").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return response


# ── JWT / Autenticação ────────────────────────────────────────────────────────
_USERS_FILE    = Path(__file__).parent / "users.json"
_pwd_ctx       = CryptContext(schemes=["bcrypt"], deprecated="auto")
_JWT_SECRET    = os.getenv("APP_SECRET_KEY") or secrets.token_hex(32)
_JWT_ALG       = "HS256"
_JWT_HOURS     = int(os.getenv("SESSION_HOURS", "8"))
_SECURE_COOKIE = os.getenv("HTTPS_ONLY", "false").lower() == "true"


def _load_users() -> list:
    # Vercel: usa variável de ambiente USERS_JSON quando o arquivo não existe
    if not _USERS_FILE.exists():
        raw = os.getenv("USERS_JSON", "")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return []
        return []
    try:
        return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _create_token(data: dict) -> str:
    payload = {**data, "exp": datetime.utcnow() + timedelta(hours=_JWT_HOURS)}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALG)


async def _get_current_user(vd_token: Optional[str] = Cookie(default=None)):
    if not vd_token:
        raise HTTPException(status_code=401, detail="Sessão não encontrada — faça login")
    try:
        return jwt.decode(vd_token, _JWT_SECRET, algorithms=[_JWT_ALG])
    except JWTError:
        raise HTTPException(status_code=401, detail="Sessão expirada — faça login novamente")


# ── Role / RLS helpers ───────────────────────────────────────────────────────
# Perfis que podem tomar decisões de crédito (aprovar / negar / encaminhar)
_ROLES_DECISION = {"Financeiro", "Administrador", "Admin", "Diretor"}


def _user_can_decide(user: dict) -> bool:
    role = user.get("role", "")
    return any(r in role for r in _ROLES_DECISION)


def _record_visible_to(record: dict, user: dict) -> bool:
    """RLS: Financeiro/Admin vêem todos; Operações vê apenas seus próprios registros.
    Registros legados sem created_by são visíveis a todos (migração transparente)."""
    if _user_can_decide(user):
        return True
    cb = record.get("created_by") or {}
    if not cb:
        return True
    return cb.get("id") == user.get("sub")


_ROLES_ADMIN = {"Administrador", "Admin"}


async def _require_admin(current_user=Depends(_get_current_user)):
    role = current_user.get("role", "")
    if not any(r in role for r in _ROLES_ADMIN):
        raise HTTPException(403, "Acesso negado — apenas Administradores")
    return current_user


# ── Modelos de autenticação ───────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


# ── Endpoints de autenticação ─────────────────────────────────────────────────
@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def auth_login(request: Request, response: Response, body: LoginRequest):
    users = _load_users()
    if not users:
        raise HTTPException(503, detail="Sistema não configurado. Execute: python create_user.py")
    user = next((u for u in users if u.get("email", "").lower() == body.email.strip().lower()), None)
    await asyncio.sleep(0.3)  # delay fixo para prevenir timing attacks
    if not user or not _pwd_ctx.verify(body.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    token = _create_token({
        "sub":   user["id"],
        "email": user["email"],
        "name":  user["name"],
        "role":  user.get("role", "Operações"),
    })
    response.set_cookie(
        key="vd_token", value=token,
        httponly=True, samesite="lax",
        secure=_SECURE_COOKIE,
        max_age=_JWT_HOURS * 3600,
        path="/"
    )
    return {
        "ok": True,
        "user": {
            "id":     user["id"],
            "name":   user["name"],
            "email":  user["email"],
            "role":   user.get("role", "Operações"),
            "avatar": user.get("avatar", user["name"][:2].upper()),
        }
    }


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(key="vd_token", path="/", samesite="lax")
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(current_user=Depends(_get_current_user)):
    return {"user": current_user}


# ── Constantes ────────────────────────────────────────────────────────────────
BRASILAPI  = "https://brasilapi.com.br/api/cnpj/v1"
_SOL_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{4,64}$')


# ── Modelos ──────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    cnpj: str
    empresa: str
    ramo: Optional[str] = ""
    produto: Optional[str] = ""
    modal: Optional[str] = ""
    segmento: Optional[str] = ""
    origens: Optional[str] = ""
    incoterms: Optional[str] = ""
    tipoOp: Optional[str] = ""
    # Limites
    limiteExportador: Optional[str] = ""
    limiteDesp: Optional[str] = ""
    limiteImp: Optional[str] = ""
    # Volume
    volMes: Optional[str] = ""
    volMesMoeda: Optional[str] = "BRL"
    vol6Meses: Optional[str] = ""
    vol6MesesMoeda: Optional[str] = "USD"
    volPotencial: Optional[str] = ""
    volPotencialMoeda: Optional[str] = "USD"
    # Prazos
    prazoInvoiceData:    Optional[str] = ""
    prazoPrepEmbarque:   Optional[str] = ""
    prazoEmbarque:       Optional[str] = ""
    prazoTransit:        Optional[str] = ""
    prazoDesembaraco:    Optional[str] = ""
    prazoFaturamento:    Optional[str] = ""
    prazoPagtoVendemmia: Optional[str] = ""
    # Fundação
    fundacao: Optional[str] = ""
    # Operação
    importadorFatura: Optional[str] = ""
    consignatario: Optional[str] = ""
    pagtoClienteExp: Optional[str] = ""
    custoFin:     Optional[str] = ""
    custoFinDesc: Optional[str] = ""
    cessao: Optional[str] = ""
    cessaoResp: Optional[str] = ""
    # Financeiro
    rentabilidade: Optional[str] = ""
    rentabilidadeObs: Optional[str] = ""
    custoAdm:       Optional[str] = ""
    custoAdmObs:    Optional[str] = ""
    analyticsValor: Optional[str] = ""
    custoAdmPct:    Optional[str] = ""
    custoAdmBase:   Optional[str] = ""
    custoAdmOutros: Optional[str] = ""
    desconto: Optional[str] = ""
    # Contexto
    comentario: Optional[str] = ""

    @model_validator(mode='before')
    @classmethod
    def _coerce_optional_strings(cls, data: Any) -> Any:
        """Converte arrays/objetos/números para str nos campos opcionais.
        Evita erro 422 quando o frontend envia valores não-string (ex: arrays de seleção múltipla)."""
        if not isinstance(data, dict):
            return data
        required = {'cnpj', 'empresa'}
        for k, v in data.items():
            if k in required:
                continue
            if v is None:
                data[k] = ''
            elif isinstance(v, list):
                data[k] = ', '.join(str(i) for i in v) if v else ''
            elif isinstance(v, dict):
                data[k] = ''
            elif not isinstance(v, str):
                data[k] = str(v)
        return data


# ── Helpers ──────────────────────────────────────────────────────────────────

def clean_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def br_to_float(val: str) -> float:
    """Converte '250.000,00' → 250000.0"""
    if not val:
        return 0.0
    try:
        return float(val.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def calc_tempo_mercado(fundacao: str) -> str:
    if not fundacao:
        return "Não informado"
    try:
        dt = datetime.strptime(fundacao[:10], "%Y-%m-%d").date()
        anos = (date.today() - dt).days // 365
        meses = ((date.today() - dt).days % 365) // 30
        if anos == 0:
            return f"{meses} {'mês' if meses == 1 else 'meses'}"
        return f"{anos} {'ano' if anos == 1 else 'anos'}" + (f" e {meses} meses" if meses else "")
    except ValueError:
        return fundacao


# ── Consulta BrasilAPI ───────────────────────────────────────────────────────

async def fetch_receita(cnpj: str) -> dict:
    clean = clean_cnpj(cnpj)
    if len(clean) != 14:
        return {"status": "invalid", "data": {}, "error": "CNPJ deve ter 14 dígitos"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(f"{BRASILAPI}/{clean}")
        if resp.status_code == 200:
            return {"status": "ok", "data": resp.json()}
        if resp.status_code == 404:
            return {"status": "not_found", "data": {}, "error": "CNPJ não encontrado na Receita Federal"}
        return {"status": "error", "data": {}, "error": f"BrasilAPI retornou HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"status": "timeout", "data": {}, "error": "Timeout ao consultar Receita Federal"}
    except Exception as exc:
        return {"status": "error", "data": {}, "error": str(exc)}


# ── Prompt ───────────────────────────────────────────────────────────────────

def build_prompt(req: AnalyzeRequest, receita: dict) -> str:
    d = receita.get("data", {})
    bureau_ok = receita.get("status") == "ok"

    # Quadro societário
    qsa_lines = ""
    if d.get("qsa"):
        rows = []
        for s in d["qsa"]:
            rows.append(
                f"  • {s.get('nome_socio','?')} | "
                f"{s.get('percentual_capital_social','?')}% | "
                f"Faixa etária: {s.get('faixa_etaria','?')} | "
                f"Entrada: {s.get('data_entrada_sociedade','?')}"
            )
        qsa_lines = "\n".join(rows)

    # Seção Receita Federal
    if bureau_ok and d:
        abertura = d.get("data_inicio_atividade", "")
        try:
            dt = datetime.strptime(abertura, "%Y-%m-%d").date()
            anos_rf = (date.today() - dt).days // 365
            tempo_rf = f"{anos_rf} anos"
        except Exception:
            tempo_rf = abertura

        receita_section = f"""
## DADOS DA RECEITA FEDERAL (BrasilAPI — tempo real)
- Razão Social: {d.get('razao_social', '—')}
- Nome Fantasia: {d.get('nome_fantasia') or '—'}
- Situação Cadastral: {d.get('descricao_situacao_cadastral', '—')}
- Data da Situação: {d.get('data_situacao_cadastral', '—')}
- Abertura: {abertura} ({tempo_rf})
- Capital Social: R$ {d.get('capital_social', 0):,.2f}
- Natureza Jurídica: {d.get('descricao_natureza_juridica', '—')}
- Porte: {d.get('descricao_porte', '—')}
- CNAE Principal: {d.get('cnae_fiscal', '—')} — {d.get('cnae_fiscal_descricao', '—')}
- Simples Nacional: {'Sim' if d.get('opcao_pelo_simples') else 'Não'}
- MEI: {'Sim' if d.get('opcao_pelo_mei') else 'Não'}
- UF / Município: {d.get('uf', '—')} / {d.get('municipio', '—')}

## QUADRO SOCIETÁRIO (QSA)
{qsa_lines or 'Não disponível'}
"""
    else:
        receita_section = f"""
## DADOS DA RECEITA FEDERAL
Status: {receita.get('status')} — {receita.get('error', 'Indisponível')}
CNPJ informado: {req.cnpj}
"""

    # Cálculo de exposição total
    exp_total = br_to_float(req.limiteExportador) + br_to_float(req.limiteDesp) + br_to_float(req.limiteImp)
    exp_str = f"R$ {exp_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    tempo_mercado = calc_tempo_mercado(req.fundacao) if req.fundacao else "Não informado"

    return f"""Você é um analista de crédito sênior especializado em empresas importadoras no Brasil,
trabalhando na Vendemmia — empresa de logística de importação (Trading/Account).

O crédito que a Vendemmia concede representa o risco de pagar adiantado fretes internacionais,
despesas alfandegárias e impostos de importação, sendo reembolsado pelo cliente posteriormente.
Inadimplência = Vendemmia absorve o custo integralmente.

{receita_section}

## DADOS DA SOLICITAÇÃO (informados pelo time de operações)
- Empresa: {req.empresa}
- CNPJ: {req.cnpj}
- Ramo de atividade: {req.ramo or 'Não informado'}
- Produto importado: {req.produto or 'Não informado'}
- Modal logístico: {req.modal or 'Não informado'}
- Segmento: {req.segmento or 'Não informado'}
- Principais origens: {req.origens or 'Não informado'}
- Incoterms: {req.incoterms or 'Não informado'}
- Tipo de operação: {req.tipoOp or 'Não informado'}
- Tempo de mercado (declarado): {tempo_mercado}

## LIMITES SOLICITADOS
- Exportador (câmbio/mercadoria): R$ {req.limiteExportador or '0'}
- Despesas alfandegárias: R$ {req.limiteDesp or '0'}
- Impostos de importação: R$ {req.limiteImp or '0'}
- EXPOSIÇÃO TOTAL: {exp_str}

## VOLUME DE NEGÓCIOS
- Volume mensal estimado: {req.volMes or '—'} {req.volMesMoeda or ''}
- Volume 6 meses estimado: {req.vol6Meses or '—'} {req.vol6MesesMoeda or ''}
- Potencial anual: {req.volPotencial or '—'} {req.volPotencialMoeda or ''}
- Rentabilidade Vendemmia: {req.rentabilidade or '—'}%{(' (' + req.rentabilidadeObs + ')') if req.rentabilidadeObs else ''}
- Plataforma Analytics: R$ {req.analyticsValor or '500,00'} por processo
- Taxa administrativa: {(req.custoAdmPct + '% sobre ' + (req.custoAdmBase or 'CIF') + ((' — ' + req.custoAdmObs) if req.custoAdmObs else '')) if req.custoAdmPct else '—'}
{('- Outros custos adm.: ' + req.custoAdmOutros) if req.custoAdmOutros else ''}
- Desconto sobre tabela: {req.desconto or '0'}%

## ESTRUTURA DA OPERAÇÃO
- Importador da fatura: {req.importadorFatura or '—'}
- Consignatário: {req.consignatario or '—'}
- Pagamento ao exportador: {req.pagtoClienteExp or '—'}
- Custo financeiro cobrado do cliente: {req.custoFin or '—'}{(' (' + req.custoFinDesc + ')') if req.custoFinDesc else ''}
- Cessão de crédito: {req.cessao or '—'}{(' — Responsável: ' + req.cessaoResp) if req.cessaoResp else ''}

## PRAZOS
- Invoice: {req.prazoInvoiceData or '—'}
- Preparação para embarque: {req.prazoPrepEmbarque or '—'} dias
- Embarque: {req.prazoEmbarque or '—'} dias
- Trânsito internacional: {req.prazoTransit or '—'} dias
- Desembaraço aduaneiro: {req.prazoDesembaraco or '—'} dias
- Faturamento: {req.prazoFaturamento or '—'} dias
- Pagamento à Vendemmia: {req.prazoPagtoVendemmia or '—'} dias

Retorne APENAS um JSON válido, sem texto adicional antes ou depois:

{{
  "score": <inteiro 0-100; 100 = risco mínimo / empresa excelente>,
  "classificacao": "<AAA|AA|A|BB|B|CC|C|D>",
  "recomendacao": "<aprovar|negar|revisar>",
  "limite_recomendado_exportador": "<R$ formatado ou 'Não recomendado'>",
  "limite_recomendado_desp": "<R$ formatado ou 'Não recomendado'>",
  "limite_recomendado_imp": "<R$ formatado ou 'Não recomendado'>",
  "exposicao_total_recomendada": "<R$ formatado>",
  "prazo_recomendado": <30|45|60|90|120>,
  "resumo_executivo": "<2-3 frases objetivas e diretas>",
  "pontos_positivos": ["<ponto 1>", "<ponto 2>"],
  "pontos_atencao": ["<ponto 1>", "<ponto 2>"],
  "alertas_criticos": [],
  "analise_cadastral": "<análise da situação na Receita Federal em 2-3 frases>",
  "analise_societaria": "<análise do quadro societário, perfil dos sócios, concentração de capital>",
  "analise_proporcionalidade": "<análise da proporcionalidade entre exposição total, capital social e volume declarado>",
  "analise_operacional": "<análise dos riscos operacionais: modal, origens, prazo de trânsito, tipo de operação>",
  "fundamentacao": "<análise completa em 3-5 parágrafos cobrindo: (1) situação cadastral e societária, (2) proporcionalidade do crédito, (3) riscos operacionais de importação, (4) recomendação final com condições>"
}}

Diretrizes de pontuação (orientativas):
- Situação ATIVA na Receita Federal: +25 pts
- Empresa > 5 anos: +20 pts | 2-5 anos: +10 pts | < 2 anos: -10 pts
- Capital social ≥ exposição total: +15 pts | ≥ 50%: +8 pts | < 20%: -10 pts
- CNAE compatível com produto importado: +10 pts
- Simples Nacional: -3 pts | MEI: -25 pts (limitar a R$ 10.000)
- Situação INAPTA ou BAIXADA: score ≤ 15, recomendação obrigatoriamente "negar"
- Sócio único + empresa < 1 ano: alerta crítico
- Exposição > 3× volume mensal declarado: alerta crítico
{('## OBSERVAÇÕES DO ANALISTA\n' + req.comentario) if req.comentario else ''}
"""


# ── Endpoints ────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Extrai o objeto JSON da resposta do Claude."""
    # Estratégia 1: parse direto
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Estratégia 2: segmentos entre triple-backticks
    parts = text.split("```")
    for part in parts:
        candidate = part.strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
        if candidate.startswith("{"):
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    # Estratégia 3: primeiro { ao último }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None


def _load_key() -> str:
    """Carrega e limpa a chave do .env, removendo espaços e quebras de linha."""
    load_dotenv(dotenv_path=_ENV_FILE, override=True)
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


# ── Modelo histórico ─────────────────────────────────────────────────────────

class HistoricoSaveRequest(BaseModel):
    solicitacao_id: str
    empresa: str
    cnpj: str
    status_solicitacao: Optional[str] = ""
    solicitante: Optional[str] = ""
    data_solicitacao: Optional[str] = ""
    dados_solicitacao: Optional[Dict[str, Any]] = None
    receita_federal: Optional[Dict[str, Any]] = None
    analise_ia: Optional[Dict[str, Any]] = None
    modelo_ia: Optional[str] = "claude-sonnet-4-6"
    # Timestamps das etapas do processo
    solicitacao_criada_at: Optional[str] = None
    rf_consultada_at: Optional[str] = None
    analise_ia_at: Optional[str] = None


def _hist_id_safe(hist_id: str) -> bool:
    return bool(re.match(r'^[a-f0-9\-]{36}$', hist_id))


@app.post("/api/historico")
async def salvar_historico(entry: HistoricoSaveRequest, current_user=Depends(_get_current_user)):
    now_iso = datetime.now().isoformat()
    hist_id = str(uuid.uuid4())
    record = {
        "id": hist_id,
        "solicitacao_id": entry.solicitacao_id,
        "empresa": entry.empresa,
        "cnpj": entry.cnpj,
        "status_solicitacao": entry.status_solicitacao or "",
        # Sobrescreve com o usuário autenticado — não confia no valor enviado pelo frontend
        "solicitante": current_user.get("name", entry.solicitante or ""),
        "data_solicitacao": entry.data_solicitacao or "",
        "dados_solicitacao": entry.dados_solicitacao or {},
        "receita_federal": entry.receita_federal or {},
        "analise_ia": entry.analise_ia or {},
        "modelo_ia": entry.modelo_ia or "claude-sonnet-4-6",
        "decisao_analista": None,
        # RLS: identidade do criador (usado para filtro por perfil)
        "created_by": {
            "id":    current_user.get("sub", ""),
            "email": current_user.get("email", ""),
            "name":  current_user.get("name", ""),
        },
        # Timestamps auditáveis de cada etapa do processo
        "timestamps": {
            "solicitacao_criada_at": entry.solicitacao_criada_at or entry.data_solicitacao or "",
            "rf_consultada_at":      entry.rf_consultada_at or now_iso,
            "analise_ia_at":         entry.analise_ia_at    or now_iso,
            "historico_salvo_at":    now_iso,
            "decisao_at":            None,
        },
    }
    (HISTORICO_DIR / f"{hist_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"id": hist_id, "salvo_em": now_iso}


@app.get("/api/historico")
async def listar_historico(
    cnpj: Optional[str] = None,
    empresa: Optional[str] = None,
    limit: int = 200,
    current_user=Depends(_get_current_user),
):
    files = sorted(
        HISTORICO_DIR.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    entries: List[dict] = []
    for f in files:
        if len(entries) >= limit:
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # RLS — filtra pelo criador se o usuário não tem perfil de decisão
            if not _record_visible_to(data, current_user):
                continue
            if cnpj:
                if re.sub(r"\D", "", cnpj) not in re.sub(r"\D", "", data.get("cnpj", "")):
                    continue
            if empresa:
                if empresa.lower() not in data.get("empresa", "").lower():
                    continue
            ai = data.get("analise_ia") or {}
            rf = (data.get("receita_federal") or {}).get("data") or {}
            ts = data.get("timestamps") or {}
            dec = data.get("decisao_analista") or {}
            entries.append({
                "id": data["id"],
                "cnpj": data["cnpj"],
                "empresa": data["empresa"],
                "score": ai.get("score"),
                "classificacao": ai.get("classificacao"),
                "recomendacao": ai.get("recomendacao"),
                "resumo_executivo": (ai.get("resumo_executivo") or "")[:250],
                "alertas_criticos": len(ai.get("alertas_criticos") or []),
                "pontos_positivos": len(ai.get("pontos_positivos") or []),
                "limite_recomendado_exportador": ai.get("limite_recomendado_exportador"),
                "exposicao_total_recomendada": ai.get("exposicao_total_recomendada"),
                "prazo_recomendado": ai.get("prazo_recomendado"),
                "rf_situacao": rf.get("descricao_situacao_cadastral"),
                "rf_abertura": rf.get("data_inicio_atividade"),
                "solicitante": data.get("solicitante"),
                "data_solicitacao": data.get("data_solicitacao"),
                "status_solicitacao": data.get("status_solicitacao"),
                "decisao_analista": dec,
                "modelo_ia": data.get("modelo_ia"),
                "solicitacao_id": data.get("solicitacao_id"),
                # Objetos completos — necessários para exibição detalhada na tela Consulta
                "receita_federal": data.get("receita_federal") or {},
                "analise_ia":      data.get("analise_ia")      or {},
                "dados_solicitacao": data.get("dados_solicitacao") or {},
                # Timestamps auditáveis
                "timestamps": {
                    "solicitacao_criada_at": ts.get("solicitacao_criada_at") or data.get("data_solicitacao"),
                    "rf_consultada_at":      ts.get("rf_consultada_at"),
                    "analise_ia_at":         ts.get("analise_ia_at"),
                    "historico_salvo_at":    ts.get("historico_salvo_at"),
                    "decisao_at":            ts.get("decisao_at") or dec.get("decisao_at"),
                },
            })
        except Exception:
            continue
    return {"total": len(entries), "entries": entries}


@app.get("/api/historico/{hist_id}")
async def buscar_historico(hist_id: str, current_user=Depends(_get_current_user)):
    if not _hist_id_safe(hist_id):
        raise HTTPException(400, "ID inválido")
    f = HISTORICO_DIR / f"{hist_id}.json"
    if not f.exists():
        raise HTTPException(404, "Análise não encontrada")
    data = json.loads(f.read_text(encoding="utf-8"))
    # RLS — retorna 404 intencional para não revelar a existência do registro
    if not _record_visible_to(data, current_user):
        raise HTTPException(404, "Análise não encontrada")
    return data


@app.patch("/api/historico/{hist_id}/decisao")
async def atualizar_decisao(hist_id: str, body: Dict[str, Any], current_user=Depends(_get_current_user)):
    # RBAC — apenas Financeiro, Administrador e Diretor podem registrar decisões
    if not _user_can_decide(current_user):
        raise HTTPException(403, "Acesso negado — apenas Financeiro e Administrador podem registrar decisões de crédito")
    if not _hist_id_safe(hist_id):
        raise HTTPException(400, "ID inválido")
    f = HISTORICO_DIR / f"{hist_id}.json"
    if not f.exists():
        raise HTTPException(404, "Análise não encontrada")
    data = json.loads(f.read_text(encoding="utf-8"))
    now_iso = datetime.now().isoformat()

    # Campos da decisão que vêm do frontend
    decisao_at = body.get("decisao_at") or now_iso
    decisao_payload = {
        "status":           body.get("status", ""),
        "limiteAprovado":   body.get("limiteAprovado", ""),
        "limiteDesp":       body.get("limiteDesp", ""),
        "limiteImp":        body.get("limiteImp", ""),
        "prazoAprovado":    body.get("prazoAprovado", ""),
        "analistaObs":      body.get("analistaObs", ""),
        "parecerTecnico":   body.get("parecerTecnico", ""),
        # Sobrescreve com o usuário autenticado — não confia no valor enviado pelo frontend
        "decisaoAnalista":  current_user.get("name", body.get("decisaoAnalista", "Analista")),
        "decisao_at":       decisao_at,
    }

    # Grava em decisao_analista (campo dedicado)
    data["decisao_analista"] = decisao_payload

    # Atualiza status_solicitacao no nível raiz (usado em listagens)
    if decisao_payload["status"]:
        data["status_solicitacao"] = decisao_payload["status"]

    # Mescla campos da decisão em dados_solicitacao para consulta completa
    ds = data.get("dados_solicitacao") or {}
    ds.update({
        "status":          decisao_payload["status"],
        "limiteAprovado":  decisao_payload["limiteAprovado"],
        "limiteDesp":      decisao_payload["limiteDesp"],
        "limiteImp":       decisao_payload["limiteImp"],
        "prazoAprovado":   decisao_payload["prazoAprovado"],
        "analistaObs":     decisao_payload["analistaObs"],
        "parecerTecnico":  decisao_payload["parecerTecnico"],
        "decisaoAnalista": decisao_payload["decisaoAnalista"],
        "decisao_at":      decisao_at,
    })
    data["dados_solicitacao"] = ds

    # Atualiza timestamp da decisão
    if "timestamps" not in data:
        data["timestamps"] = {}
    data["timestamps"]["decisao_at"] = decisao_at

    data["atualizado_em"] = now_iso
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "decisao_at": decisao_at}


# ── Upload de documentos financeiros ────────────────────────────────────────

_MIME_MAP = {
    ".pdf":  "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
}

@app.post("/api/docs/{sol_id}/upload")
async def upload_docs(
    sol_id:    str,
    balanco:   List[UploadFile] = File(default=[]),
    contrato:  List[UploadFile] = File(default=[]),
    dre:       List[UploadFile] = File(default=[]),
    fat:       List[UploadFile] = File(default=[]),
    current_user=Depends(_get_current_user),
):
    """Salva documentos financeiros no Turso (persistente no Vercel)."""
    if not _SOL_ID_RE.match(sol_id):
        raise HTTPException(400, "sol_id inválido")
    if not _turso_ok():
        raise HTTPException(503, "Banco de dados não configurado.")
    sal = []
    for tipo, uploads in [("balanco", balanco), ("contrato", contrato), ("dre", dre), ("fat", fat)]:
        for f in uploads:
            raw = await f.read()
            if not raw:
                continue
            fname = Path(f.filename or "doc").name
            ext   = Path(fname).suffix.lower()
            mime  = _MIME_MAP.get(ext, f.content_type or "application/octet-stream")
            b64   = base64.standard_b64encode(raw).decode()
            doc_id = f"{sol_id}__{tipo}__{fname}"
            now    = datetime.utcnow().isoformat()
            await _turso_exec(
                "INSERT OR REPLACE INTO documents (id, sol_id, tipo, nome, content, mime, size_bytes, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [doc_id, sol_id, tipo, fname, b64, mime, len(raw), now],
            )
            sal.append(f"{tipo}/{fname}")
    return {"saved": sal, "sol_id": sol_id}


@app.get("/api/docs/{sol_id}/{tipo}/{fname}")
async def download_doc(sol_id: str, tipo: str, fname: str, current_user=Depends(_get_current_user)):
    """Baixa um documento armazenado no Turso."""
    if not _turso_ok():
        raise HTTPException(503, "Banco de dados não configurado.")
    rows = await _turso_query(
        "SELECT content, mime, nome FROM documents WHERE sol_id=? AND tipo=? AND nome=?",
        [sol_id, tipo, fname],
    )
    if not rows:
        raise HTTPException(404, "Arquivo não encontrado.")
    row = rows[0]
    raw = base64.standard_b64decode(row["content"])
    safe_name = Path(row["nome"]).name
    return Response(
        content=raw,
        media_type=row["mime"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Extração de indicadores financeiros ─────────────────────────────────────

def _xlsx_to_text(data: bytes, filename: str) -> str:
    """Converte Excel para texto tabular para enviar ao Claude."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = [f"=== {filename} ==="]
        for name in wb.sheetnames:
            ws = wb[name]
            lines.append(f"\n--- Planilha: {name} ---")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                line  = " | ".join(cells)
                if line.replace("|", "").strip():
                    lines.append(line)
        return "\n".join(lines)
    except Exception as exc:
        return f"[Erro ao ler {filename}: {exc}]"


def _build_content_from_files(file_list: list) -> list:
    """Converte lista de (raw_bytes, filename) em partes de conteúdo Claude."""
    content = []
    for raw, fname in file_list:
        if fname.lower().endswith(".pdf"):
            b64 = base64.standard_b64encode(raw).decode()
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                "title": fname,
            })
        elif fname.lower().endswith((".xlsx", ".xls")):
            content.append({"type": "text", "text": _xlsx_to_text(raw, fname)})
    return content


@app.post("/api/extract-financials")
@limiter.limit("10/minute")
async def extract_financials(
    request: Request,
    empresa: str = Form(""),
    cnpj:    str = Form(""),
    sol_id:  str = Form(""),
    files:   List[UploadFile] = File(default=[]),
    current_user=Depends(_get_current_user),
):
    """Extrai indicadores financeiros de PDFs/Excel via Claude.

    Aceita duas fontes (em ordem de prioridade):
    1. sol_id — lê arquivos já salvos em /api/docs/{sol_id}/
    2. files  — upload direto de arquivos pelo usuário
    """
    key = _load_key()
    if not key:
        raise HTTPException(503, "ANTHROPIC_API_KEY não configurada")

    file_list: list[tuple[bytes, str]] = []

    # Prioridade 1: arquivos salvos no Turso
    if sol_id and _SOL_ID_RE.match(sol_id) and _turso_ok():
        rows = await _turso_query(
            "SELECT nome, content FROM documents WHERE sol_id=? AND tipo IN ('balanco','dre') ORDER BY tipo, nome",
            [sol_id],
        )
        for row in rows:
            ext = Path(row["nome"]).suffix.lower()
            if ext in (".pdf", ".xlsx", ".xls"):
                raw = base64.standard_b64decode(row["content"])
                file_list.append((raw, row["nome"]))

    # Prioridade 2: upload direto (fallback)
    if not file_list and files:
        for f in files:
            raw = await f.read()
            if raw:
                file_list.append((raw, f.filename or "doc"))

    if not file_list:
        raise HTTPException(
            404 if sol_id else 400,
            "Nenhum documento encontrado. Envie os arquivos ou verifique se o upload foi realizado."
        )

    client  = Anthropic(api_key=key)
    content = _build_content_from_files(file_list)
    if not content:
        raise HTTPException(400, "Nenhum arquivo em formato suportado (PDF, XLSX)")

    prompt = f"""Você é um analista financeiro. Analise os documentos da empresa "{empresa}" (CNPJ: {cnpj})
e extraia os indicadores financeiros dos **dois últimos exercícios** disponíveis.

Retorne APENAS um JSON válido, sem texto extra:
{{
  "anos": ["AAAA", "AAAA"],
  "dados": [
    {{
      "receitaBruta": <número inteiro em R$ ou null>,
      "receitaLiquida": <número inteiro em R$ ou null>,
      "lucroBruto": <número inteiro em R$ ou null>,
      "lucroLiquido": <número inteiro em R$ ou null>,
      "ebitda": <número inteiro em R$ ou null>,
      "ativoCirculante": <número inteiro em R$ ou null>,
      "realizavelLP": <número inteiro em R$ ou null>,
      "ativoTotal": <número inteiro em R$ ou null>,
      "passivoCirculante": <número inteiro em R$ ou null>,
      "exigivelLP": <número inteiro em R$ ou null>,
      "passivoTotal": <número inteiro em R$ ou null>,
      "patrimonioLiquido": <número inteiro em R$ ou null>,
      "dividaFinanceira": <número inteiro em R$ ou null>,
      "fco": <número inteiro em R$ ou null>,
      "fce": <número inteiro em R$ ou null>,
      "fci": <número inteiro em R$ ou null>,
      "fcf": <número inteiro em R$ ou null>
    }},
    {{ ...mesmo estrutura para o ano mais recente... }}
  ]
}}

Regras obrigatórias:
- Todos os valores em REAIS como inteiros (sem casas decimais, sem formatação)
- Índice 0 = exercício mais antigo, índice 1 = mais recente
- Campos não encontrados = null (não 0)
- EBITDA: se não explícito, calcule como LAJIDA (EBIT + Depreciação + Amortização)
- Dívida Financeira: empréstimos + financiamentos + debêntures (excluir fornecedores/impostos)
- FCO/FCI/FCF: extrair da DFC se disponível"""

    content.append({"type": "text", "text": prompt})

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": content}],
        extra_headers={"anthropic-beta": "pdfs-2024-09-25"},
    )

    extracted = _extract_json(resp.content[0].text)
    if not extracted:
        raise HTTPException(422, "Não foi possível extrair os dados financeiros dos documentos")

    return extracted


# ── Endpoints de análise ──────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    key = _load_key()
    return {"status": "ok", "version": "2.0.0", "ai_configured": bool(key) and key not in ("sua-chave-aqui", "")}


@app.post("/api/analyze")
@limiter.limit("30/minute")
async def analyze(request: Request, req: AnalyzeRequest, current_user=Depends(_get_current_user)):
    client = Anthropic(api_key=_load_key())

    # 1. Consulta Receita Federal
    receita = await fetch_receita(req.cnpj)

    # 2. Gera análise com Claude
    prompt = build_prompt(req, receita)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
    except Exception as exc:
        raise HTTPException(500, f"Erro ao chamar Claude API: {exc}")

    # 3. Extrai JSON com três estratégias em cascata
    analysis = _extract_json(raw)
    if analysis is None:
        analysis = {
            "score": 0,
            "classificacao": "—",
            "recomendacao": "revisar",
            "resumo_executivo": raw,
            "pontos_positivos": [],
            "pontos_atencao": [],
            "alertas_criticos": ["Erro ao processar resposta da IA — revise manualmente"],
            "fundamentacao": raw,
            "analise_cadastral": "",
            "analise_societaria": "",
            "analise_proporcionalidade": "",
            "analise_operacional": "",
            "limite_recomendado_exportador": "—",
            "limite_recomendado_desp": "—",
            "limite_recomendado_imp": "—",
            "exposicao_total_recomendada": "—",
            "prazo_recomendado": 30,
        }

    return {
        "cnpj_data": receita,
        "analysis": analysis,
        "bureau_fonte": "BrasilAPI / Receita Federal",
        "modelo_ia": "claude-sonnet-4-6",
    }


# ── CRUD Solicitações ────────────────────────────────────────────────────────

@app.get("/api/solicitacoes")
async def sol_list(current_user=Depends(_get_current_user)):
    rows = await _turso_query(
        "SELECT id, status, created_at, updated_at, created_by, data FROM solicitacoes ORDER BY created_at DESC"
    )
    items = []
    for row in rows:
        try:
            d = json.loads(row["data"] or "{}")
        except Exception:
            d = {}
        d["id"]        = row["id"]
        d["status"]    = row["status"]
        d["createdAt"] = row["created_at"]
        d["updatedAt"] = row["updated_at"]
        try:
            d["created_by"] = json.loads(row["created_by"] or "null")
        except Exception:
            pass
        if _record_visible_to(d, current_user):
            items.append(d)
    return {"items": items}


@app.post("/api/solicitacoes", status_code=201)
async def sol_create(request: Request, current_user=Depends(_get_current_user)):
    body       = await request.json()
    sol_id     = body.get("id") or str(uuid.uuid4())
    if not _SOL_ID_RE.match(sol_id):
        raise HTTPException(400, "ID inválido")
    status     = body.get("status", "pendente")
    created_at = body.get("createdAt") or datetime.utcnow().isoformat()
    updated_at = body.get("updatedAt") or created_at
    created_by = json.dumps({
        "id": current_user.get("sub"), "email": current_user.get("email"), "name": current_user.get("name")
    })
    body["id"]        = sol_id
    body["createdAt"] = created_at
    body["updatedAt"] = updated_at
    await _turso_exec(
        "INSERT OR REPLACE INTO solicitacoes (id, status, created_at, updated_at, created_by, data) VALUES (?,?,?,?,?,?)",
        [sol_id, status, created_at, updated_at, created_by, json.dumps(body, ensure_ascii=False)],
    )
    return {"ok": True, "id": sol_id}


@app.get("/api/solicitacoes/stats")
async def sol_stats(current_user=Depends(_get_current_user)):
    rows   = await _turso_query("SELECT status, COUNT(*) as cnt FROM solicitacoes GROUP BY status")
    counts = {"total": 0, "aprovado": 0, "negado": 0, "em_analise": 0, "pendente": 0, "em_comite": 0}
    for row in rows:
        st  = row["status"] or "pendente"
        cnt = int(row["cnt"] or 0)
        counts["total"] += cnt
        if st in counts:
            counts[st] = cnt
    return counts


@app.get("/api/solicitacoes/{sol_id}")
async def sol_get(sol_id: str, current_user=Depends(_get_current_user)):
    if not _SOL_ID_RE.match(sol_id):
        raise HTTPException(400, "ID inválido")
    rows = await _turso_query(
        "SELECT id, status, created_at, updated_at, created_by, data FROM solicitacoes WHERE id=?", [sol_id]
    )
    if not rows:
        raise HTTPException(404, "Solicitação não encontrada")
    row = rows[0]
    try:
        d = json.loads(row["data"] or "{}")
    except Exception:
        d = {}
    d["id"]        = row["id"]
    d["status"]    = row["status"]
    d["createdAt"] = row["created_at"]
    d["updatedAt"] = row["updated_at"]
    if not _record_visible_to(d, current_user):
        raise HTTPException(403, "Acesso negado")
    return d


@app.put("/api/solicitacoes/{sol_id}")
async def sol_update(sol_id: str, request: Request, current_user=Depends(_get_current_user)):
    if not _SOL_ID_RE.match(sol_id):
        raise HTTPException(400, "ID inválido")
    body       = await request.json()
    status     = body.get("status", "pendente")
    updated_at = body.get("updatedAt") or datetime.utcnow().isoformat()
    created_at = body.get("createdAt") or updated_at
    existing   = await _turso_query("SELECT created_by, created_at FROM solicitacoes WHERE id=?", [sol_id])
    if existing:
        created_by = existing[0]["created_by"]
        created_at = existing[0]["created_at"] or created_at
    else:
        created_by = json.dumps({
            "id": current_user.get("sub"), "email": current_user.get("email"), "name": current_user.get("name")
        })
    body["id"]        = sol_id
    body["updatedAt"] = updated_at
    await _turso_exec(
        "INSERT OR REPLACE INTO solicitacoes (id, status, created_at, updated_at, created_by, data) VALUES (?,?,?,?,?,?)",
        [sol_id, status, created_at, updated_at, created_by, json.dumps(body, ensure_ascii=False)],
    )
    return {"ok": True}


@app.delete("/api/solicitacoes/{sol_id}", status_code=204)
async def sol_delete(sol_id: str, current_user=Depends(_get_current_user)):
    if not _SOL_ID_RE.match(sol_id):
        raise HTTPException(400, "ID inválido")
    if not _user_can_decide(current_user):
        raise HTTPException(403, "Apenas analistas podem excluir solicitações")
    await _turso_exec("DELETE FROM solicitacoes WHERE id=?", [sol_id])
    from fastapi.responses import Response as _R
    return _R(status_code=204)


# ── Admin: Backup e Exportação ────────────────────────────────────────────────

def _build_backup_zip() -> io.BytesIO:
    """Comprime historico/ + docs/ + users.json num ZIP em memória."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(HISTORICO_DIR.glob("*.json")):
            zf.write(f, f"historico/{f.name}")
        for f in DOCS_DIR.rglob("*"):
            if f.is_file():
                zf.write(f, f"docs/{f.relative_to(DOCS_DIR)}")
        if _USERS_FILE.exists():
            zf.write(_USERS_FILE, "users.json")
        # Manifesto com metadados do backup
        manifest = {
            "gerado_em": datetime.now().isoformat(),
            "versao_api": "2.0.0",
            "total_analises": len(list(HISTORICO_DIR.glob("*.json"))),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf


@app.get("/api/admin/backup/download")
@limiter.limit("5/hour")
async def admin_backup_download(request: Request, current_user=Depends(_require_admin)):
    """Baixa um ZIP completo com todos os dados (historico, docs, usuários)."""
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    buf = _build_backup_zip()
    # Persiste cópia local na pasta backups/
    local_path = BACKUPS_DIR / f"backup_{ts}.zip"
    local_path.write_bytes(buf.read())
    buf.seek(0)
    # Rotação: mantém os 30 backups mais recentes em disco
    all_backups = sorted(BACKUPS_DIR.glob("backup_*.zip"))
    for old in all_backups[:-30]:
        old.unlink()
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=backup_vendemmia_{ts}.zip"},
    )


@app.get("/api/admin/backup/list")
async def admin_backup_list(current_user=Depends(_require_admin)):
    """Lista os backups armazenados localmente."""
    files = sorted(BACKUPS_DIR.glob("backup_*.zip"), reverse=True)
    return {
        "backups": [
            {
                "nome":       f.name,
                "tamanho_kb": round(f.stat().st_size / 1024, 1),
                "criado_em":  datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            }
            for f in files
        ]
    }


@app.get("/api/admin/export")
async def admin_export_json(current_user=Depends(_require_admin)):
    """Exporta todos os dados em formato normalizado para migração ao banco de dados.

    Retorna três coleções prontas para INSERT em tabelas SQL:
      - analises     → tabela principal (uma linha por análise)
      - decisoes     → decisões do analista (FK: analise_id)
      - documentos   → arquivos enviados (FK: sol_id)
    """
    analises, decisoes, documentos = [], [], []

    for f in sorted(HISTORICO_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        ai  = d.get("analise_ia")  or {}
        rf  = d.get("receita_federal") or {}
        ts  = d.get("timestamps") or {}
        cb  = d.get("created_by") or {}
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
                "analise_id":      d.get("id"),
                "status":          dec.get("status"),
                "limite_aprovado": dec.get("limiteAprovado"),
                "limite_desp":     dec.get("limiteDesp"),
                "limite_imp":      dec.get("limiteImp"),
                "prazo_aprovado":  dec.get("prazoAprovado"),
                "obs_analista":    dec.get("analistaObs"),
                "parecer_tecnico": dec.get("parecerTecnico"),
                "decisao_analista":dec.get("decisaoAnalista"),
                "decidido_em":     dec.get("decisao_at"),
            })

    for sol_dir in DOCS_DIR.iterdir():
        if not sol_dir.is_dir():
            continue
        for tipo_dir in sol_dir.iterdir():
            if not tipo_dir.is_dir():
                continue
            for arq in tipo_dir.iterdir():
                if arq.is_file():
                    documentos.append({
                        "sol_id":       sol_dir.name,
                        "tipo":         tipo_dir.name,
                        "nome_arquivo": arq.name,
                        "tamanho_bytes":arq.stat().st_size,
                        "path_relativo":str(arq.relative_to(DOCS_DIR)),
                    })

    return {
        "exportado_em": datetime.now().isoformat(),
        "totais": {
            "analises":   len(analises),
            "decisoes":   len(decisoes),
            "documentos": len(documentos),
        },
        "analises":   analises,
        "decisoes":   decisoes,
        "documentos": documentos,
    }


# Serve os arquivos HTML/JS/CSS estáticos na raiz
_static_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
