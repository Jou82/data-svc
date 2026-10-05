# Arquitetura — data-svc

Este documento complementa o [README.md](../README.md) (setup local, cache L1, contribuição) com:
papel do serviço no ecossistema MEIrelles, variáveis de ambiente completas, inventário de todos
os endpoints Flask, e os módulos centrais (cache em dois níveis, RAG dual-backend).

---

## 1. O que é e qual o papel no sistema

O `data-svc` é o microserviço Flask (Python 3.12) que centraliza todo o acesso ao Postgres
(Supabase) da MEIrelles. Os workflows n8n (Orbit, Financeiro MEI/PL, Livro Caixa, Comunidade,
Agenda etc.) não têm mais nós Postgres diretos — eles chamam o `data-svc` via HTTP, autenticado
por API key, e o serviço faz a query, aplica cache e devolve JSON já pronto para o agente de IA
ou para lógica de roteamento no workflow.

```
N8N (Orbit, Financeiro MEI/PL, Livro Caixa, Comunidade, Agenda, ...)
        │  HTTP + X-Api-Key
        ▼
     data-svc (Flask)
        │              ↑ L1 TTLCache in-process
        │              ↑ L2 Upstash Redis (REST, prefixo stg:/prd:)
        ▼
   Supabase Postgres (STG ou PRD — dois projetos separados)
        │
        ▼ (rota /rag/busca)
   pgvector (tabela documents) OU Upstash Vector (RAG_BACKEND)
```

Outros microserviços do ecossistema (`relatorios-svc`, `dicas-svc`, `monitor-svc`, em Node.js)
são serviços irmãos, não clientes do `data-svc` — eles acessam o Postgres por conta própria ou
expõem suas próprias rotas. O `data-svc` é especificamente a camada de dados usada pelos
workflows n8n e pelos agentes de IA.

Rede: o serviço roda na VPS Hostinger (Easypanel) **sem domínio público nem porta exposta ao
host** — só é alcançável pela rede Docker interna, no endereço `http://data-svc:5000`. A defesa
em profundidade é o header `X-Api-Key` (obrigatório em produção; ausente = auth desativada, só
aceitável em dev local).

---

## 2. Rodando localmente

Resumo — para o passo a passo completo (virtualenv, `docker-compose.yml`, seed do banco), ver o
[README.md](../README.md).

- **Runtime:** Python 3.12, Flask 3, Gunicorn (produção usa `--workers=1` de propósito — ver
  comentário no `Dockerfile`: o cache L1 é em memória por processo, 2+ workers quebram
  invalidação).
- **Dependências:** `pip install -r requirements.txt` (flask, gunicorn, psycopg2-binary,
  cachetools, python-dotenv, openai, pytest/pytest-mock).
- **Banco:** Postgres local via `docker compose up db -d` (schema/seed em `scripts/init.sql` e
  `scripts/seed.sql`), ou apontar `DATABASE_URL` para o Supabase de STG (nunca PRD para dev).
- **Start:** `flask --app src/app run --port 5001 --debug` (ou `docker build` + `docker run`,
  ver README).
- **Testes:** `pytest` (suíte em `tests/`).

### Variáveis de ambiente (`.env.example`)

