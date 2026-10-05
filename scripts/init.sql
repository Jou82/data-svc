-- Comente ou remova estas linhas do schema antes de usar localmente:
-- CREATE EXTENSION IF NOT EXISTS "pg_graphql";
-- CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- CREATE EXTENSION IF NOT EXISTS "pgjwt";
-- CREATE EXTENSION IF NOT EXISTS "supabase_vault";

-- Mantenha apenas:
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "unaccent";


-- Criação da tabela usuarios
CREATE TABLE public.usuarios (
  id                   bigint        NOT NULL GENERATED ALWAYS AS IDENTITY,
  numero_telefone      varchar(20),                          -- identificador principal, único
  nome                 varchar(100),                         -- nome preferido do MEI
  razao_social         text,                                 -- nome do negócio
  email                varchar,
  "cpfCnpj"            varchar,
  interacao_previa     boolean       DEFAULT false,          -- false = onboarding ainda não concluído
  estado_atual         text          DEFAULT 'menu',         -- estado da conversa atual
  -- Campos preenchidos pelo onboarding — Bloco 1 (Pessoa)
  dias_trabalho        text,                                 -- ex: 'seg,ter,qua,qui,sex'
  horario_inicio       time,                                 -- ex: 08:00
  horario_fim          time,                                 -- ex: 18:00
  -- Campos preenchidos pelo onboarding — Bloco 2 (Empresa)
  descricao_negocio    text,                                 -- síntese do áudio de apresentação do negócio
  descricao_objetivo   text,                                 -- síntese do áudio de objetivo de vida
  area_ajuda           text,                                 -- onde o MEI mais precisa de ajuda
  tipo_negocio         varchar       CHECK (tipo_negocio IN ('produto', 'servico', 'ambos')),
  preco_referencia     numeric,                              -- preço médio do produto/serviço principal
  -- Integrações externas (fora do escopo do data-svc)
  asaas_customer_id    varchar,
  subconta_asaas_id    integer,
  tem_subconta_ativa   boolean       DEFAULT false,
  relatorio_atual_id   bigint,
  -- Timestamps
  data_primeiro_contato timestamp with time zone,
  data_ultimo_contato   timestamp with time zone,
  CONSTRAINT usuarios_pkey PRIMARY KEY (id)
);

-- Índice principal: busca por telefone em toda mensagem recebida
CREATE UNIQUE INDEX idx_usuarios_telefone ON public.usuarios (numero_telefone);
-- Índice para o workflow Retornar estado Menu
CREATE INDEX idx_usuarios_estado_atual ON public.usuarios (estado_atual);


-- Criação da tabela comprovantes
CREATE TABLE public.comprovantes (
  id             integer       NOT NULL GENERATED ALWAYS AS IDENTITY,
  usuario_id     integer       NOT NULL REFERENCES public.usuarios(id),
  item           text,                        -- descrição do item/serviço
  quantidade     numeric(10,3),
  valor_unitario numeric(12,2),
  valor_total    numeric(12,2) NOT NULL,
  operacao       text          NOT NULL,      -- 'venda' ou 'gasto'
  data_venda     date,                        -- preenchido quando operacao = 'venda'
  data_compra    date,                        -- preenchido quando operacao = 'gasto'
  last_update    timestamp with time zone,
  item_hash      varchar,                     -- hash SHA para idempotência no upsert
  canal_venda    text,
  pagador_nome   text,                        -- PL: quem pagou
  pagador_cpf    text,                        -- PL: CPF do pagador
  atendido_nome  text,                        -- PL: paciente/cliente atendido
  CONSTRAINT comprovantes_pkey PRIMARY KEY (id),
  CONSTRAINT comprovantes_item_hash_key UNIQUE (item_hash)
);

CREATE INDEX idx_comprovantes_usuario_mes
  ON public.comprovantes (usuario_id, data_venda, data_compra);


