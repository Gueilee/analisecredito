#!/usr/bin/env python3
"""
PEREIRA Daemon — Análise de Crédito Vendemmia
Conecta a analisecredito.vendemmia.dev.br, busca jobs pendentes e executa via browser-use.

Auth: cookie-based (vd_token) — requests.Session gerencia automaticamente.
Todas as otimizações de custo já aplicadas:
  - claude-haiku-4-5-20251001 + flash_mode=True
  - use_vision=False + include_attributes mínimos (11 attrs)
  - prompt-caching beta + max_tokens=4096
"""

# ── PASSO 1: fix truststore ANTES de qualquer import que use SSL ──────────────
import sys, subprocess
from pathlib import Path as _Path
try:
    from pip._vendor import truststore as _pip_ts_early
    _pip_ts_early.extract_from_ssl()
except Exception:
    pass

# ── PASSO 2: verifica browser_use e relança com venv Python se necessário ─────
_SELF = _Path(__file__).resolve()
_VENV = _SELF.parent.parent / "venv" / "Scripts" / "python.exe"
try:
    import browser_use as _bu  # noqa
except (ImportError, Exception):
    if _VENV.exists() and _VENV.resolve() != _Path(sys.executable).resolve():
        print(f"[PEREIRA] Relançando com venv Python: {_VENV}")
        _proc = subprocess.Popen([str(_VENV), str(_SELF)], cwd=str(_SELF.parent))
        while True:
            try:
                sys.exit(_proc.wait())
            except KeyboardInterrupt:
                pass
    else:
        print("[PEREIRA] ERRO: browser_use não instalado. Execute:")
        print(f"          {_VENV} -m pip install browser-use")
        sys.exit(1)

import asyncio
import json
import os
import queue
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Python 3.14 + pip injeta truststore no ssl.SSLContext — restaura antes de qualquer SSL
try:
    from pip._vendor import truststore as _pip_ts
    _pip_ts.extract_from_ssl()
except Exception:
    pass
sys.modules.setdefault("truststore", None)  # type: ignore

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

ROOT         = Path(__file__).parent
MEMORIA_FILE = ROOT / "memoria" / "pereira.json"
BASE_URL     = os.getenv("ANALISE_URL", "https://analisecredito.vendemmia.dev.br")
API_KEY      = os.getenv("ANTHROPIC_API_KEY", "")

# ─── Auth via cookie (requests.Session gerencia vd_token automaticamente) ──────
_session = requests.Session()

def _login() -> bool:
    email = os.getenv("PEREIRA_EMAIL", "")
    pwd   = os.getenv("PEREIRA_PASSWORD", "")
    if not email or not pwd:
        print("[PEREIRA] ERRO: configure PEREIRA_EMAIL e PEREIRA_PASSWORD no .env")
        return False
    try:
        r = _session.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": pwd}, timeout=15)
        if r.status_code == 200:
            print("[PEREIRA] Login realizado — sessão válida por 8h.")
            return True
        print(f"[PEREIRA] Login falhou ({r.status_code}): {r.text[:120]}")
        return False
    except Exception as e:
        print(f"[PEREIRA] Erro no login: {e}")
        return False

# ─── Lock de instância única ──────────────────────────────────────────────────
_LOCK_FILE = ROOT / "pereira.lock"

def _pid_vivo(pid: int) -> bool:
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong(0)
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259

def _matar_pid(pid: int):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
    if handle:
        ctypes.windll.kernel32.TerminateProcess(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)

def _adquirir_lock():
    meu_pid = os.getpid()
    if _LOCK_FILE.exists():
        try:
            pid = int(_LOCK_FILE.read_text().strip())
            if pid != meu_pid and _pid_vivo(pid):
                print(f"[PEREIRA] Encerrando instância anterior (PID {pid})...")
                _matar_pid(pid)
                time.sleep(1.5)
        except Exception:
            pass
    try:
        _LOCK_FILE.write_text(str(meu_pid))
    except Exception:
        pass

_adquirir_lock()


# ─── Memória ──────────────────────────────────────────────────────────────────

def _load_memory() -> dict:
    if MEMORIA_FILE.exists():
        return json.loads(MEMORIA_FILE.read_text("utf-8"))
    return {"tarefas": {}, "log": []}

def _save_memory(d: dict):
    MEMORIA_FILE.parent.mkdir(exist_ok=True)
    MEMORIA_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")


# ─── HTTP helpers síncronos ───────────────────────────────────────────────────

def _api(path: str) -> str:
    return f"{BASE_URL}/api{path}"

def _get(path: str) -> requests.Response | None:
    try:
        r = _session.get(_api(path), timeout=10)
        if r.status_code == 401 and _login():
            r = _session.get(_api(path), timeout=10)
        return r
    except Exception as e:
        print(f"[PEREIRA] GET {path} falhou: {e}")
        return None