| Variável | Obrigatória | Default | Papel |
|---|---|---|---|
| `DATABASE_URL` | sim | — | connection string Postgres (Supabase STG ou PRD) |
| `PORT` | não | `5000` | porta do Flask/Gunicorn |
| `FLASK_ENV` | não | `production` | se `production` e `API_KEY` ausente, o boot falha (`Config.validate()`) |
| `API_KEY` | em produção | — | valor exigido no header `X-Api-Key`; vazio = auth desativada (dev) |
| `OPENAI_API_KEY` | para LLM opcional | — | fallback de `EMBEDDINGS_API_KEY` se esta faltar |
| `OPENAI_BASE_URL` | não | — | override de base URL para chamadas de LLM (não afeta embeddings) |
| `EMBEDDINGS_API_KEY` | para `/rag/busca` | herda `OPENAI_API_KEY` | sempre OpenAI real — 1536 dims fixos no schema; Gemini não serve para embeddings |
| `EMBEDDING_MODEL` | não | `text-embedding-3-small` | modelo de embedding |
| `RAG_MATCH_THRESHOLD` | não | `0.4` | corte de similaridade cosseno em `/rag/busca` (0.7 zera resultado com este modelo — não usar) |
| `RAG_MATCH_COUNT` | não | `5` | quantidade de chunks retornados |
| `TYPESAFE_API_KEY` | para filtro RAG | — | key Jev; vazia = TypeSafe RAG score nunca roda |
| `TYPESAFE_MODEL` | não | `jev-latest` | modelo System One |
| `TYPESAFE_RAG_SCORE` | não | `0` | `1` liga Nouls por chunk após embedding (lab); fail-open se erro. **Não ligar em prod** até smoke |
| `TYPESAFE_RAG_RELEVANT_MIN` / `_EVIDENCE_MIN` / `_INJECTION_MAX` | não | `0.45` / `0.55` / `0.70` | limiares do filtro (`src/typesafe/rag_passages.py`) |
| `RAG_BACKEND` | não | `pgvector` | `pgvector` = tabela `documents` no Supabase; `upstash` = índice Upstash Vector. Qualquer outro valor cai em pgvector **silenciosamente**. Lido só no import — mudar exige restart |
| `UPSTASH_VECTOR_REST_URL` / `_TOKEN` | se `RAG_BACKEND=upstash` | — | índice Upstash Vector (compartilhado STG+PRD, free tier = 1 índice só) |
| `UPSTASH_REDIS_REST_URL` / `_TOKEN` | não | — | cache L2 distribuído; vazio = desativado (no-op, fail-open) |
| `CACHE_ENV_PREFIX` | não | vazio | `stg` / `prd` — isola chaves na mesma DB Redis compartilhada |
| `REDIS_TTL_USER` | não | `600` | TTL L2 do contexto de usuário |
| `REDIS_TTL_RAG` | não | `3600` | TTL L2 do resultado de busca vetorial |
| `REDIS_TTL_MEMORIA` | não | `43200` | TTL L2 da janela quente de `chat_memory` (12h) |
| `DEDUP_TTL` | não | `60` | janela de deduplicação de mensagem (guarda de alto nível em `redis_cache.py`) |
| `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` | não | `30` / `60` | rate limit por telefone (guarda de alto nível) |
| `CACHE_TTL_USUARIO`, `CACHE_TTL_SALDO`, `CACHE_TTL_COMPROVANTES`, `CACHE_TTL_AGENDAMENTOS`, `CACHE_TTL_LISTAS`, `CACHE_TTL_FEEDBACKS`, `CACHE_TTL_CONTEXTO_BUSINESS` | não | ver `.env.example` | TTLs do cache L1 (`cachetools.TTLCache`), por namespace |

Dependências externas: **Supabase Postgres** (STG e PRD são projetos separados — nunca deixar o
cliente resolver qual usar por fallback), **Upstash Redis** (cache L2, REST, fail-open) e,
opcionalmente, **Upstash Vector** (RAG, quando `RAG_BACKEND=upstash`).

---

## 3. Inventário de endpoints

Todas as rotas exigem o header `X-Api-Key` quando `API_KEY` está configurada (ver `src/app.py`,
`before_request`). Prefixo comum: a maioria das rotas de domínio vive sob `/usuarios/<id>/...`.