-- Criação da tabela agendamentos
CREATE TABLE public.agendamentos (
  id                bigint        NOT NULL GENERATED ALWAYS AS IDENTITY,
  usuario_id        bigint        REFERENCES public.usuarios(id),
  nome_compromisso  varchar(200),
  data_compromisso  date,
  hora_compromisso  time,
  status            text          DEFAULT 'pendente'
                    CHECK (status IN ('pendente', 'confirmado', 'agendado', 'cancelado')),
  lembrete_enviado  boolean       DEFAULT false,  -- atualizado pelo workflow Lembretes automaticos
  lembrete_minutos_antes integer  DEFAULT 15,
  data_lembrete     timestamp,
  tipo_agendamento  varchar(20)   DEFAULT 'unico',
  recorrencia_id    uuid,
  data_criacao      timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
  data_modificacao  timestamp with time zone,
  CONSTRAINT agendamentos_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_agendamentos_usuario_semana
  ON public.agendamentos (usuario_id, data_compromisso)
  WHERE status IN ('pendente', 'confirmado');

CREATE INDEX idx_agendamentos_lembrete
  ON public.agendamentos (data_compromisso, hora_compromisso)
  WHERE lembrete_enviado = false AND status IN ('pendente', 'confirmado');


-- Criação da tabela lista_compras
CREATE TABLE public.lista_compras (
  id               integer       NOT NULL GENERATED ALWAYS AS IDENTITY,
  usuario_id       integer       NOT NULL REFERENCES public.usuarios(id),
  nome_lista       varchar(255)  NOT NULL,
  data_criacao     timestamp     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  data_atualizacao timestamp     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT lista_compras_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_lista_compras_usuario ON public.lista_compras (usuario_id);


-- Criação da tabela itens_lista
CREATE TABLE public.itens_lista (
  id             integer        NOT NULL GENERATED ALWAYS AS IDENTITY,
  lista_id       integer        NOT NULL REFERENCES public.lista_compras(id),
  nome_item      varchar(255)   NOT NULL,
  quantidade     integer        NOT NULL CHECK (quantidade > 0),
  preco_unitario numeric(10,2)  NOT NULL CHECK (preco_unitario >= 0),
  preco_total    numeric(12,2)  GENERATED ALWAYS AS (quantidade * preco_unitario) STORED,
  CONSTRAINT itens_lista_pkey PRIMARY KEY (id),
  CONSTRAINT itens_lista_lista_id_nome_item_key UNIQUE (lista_id, nome_item)
);


-- Criação da tabela contas_recorrentes
CREATE TABLE public.contas_recorrentes (
  id             integer        NOT NULL GENERATED ALWAYS AS IDENTITY,
  usuario_id     bigint         NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
  tipo           varchar        NOT NULL
                 CHECK (tipo IN ('aluguel', 'internet', 'luz', 'agua', 'boleto')),
  descricao      varchar,                      -- obrigatório quando tipo = 'boleto'
  valor          numeric,                      -- NULL para contas variáveis (luz, água)
  dia_vencimento integer        CHECK (dia_vencimento BETWEEN 1 AND 31),
  lembrete_ativo boolean        NOT NULL DEFAULT false,
  pix_chave      text,                         -- incluso no lembrete mensal quando preenchido
  ativo          boolean        NOT NULL DEFAULT true,  -- soft delete
  created_at     timestamp      NOT NULL DEFAULT now(),
  updated_at     timestamp      NOT NULL DEFAULT now(),
  CONSTRAINT contas_recorrentes_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_contas_recorrentes_usuario ON public.contas_recorrentes (usuario_id);
CREATE INDEX idx_contas_recorrentes_lembrete
  ON public.contas_recorrentes (usuario_id, dia_vencimento)
  WHERE lembrete_ativo = true AND ativo = true;

-- Índice parcial para UPSERT em POST /contas-recorrentes
-- Garante unicidade de (usuario_id, tipo) apenas para tipos que não são 'boleto'
CREATE UNIQUE INDEX contas_recorrentes_usuario_tipo_unique
  ON public.contas_recorrentes (usuario_id, tipo)
  WHERE tipo <> 'boleto';
