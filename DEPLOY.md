# Deploy — Análise de Crédito Vendemmia

## Configuração inicial (obrigatório antes de subir)

### 1. Configurar variáveis de ambiente
```bash
cd api
cp .env.example .env
# Edite .env com sua ANTHROPIC_API_KEY e uma APP_SECRET_KEY aleatória
```

### 2. Instalar dependências
```bash
cd api
pip install -r requirements.txt
```

### 3. Criar usuários do sistema
```bash
cd api
python create_user.py
# Siga as instruções para adicionar cada usuário com senha segura
```

### 4. Iniciar o servidor
```bash
cd api
uvicorn main:app --host 0.0.0.0 --port 8000
```
Acesse: http://localhost:8000

---

## Deploy em produção (Railway / Render / Fly.io)

### Railway (recomendado)
1. Conecte o repositório GitHub no dashboard do Railway
2. Configure as variáveis de ambiente:
   - `ANTHROPIC_API_KEY` — sua chave Anthropic
   - `APP_SECRET_KEY` — string aleatória (32+ chars)
   - `ALLOWED_ORIGINS` — URL do deploy (ex: `https://seu-app.railway.app`)
   - `HTTPS_ONLY` — `true`
   - `SESSION_HOURS` — `8`
3. No Railway, defina o **Root Directory** como `api/`
4. O **Start Command** será detectado automaticamente via `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Após o deploy, acesse a URL e faça upload do `users.json` via Railway shell:
   ```bash
   python create_user.py
   ```

### Variáveis obrigatórias em produção
| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Chave da API Anthropic |
| `APP_SECRET_KEY` | Chave secreta para JWT (min. 32 chars) |
| `ALLOWED_ORIGINS` | URL do frontend |
| `HTTPS_ONLY` | `true` |

---

## Segurança implementada

- ✅ JWT em cookie httpOnly (não acessível por JavaScript)
- ✅ Rate limiting (10 req/min no login, 60 req/min nas APIs)
- ✅ Security headers (X-Frame-Options, CSP, HSTS, etc.)
- ✅ CORS restrito a origens configuradas
- ✅ Senhas com bcrypt (fator 12)
- ✅ Sessão expira automaticamente
- ✅ Dados de clientes fora do repositório (.gitignore)
- ✅ Chaves de API fora do código-fonte

---

## Arquivos sensíveis (nunca commitar)
- `api/.env` — chaves de API
- `api/users.json` — usuários e senhas hashed
- `api/historico/` — análises de clientes
- `api/docs/` — documentos financeiros
- `Arquivos/` — PDFs de clientes
