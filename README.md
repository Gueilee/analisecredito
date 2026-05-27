# 💳 Vendemmia — Análise de Crédito

Este projeto é uma plataforma para análise e concessão de crédito para clientes importadores, utilizando FastAPI no backend, integração com a Receita Federal (via BrasilAPI), inteligência artificial com Claude AI (Anthropic) e persistência de dados em banco de dados Turso (libSQL).

O backend em FastAPI também serve os arquivos estáticos (HTML/CSS/JS) da interface do usuário de forma integrada.

---

## 🚀 Como Rodar o Projeto Localmente

Siga o passo a passo abaixo para configurar e iniciar o projeto na sua máquina.

### 📋 Pré-requisitos

Antes de começar, você precisará ter instalado:
* **Python 3.11+**
* Uma conta/banco criado no **[Turso (libSQL)](https://turso.tech)** (banco de dados em nuvem leve e rápido)
* Uma chave de API da **[Anthropic](https://console.anthropic.com)** (Claude AI)

---

### ⚙️ Configuração Passo a Passo

#### 1. Criar Ambiente Virtual e Instalar Dependências
Navegue até a pasta `api`, crie um ambiente virtual (`venv`) para evitar conflitos de pacotes globais no Ubuntu (erro `externally-managed-environment`), ative-o e instale as dependências:
```bash
cd api

# Cria o ambiente virtual
python3 -m venv venv

# Ativa o ambiente virtual
source venv/bin/activate

# Instala as dependências
pip install -r requirements.txt
```

#### 2. Configurar as Variáveis de Ambiente
Copie o arquivo de exemplo de ambiente `.env.example` para `.env` dentro da pasta `api`:
```bash
cp .env.example .env
```
Abra o arquivo `api/.env` e configure as seguintes variáveis essenciais:
* `ANTHROPIC_API_KEY`: Insira sua chave da API Anthropic.
* `APP_SECRET_KEY`: Gere uma chave secreta segura de 64 caracteres hexadecimais rodando o comando:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
* `TURSO_URL` e `TURSO_TOKEN`: Insira a URL de conexão e o token do seu banco de dados criado no Turso.
* `SMTP_USER`, `SMTP_PASS` e `NOTIFY_EMAILS`: Opcional, para notificações por e-mail das análises de crédito.

#### 3. Executar o Schema no Banco de Dados (Turso)
O banco de dados utiliza a estrutura definida no arquivo `api/schema.sql`. Execute o schema no seu banco de dados Turso usando a CLI do Turso ou o dashboard:
```bash
turso db shell <nome-do-seu-banco> < schema.sql
```
> **Nota:** Conforme a regra de desenvolvimento, a execução de migrações e comandos no banco de dados deve ser executada de forma manual por você.

#### 4. Criar Usuários no Sistema
Para acessar a plataforma, você precisa de uma conta de usuário cadastrada localmente no arquivo de segurança `api/users.json`. O projeto fornece uma ferramenta CLI interativa para criar usuários (garanta que o ambiente virtual `venv` está ativo):
```bash
python3 create_user.py
```
Selecione a opção `[1] Adicionar / atualizar usuário` e preencha:
* **Nome completo**
* **E-mail** (deve terminar com `@vendemmia.com.br`)
* **Papel (Role)**: Escolha entre as opções (ex: `Financeiro` ou `Administrador` para acesso total, ou `Operações` para acesso restrito)
* **Senha**

---

### 🖥️ Iniciando o Servidor

Com tudo configurado e com o ambiente virtual `venv` ativo, inicie o servidor FastAPI usando o Uvicorn a partir do diretório `api`:
```bash
# Se o venv não estiver ativo, ative-o primeiro:
# source venv/bin/activate

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Após iniciar, acesse o sistema no seu navegador:
👉 **[http://localhost:8000](http://localhost:8000)** (será redirecionado automaticamente para a interface do frontend)

---

## 📁 Estrutura de Pastas Principal

* `api/`: Código-fonte do backend FastAPI.
  * `main.py`: Ponto de entrada do backend contendo as rotas, middlewares, integração com Claude AI e queries.
  * `schema.sql`: Definição da estrutura das tabelas do banco de dados Turso.
  * `create_user.py`: Utilitário para adicionar/listar/remover usuários.
  * `users.json`: Arquivo gerado que armazena os hashes das credenciais locais (ignorado no Git).
* `./`: Diretório raiz que contém os arquivos estáticos de frontend (HTML/CSS/JS) servidos pelo FastAPI.
  * `index.html`: Dashboard principal.
  * `db.js`: Ponte de cache/sincronização síncrona com `localStorage` e a API.
  * `components.js`: Componentes reutilizáveis da UI.
  * `shared.css`: Estilização global e componentes CSS.