### `usuarios` — `src/routes/usuarios.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios` | Busca usuário por telefone (cache L1+L2) | query `telefone` |
| POST | `/usuarios` | Cria/upsert usuário | body `{numero_telefone, nome?, razao_social?}` |
| PUT | `/usuarios/<id>` | Atualiza campos permitidos (lista fixa: nome, estado_atual, onboarding, perfil fiscal, etc.) | body com subconjunto de `allowed_fields` |
| POST | `/usuarios/<id>/resetar-demo` | Reseta dados de demonstração do usuário | — |
| GET | `/usuarios/<id>/notificacoes` | Lê preferências de notificação | — |
| PUT | `/usuarios/<id>/notificacoes` | Upsert de preferências `{tipo: bool}` | body plano, chaves só de `NOTIF_TIPOS` |
| GET | `/usuarios/<id>/prox-nfe` | Próxima nota fiscal a emitir | — |
| GET | `/usuarios/<id>/clientes-nf` | Lista clientes cadastrados para NF | — |
| POST | `/usuarios/<id>/clientes-nf` | Cadastra cliente para NF | body `{nome, cnpj, email?}` |
| GET | `/usuarios/<id>/cobranca-pendente` | Cobrança pendente do usuário (`{}` se não houver, não 404) | — |

### `comprovantes` — `src/routes/comprovantes.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/saldo` | Saldo do mês (vendas − gastos) | query `mes` OU `data_inicio`+`data_fim` |
| GET | `/usuarios/<id>/comprovantes` | Lista comprovantes | query `modo`, `mes` OU `data_inicio`+`data_fim` |
| POST | `/usuarios/<id>/comprovantes` | Cria comprovante (idempotente via `item_hash`) | body validado por `validate_comprovante_payload` |
| GET | `/usuarios/<id>/comprovantes/ultimo` | Último comprovante lançado | — |
| PATCH | `/usuarios/<id>/comprovantes/ultimo` | Corrige último comprovante | body `{valor_total?, item?, comprovante_id?}` |
| DELETE | `/usuarios/<id>/comprovantes/ultimo` | Remove último comprovante (ou um específico) | body `{comprovante_id?}` |
| GET | `/usuarios/<id>/livro-caixa` | Livro caixa mensal (totais) | query `mes` |
| GET | `/usuarios/<id>/livro-caixa/pdf` | PDF Livro Caixa PL (base64 p/ Z-API) | query `mes`, `parcial` |

### `agendamentos` — `src/routes/agendamentos.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/agendamentos` | Lista agendamentos | query `scope` |
| GET | `/usuarios/<id>/agendamentos/conflitos` | Checa conflito de horário | query `data`, `hora`, `nome_compromisso` |
| POST | `/usuarios/<id>/agendamentos` | Cria agendamento | body validado por `validate_agendamento_payload` |
| POST | `/usuarios/<id>/agendamentos/recorrentes` | Cria série recorrente (gera datas em `recurrence_generator`) | body `{data_inicio, frequencia, dia_semana_ou_mes, quantidade_meses, nome_compromisso, hora_compromisso}` |
| PUT | `/usuarios/<id>/agendamentos/<agendamento_id>` | Atualiza agendamento | body validado por `validate_update_agendamento_payload` |
| DELETE | `/usuarios/<id>/agendamentos` | Cancela todos os agendamentos do usuário | — |
| DELETE | `/usuarios/<id>/agendamentos/recorrencia/<recorrencia_id>` | Cancela uma série recorrente | — |

### `lembretes` — `src/routes/lembretes.py` (cron n8n)

| Método | Path | Propósito | Params / body |
|--------|------|-----------|----------------|
| GET | `/lembretes/due` | Agendamentos na janela de lembrete (TZ `America/Sao_Paulo`, default ±2 min) | query `window_minutes` (0–10, default 2) |
| POST | `/lembretes/<agendamento_id>/enviado` | Marca `lembrete_enviado=true` após Z-API ok (idempotente) | — |

Auth: header `X-API-Key` (mesmo contrato das demais rotas internas). Retry: `run_db_with_retry` (3 tentativas, backoff) em falha `OperationalError`.