def _post(path: str, **kwargs) -> requests.Response | None:
    try:
        r = _session.post(_api(path), timeout=10, **kwargs)
        if r.status_code == 401 and _login():
            r = _session.post(_api(path), timeout=10, **kwargs)
        return r
    except Exception as e:
        print(f"[PEREIRA] POST {path} falhou: {e}")
        return None


# ─── Operações do daemon ──────────────────────────────────────────────────────

def _sincronizar_memoria():
    mem = _load_memory()
    for tid, t in mem.get("tarefas", {}).items():
        _post("/pereira/sync-task", json={
            "slug":      tid,
            "nome":      t.get("nome", tid),
            "descricao": t.get("descricao", ""),
            "passos":    t.get("passos", []),
            "url_inicial": t.get("url_inicial", ""),
        })

def _buscar_job() -> dict | None:
    r = _get("/pereira/pending")
    if r and r.status_code == 200 and r.json():
        return r.json()
    return None

def _reportar(job_id: int, status: str, resultado: str = ""):
    _post(f"/pereira/result/{job_id}", json={"status": status, "resultado": resultado})

def _heartbeat():
    _post("/pereira/heartbeat")


# ─── Executor de tarefas (async — browser-use exige) ─────────────────────────

async def _executar_job_async(job: dict) -> str:
    try:
        from browser_use import Agent
        from browser_use.browser.profile import BrowserProfile
        from browser_use.llm.anthropic.chat import ChatAnthropic
    except ImportError as e:
        return f"Dependência não instalada: {e}"

    if not API_KEY:
        return "ANTHROPIC_API_KEY não configurada"

    slug      = job.get("tarefa_slug", "")
    nome      = job.get("tarefa_nome", slug)
    passos_db = job.get("passos", [])
    url_ini   = job.get("url_inicial", "")

    mem    = _load_memory()
    passos = passos_db or mem.get("tarefas", {}).get(slug, {}).get("passos", [])

    passos_str = ""
    if passos:
        resumo = [p.split("—")[0].strip()[:80] for p in passos]
        passos_str = "\nPassos: " + " → ".join(f"{i+1}.{p}" for i, p in enumerate(resumo))

    dados_job = job.get("dados", {}) or {}
    dados_str = " | ".join(f"{k}={v}" for k, v in dados_job.items()) if dados_job else "Dados de teste"

    tarefa = (
        f"PEREIRA automação Vendemmia. Tarefa: {nome}."
        f"{f' URL: {url_ini}.' if url_ini else ''}"
        f"{passos_str}"
        f"\nDados: {dados_str}"
        f"\nIMPORTANTE: preencha os campos com os dados fornecidos acima. Campos sem dados: deixe como estão."
        f" NÃO clique em confirmar/salvar/enviar NEM em Fechar NEM em qualquer botão que finalize a ação — deixe a tela ABERTA e visível."
        f" Ao terminar de preencher, reporte o que preencheu e declare done."
    )

    print(f"\n[PEREIRA] Executando: {nome}")
    print(f"          Job ID: {job['id']}")

    # ── Configurações de custo mínimo (NÃO alterar sem autorização) ──────────
    _ATTRS_MINIMOS = [
        'type', 'id', 'name', 'role', 'value',
        'placeholder', 'aria-label', 'required',
        'disabled', 'selected', 'aria-expanded',
    ]

    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",        # mais barato disponível
        api_key=API_KEY,
        max_tokens=4096,                           # flash mode outputs são curtos
        betas=["prompt-caching-2024-07-31"],       # cacheia system prompt entre steps
    )
    profile = BrowserProfile(headless=False)
    agent   = Agent(
        task=tarefa,
        llm=llm,
        browser_profile=profile,
        enable_signal_handler=False,
        use_vision=False,                          # DOM texto em vez de screenshots
        max_steps=15,
        max_failures=3,
        flash_mode=True,                           # schema simplificado — compatível com Haiku 4.5
        include_attributes=_ATTRS_MINIMOS,         # 11 attrs em vez de 44 — DOM ~60% menor
    )

    from browser_use.browser.session import BrowserSession as _BS
    _orig_reset    = _BS.reset
    _delay_applied = [False]

    async def _reset_com_pausa(self, *args, **kwargs):
        force = kwargs.get('force', args[0] if args else False)
        if force and not _delay_applied[0]:
            _delay_applied[0] = True
            print("\n[PEREIRA] 🔍 Tarefa concluída — Chrome aberto para revisão.")
            print("          Feche o Chrome manualmente quando terminar. O daemon aguarda.")
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < 1800:
                await asyncio.sleep(5)
                try:
                    ctx     = getattr(self, 'context', None) or getattr(self, '_context', None)
                    browser = getattr(ctx, 'browser', None) if ctx else None
                    if browser and not browser.is_connected():
                        print("[PEREIRA] Chrome fechado — retomando.")
                        break
                except Exception:
                    break
        await _orig_reset(self)

    _BS.reset = _reset_com_pausa

    try:
        resultado = await agent.run()

        texto = None
        try:
            texto = resultado.final_result()
        except Exception:
            pass

        if not texto:
            all_results = getattr(resultado, 'all_results', [])
            for r in all_results:
                content = str(getattr(r, 'extracted_content', '') or '')
                if 'credit balance' in content.lower() or 'too low' in content.lower():
                    return "Erro: Créditos da API Anthropic esgotados. Acesse console.anthropic.com → Plans & Billing."
            errors = getattr(resultado, 'errors', [])
            if errors or (hasattr(resultado, 'is_done') and not resultado.is_done()):
                return "Erro: Agente não completou a tarefa — falhas consecutivas. Verifique o terminal."
            return "Erro: Tarefa finalizada sem resultado explícito do agente."

        mem = _load_memory()
        if slug in mem.get("tarefas", {}):
            mem["tarefas"][slug]["ultima_exec"] = datetime.now().isoformat()
            mem["tarefas"][slug]["total_exec"]  = mem["tarefas"][slug].get("total_exec", 0) + 1
            _save_memory(mem)
        return str(texto)[:1000]

    except Exception as e:
        traceback.print_exc()
        msg = str(e)
        if 'credit balance' in msg.lower() or 'too low' in msg.lower():
            return "Erro: Créditos da API Anthropic esgotados. Acesse console.anthropic.com → Plans & Billing."
        return f"Erro: {e}"
    finally:
        _BS.reset = _orig_reset


