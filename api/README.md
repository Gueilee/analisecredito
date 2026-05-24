# Vendemmia Credit API — Setup

## Pré-requisitos
- Python 3.11+
- Chave de API da Anthropic (https://console.anthropic.com)

## Instalação

```bash
# 1. Instalar dependências
cd api
pip install -r requirements.txt

# 2. Configurar variáveis de ambiente
cp .env.example .env
# Edite .env e insira sua ANTHROPIC_API_KEY

# 3. Iniciar o servidor
uvicorn main:app --reload
```

O servidor estará disponível em **http://localhost:8000**

## Acessar o sistema

Depois de iniciar o servidor, acesse o sistema via:
```
http://localhost:8000/index.html
```

> Usar o servidor evita problemas de CORS do protocolo `file://`.

## Endpoints

| Método | Rota           | Descrição                                  |
|--------|---------------|--------------------------------------------|
| GET    | /api/health   | Status do servidor                         |
| POST   | /api/analyze  | Analisa um CNPJ + dados da solicitação     |

## Integrações futuras

| Bureau          | Status       | Como ativar                                      |
|-----------------|-------------|--------------------------------------------------|
| BrasilAPI (RF)  | ✅ Ativo     | Gratuito, sem configuração                       |
| Serasa Experian | 🔜 Em breve  | Adicionar `SERASA_CLIENT_ID` + `SERASA_SECRET`   |
| BigDataCorp     | 🔜 Em breve  | Adicionar `BIGDATA_TOKEN`                        |

## Produção (Fase 3)

```
FastAPI  →  PostgreSQL (Supabase)  →  JWT Auth  →  Multi-tenant
```

Basta substituir as chamadas `localStorage` em `db.js` por `fetch('/api/...')`.