### `listas` — `src/routes/listas.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/listas` | Lista as listas de compras do usuário | — |
| GET | `/usuarios/<id>/listas/<lista_id>/itens` | Lista os itens de uma lista | — |
| POST | `/usuarios/<id>/listas/<lista_id>/itens` | Upsert de itens | body validado por `validate_lista_itens_payload` |
| DELETE | `/usuarios/<id>/listas/<lista_id>/itens` | Remove itens por nome | body validado por `validate_lista_delete_itens_payload` |

### `contas-recorrentes` — `src/routes/contas.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/contas-recorrentes` | Lista contas recorrentes do usuário | — |
| POST | `/usuarios/<id>/contas-recorrentes` | Upsert de conta recorrente | body validado por `validate_conta_recorrente_payload` |
| PATCH | `/usuarios/<id>/contas-recorrentes/<conta_id>` | Atualiza campos de uma conta | body validado por `validate_patch_conta_payload` |

> `contas_recorrentes` não tem vigência histórica — `ativo=true` reflete o estado de hoje, só o
> mês de referência pode ser reconciliado com o histórico (ver `CLAUDE.md` do repo `meire`).

### `agente` — `src/routes/agente.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/agente/persona` | Devolve o texto de persona do agente (cache L1, TTL 3600s) | — |

### `memoria` — `src/routes/memoria.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/memoria` | Janela de memória de chat (12h) | query `limit` (default 50) |
| POST | `/usuarios/<id>/memoria` | Insere turno de conversa | body `{session_id, role, content}`, `role` ∈ {user, assistant, system} |

### `rag` — `src/routes/rag.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| POST | `/rag/busca` | Busca semântica na base de conhecimento | body `{pergunta, match_count?, match_threshold?, perfil?}` ou `{metadata_filter: {perfil: [...]}}` |

Ver seção 4.2 para o funcionamento interno (dual backend, cache, normalização de texto).

### `cache` — `src/routes/cache.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| POST | `/cache/invalidate` | Invalida cache L1+L2 de usuário(s) — usado quando um write não passou pelo `data-svc` (SQL manual, reset em lote, job externo) | body `{telefones?: [...], usuario_ids?: [...]}` (máx. 500 alvos) |

### `feedbacks` — `src/routes/feedbacks.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| POST | `/feedbacks` | Registra feedback de um agente sobre um usuário | body `{usuario_id, texto, classificacao?}` |
| GET | `/usuarios/<id>/feedbacks` | Lista feedbacks paginados | query `limit`, `offset` |
| GET | `/usuarios/<id>/feedbacks/<feedback_id>` | Feedback individual | — |
| PUT | `/usuarios/<id>/feedbacks/<feedback_id>` | Atualiza resolução do feedback | body `{resolvido?, acao_tomada?, classificacao?}` |
| GET | `/feedbacks/resumo/<mes_referencia>` | Resumo mensal (formato `YYYY-MM`) | — |
| POST | `/feedbacks/resumo` | Persiste resumo mensal consolidado | body `{mes_referencia, ...}` |

### `business` — `src/routes/business.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/usuarios/<id>/contexto-business` | Agrega perfil, flags e dados financeiros (semana/mês/histórico/faturamento) para injetar no prompt do agente | — |
| POST | `/usuarios/<id>/meicheck-logs` | Registra log do fluxo "MEIcheck" | body livre + `usuario_id` |

### `oauth` — `src/routes/oauth.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/oauth/health` | Healthcheck de conexão com o banco | — |
| POST | `/oauth/refresh` | Renova access_token OAuth do usuário (Google) — **TODO**: chamada real ao endpoint OAuth2 ainda não implementada, hoje gera token fictício | header `X-User-ID` obrigatório |
| POST | `/oauth/revoke` | Revoga token (soft delete) | header `X-User-ID` obrigatório |
| GET | `/oauth/status` | Status do token OAuth do usuário | header `X-User-ID` obrigatório |