_job_queue:    queue.Queue = queue.Queue(maxsize=1)
_result_queue: queue.Queue = queue.Queue(maxsize=1)

def _executar_job(job: dict) -> str:
    _job_queue.put(job)
    return _result_queue.get()

_stop_event = threading.Event()


def _polling_worker():
    last_heartbeat = 0.0

    if not _login():
        print("[PEREIRA] ERRO: não foi possível autenticar. Verifique PEREIRA_EMAIL e PEREIRA_PASSWORD no .env")
        _stop_event.set()
        return

    try:
        _sincronizar_memoria()
        print("[PEREIRA] Memória sincronizada com o sistema.")
    except Exception as e:
        print(f"[PEREIRA] Aviso: falha ao sincronizar memória ({e}) — continuando.")

    while not _stop_event.is_set():
        try:
            now = time.time()

            if now - last_heartbeat >= 60:
                _heartbeat()
                last_heartbeat = now

            job = _buscar_job()
            if job:
                print(f"[PEREIRA] Job recebido: {job['tarefa_nome']} (#{job['id']})")
                _reportar(job["id"], "executando")
                resultado = _executar_job(job)
                status = "erro" if resultado.startswith(("Erro:", "Dependência", "ANTHROPIC")) else "sucesso"
                _reportar(job["id"], status, resultado)
                print(f"[PEREIRA] Job #{job['id']} — {status}: {resultado[:80]}")
            else:
                _stop_event.wait(5)

        except Exception as e:
            print(f"[PEREIRA] Erro no polling: {e}")
            traceback.print_exc()
            _stop_event.wait(5)


def main():
    print("\n" + "━"*60)
    print("  PEREIRA Daemon v1.0 — Análise de Crédito")
    print(f"  Conectando a: {BASE_URL}")
    print(f"  Iniciado em:  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("━"*60)
    print("  Aguardando comandos do sistema. Ctrl+C 3× para encerrar.\n")

    t = threading.Thread(target=_polling_worker, name="pereira-poll", daemon=True)
    t.start()

    import signal
    _quit     = threading.Event()
    _ki_times: list[float] = []

    def _sigint_handler(sig, frame):
        now = time.time()
        _ki_times[:] = [ts for ts in _ki_times if now - ts < 3]
        _ki_times.append(now)
        if len(_ki_times) >= 3:
            print("\n[PEREIRA] Ctrl+C confirmado — encerrando.")
            _quit.set()
            _stop_event.set()

    signal.signal(signal.SIGINT, _sigint_handler)

    while not _quit.is_set() and t.is_alive():
        try:
            job = _job_queue.get(timeout=0.5)
            try:
                resultado = asyncio.run(_executar_job_async(job))
            except Exception as e:
                traceback.print_exc()
                resultado = f"Erro: {e}"
            _result_queue.put(str(resultado)[:500] if resultado else "Concluído")
        except queue.Empty:
            pass

    _stop_event.set()
    t.join(timeout=10)
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    print("[PEREIRA] Daemon encerrado.")


if __name__ == "__main__":
    main()