### `comunidade` — `src/routes/comunidade.py`

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| GET | `/comunidade/profissionais/ranking` | Ranking de profissionais da rede Comunidade | query validada por `validate_ranking_params` |
| GET | `/comunidade/bairros` | Resolve bairro por nome exato ou varredura de texto (cache L1, TTL 3600s, não cacheia miss) | query `nome` ou `texto` |
| GET | `/comunidade/conexoes` | Histórico de conexões do solicitante (sem cache) | query `solicitante_id` |
| GET | `/comunidade/conexoes/pendente` | Conexão aguardando resposta do indicado, por telefone (sem cache — consentimento duplo) | query `telefone` |
| PATCH | `/comunidade/conexoes/<conexao_id>/resposta` | Registra resposta na transição de consentimento (etapa 1 = solicitante, etapa 2 = profissional) | body `{etapa, resposta, conectar?}` |
| POST | `/comunidade/conexoes/cancelar` | Cancela conexões em aberto de um solicitante (lote) | body `{solicitante_id, conexao_id}` |

### `inbox` — `src/routes/inbox.py`

Suporte a um inbox multiusuário (contas, contatos, conversas, mensagens).

| Método | Path | Propósito | Body/params |
|---|---|---|---|
| POST | `/inbox/accounts` | Cria conta de canal (ex: número de WhatsApp) | body `{phone_number, ...}` |
| GET | `/inbox/accounts/by-phone/<phone>` | Busca conta pelo número | — |
| GET | `/inbox/accounts/<account_id>/conversations` | Lista conversas de uma conta | query `status?` |
| POST | `/inbox/accounts/<account_id>/contacts` | Upsert de contato | body `{phone_number, ...}` |
| POST | `/inbox/conversations` | Abre (ou retorna) a conversa aberta de um contato — idempotente | body `{account_id, contact_id}` |
| GET | `/inbox/conversations/<conversation_id>/messages` | Lista mensagens da conversa | query `limit` (máx. 200), `before_id?` |
| POST | `/inbox/messages` | Cria mensagem | body `{conversation_id, sender_type: user\|contact, sender_id?}` |

---

## 4. Módulos centrais

### 4.1 Cache em dois níveis

- **L1 — `src/cache.py`.** `cachetools.TTLCache` em memória, por processo, organizado em
  namespaces (`usuario`, `saldo`, `comprovantes`, `agendamentos`, `listas`, `feedbacks`,
  `contexto_business`, `agente`, `memoria`, `comunidade_bairro`...). Funções: `cache_get`,
  `cache_set`, `cache_invalidate` (chave específica ou namespace inteiro) e
  `cache_invalidate_prefix` (invalida por prefixo de chave, usado quando a chave inclui
  parâmetros variáveis como mês/intervalo). Por não ser compartilhado entre processos, o
  Gunicorn em produção roda com `--workers=1` — 2+ workers fariam um POST invalidar só o
  cache do worker que o atendeu.
- **L2 — `src/redis_cache.py`.** Cache distribuído sobre a REST API do Upstash Redis (sem
  dependência de cliente/pool — usa `urllib` puro). **Fail-open**: qualquer falha (rede, 5xx,
  timeout, credencial ausente) degrada para miss/None e o caller cai no Postgres; nenhum
  estado de FSM depende deste cache. Chaves recebem prefixo de ambiente (`CACHE_ENV_PREFIX`:
  `stg:`/`prd:`) para que uma única DB Upstash free sirva STG e PRD sem colisão. Além do
  cache simples (`cache_get`/`cache_set`/`cache_del`/`cache_setnx`/`cache_incr`), expõe duas
  guardas de alto nível: `dedup_is_duplicate` (deduplicação de mensagem via `SETNX`) e
  `rate_limit_exceeded` (rate limit por telefone via `INCR`+`EXPIRE`), ambas fail-open.
- Hoje só a entidade `usuario` tem os dois níveis ligados de fato (é a única com escritor
  externo medido — ver rota `POST /cache/invalidate`); os demais namespaces são L1-only com
  TTL curto.

### 4.2 RAG — `/rag/busca`, `src/queries/rag.py`, `src/vector.py`

A rota `POST /rag/busca` (`src/routes/rag.py`) implementa busca semântica na base de
conhecimento com um backend duplo, escolhido por `RAG_BACKEND`:

1. **Normalização.** A pergunta passa por `normalizar_busca` (`src/utils/texto.py`) antes do
   embedding — remove acentuação para casar com o acervo indexado, que passa pela mesma função
   no momento da escrita. As duas pontas têm que compartilhar literalmente a função, não só a
   intenção.
2. **Cache.** Chave é um hash SHA-256 de `pergunta normalizada + match_count + match_threshold +
   perfil + backend` — o backend entra na chave de propósito, senão o resultado de um backend
   ficaria servido por até `REDIS_TTL_RAG` (3600s) depois de trocar a flag, mascarando um A/B.
   Cache hit devolve direto do L2 (Upstash Redis), sem gastar embedding.
3. **Embedding.** Sempre via OpenAI real (`EMBEDDINGS_API_KEY`), independente de
   `OPENAI_BASE_URL` — o compat layer usado para chamadas de LLM não serve embeddings.
4. **Backend vetorial:**
   - `pgvector` (default) — `src/queries/rag.py::busca_semantica`, consulta a tabela
     `documents` no Supabase.
   - `upstash` — `src/vector.py::busca_semantica`, consulta o índice Upstash Vector
     (namespace por perfil: `mei`/`pl`/`autonomo`; perfil é obrigatório neste caminho,
     diferente do pgvector, porque não existe namespace "tudo"). Duas correções aplicadas
     sobre o resultado cru da Upstash: reescala o score `(1+cos)/2 → cos` (senão o filtro de
     threshold aceitaria quase tudo) e faz over-fetch (`topK = count × 20`) porque a busca é
     aproximada (HNSW) e `topK` baixo perde o vizinho verdadeiro. Falha aqui levanta
     (`VectorIndisponivel`) em vez de devolver lista vazia — a rota decide degradar para
     pgvector, e sempre loga (`[rag] upstash ok: ...` ou `[rag] upstash indisponivel, caindo no
     pgvector: ...`), porque um 200 vazio silencioso pareceria "índice saudável, sem
     resultado" quando na verdade é "backend fora do ar".
   - Qualquer valor de `RAG_BACKEND` diferente de `upstash` cai em pgvector silenciosamente —
     não há terceiro caminho nem erro de configuração explícito.
5. `perfil` pode chegar tanto em `body.perfil` quanto em `body.metadata_filter.perfil` (formato
   que os workflows n8n efetivamente mandam); ambos passam pelo mesmo mapa
   `profissional_liberal|pl → pl`, `mei → mei`, `autonomo → autonomo`. Entrada não reconhecida
   vira "sem filtro" (pgvector) ou dispara `VectorIndisponivel` (Upstash) — nunca 500.

### 4.3 Outros módulos

- **`src/db.py`** — pool de conexões `psycopg2` + context manager `get_db_conn()`, usado por
  toda rota que precisa do Postgres.
- **`src/config.py`** — carrega e valida env vars (`Config.validate()` roda no import; falha
  rápido se `DATABASE_URL` faltar, ou se `API_KEY` faltar em `FLASK_ENV=production`).
- **`src/utils/validators.py`** — validação de entrada centralizada (telefone, mês, payloads de
  cada domínio); toda rota de escrita passa por uma função `validate_*` antes de tocar o banco.
- **`src/utils/recurrence_generator.py`** — gera as datas de uma série de agendamentos
  recorrentes a partir de frequência + dia + quantidade de meses.
- **`src/utils/api_response.py`** — helpers `ok()`/`fail()` para padronizar o shape das
  respostas JSON.
- **`src/queries/`** — SQL puro por domínio, funções que recebem `conn` + parâmetros e devolvem
  `dict`/`list[dict]`; nunca tocam cache ou HTTP (regra de responsabilidade única documentada no
  README).
