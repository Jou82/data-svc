import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL: str = os.environ.get("DATA_SVC_DATABASE_URL") or os.environ["DATABASE_URL"]
    PORT: int = int(os.getenv("PORT", 5000))
    FLASK_ENV: str = os.getenv("FLASK_ENV", "production")

    API_KEY: str | None = (os.getenv("API_KEY") or "").strip() or None   # None = auth desativada (dev local)

    # Cache TTLs (segundos)
    CACHE_TTL_USUARIO: int = int(os.getenv("CACHE_TTL_USUARIO", 60))
    CACHE_TTL_SALDO: int = int(os.getenv("CACHE_TTL_SALDO", 300))
    CACHE_TTL_COMPROVANTES: int = int(os.getenv("CACHE_TTL_COMPROVANTES", 300))
    CACHE_TTL_AGENDAMENTOS: int = int(os.getenv("CACHE_TTL_AGENDAMENTOS", 120))
    CACHE_TTL_LISTAS: int = int(os.getenv("CACHE_TTL_LISTAS", 300))
    CACHE_TTL_FEEDBACKS: int = int(os.getenv("CACHE_TTL_FEEDBACKS", 300))
    CACHE_TTL_CONTEXTO_BUSINESS: int = int(os.getenv("CACHE_TTL_CONTEXTO_BUSINESS", 60))

    # Cache L2 distribuído (Upstash Redis REST) — não-fatal, Postgres é fonte da verdade.
    # Vazio = desativado (wrapper vira no-op). Uma DB free serve STG+PRD via prefixo.
    UPSTASH_REDIS_REST_URL: str = (os.getenv("UPSTASH_REDIS_REST_URL") or "").strip()
    UPSTASH_REDIS_REST_TOKEN: str = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()
    CACHE_ENV_PREFIX: str = (os.getenv("CACHE_ENV_PREFIX") or "").strip()  # ex: "stg" / "prd"
    REDIS_TTL_USER: int = int(os.getenv("REDIS_TTL_USER", 600))        # contexto usuário (curto; DB é lei)
    REDIS_TTL_RAG: int = int(os.getenv("REDIS_TTL_RAG", 3600))         # resultado busca vetorial
    REDIS_TTL_MEMORIA: int = int(os.getenv("REDIS_TTL_MEMORIA", 43200))  # janela quente chat (12h)
    DEDUP_TTL: int = int(os.getenv("DEDUP_TTL", 60))                   # janela de deduplicação
    RATE_LIMIT_MAX: int = int(os.getenv("RATE_LIMIT_MAX", 30))         # requests por janela
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", 60))   # janela do rate-limit (s)

    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL", "")
    # Embeddings always via OpenAI (1536 dims fixed in DB). Falls back to OPENAI_API_KEY if not set.
    EMBEDDINGS_API_KEY: str = os.environ.get("EMBEDDINGS_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    # 0.4, não 0.7. O 0.7 era o default histórico e ZERA o retrieval com
    # text-embedding-3-small nesta base: a rota devolve 200 {"resultados": []}
    # sem erro nenhum, o serviço parece saudável e o agente responde sem
    # fundamento. Medido em 2026-08-17 nos dois backends (pgvector e Upstash):
    # recall 0,92 a 0.4 e 0,84 a 0.5, com vazamento de perfil 0,0% em ambos —
    # subir o corte não compra precisão, só apaga resultado. STG e PRD já
    # rodam 0.4 pela env; este default é o que vale em máquina nova e no CI.
    RAG_MATCH_THRESHOLD: float = float(os.environ.get("RAG_MATCH_THRESHOLD", "0.4"))
    RAG_MATCH_COUNT: int = int(os.environ.get("RAG_MATCH_COUNT", "5"))

    # Backend de busca vetorial. `pgvector` (default) = tabela documents no
    # Supabase; `upstash` = índice Upstash Vector, namespace por perfil. A/B de
    # 2026-08-17 deu recall idêntico (0,92) nos dois — ver src/vector.py.
    RAG_BACKEND: str = (os.environ.get("RAG_BACKEND") or "pgvector").strip().lower()
    UPSTASH_VECTOR_REST_URL: str = (os.getenv("UPSTASH_VECTOR_REST_URL") or "").strip()
    UPSTASH_VECTOR_REST_TOKEN: str = (os.getenv("UPSTASH_VECTOR_REST_TOKEN") or "").strip()

    # TypeSafe/Jev — filtro semântico de chunks RAG (lab). Default off; fail-open
    # se key ausente ou API falhar. Jev julga relevância; não gera resposta fiscal.
    TYPESAFE_API_KEY: str = (os.getenv("TYPESAFE_API_KEY") or "").strip()
    TYPESAFE_MODEL: str = (os.getenv("TYPESAFE_MODEL") or "jev-latest").strip()
    TYPESAFE_RAG_SCORE: bool = (os.getenv("TYPESAFE_RAG_SCORE") or "0").strip() in (
        "1",
        "true",
        "True",
        "yes",
        "on",
    )
    TYPESAFE_RAG_RELEVANT_MIN: float = float(os.getenv("TYPESAFE_RAG_RELEVANT_MIN", "0.45"))
    TYPESAFE_RAG_EVIDENCE_MIN: float = float(os.getenv("TYPESAFE_RAG_EVIDENCE_MIN", "0.55"))
    TYPESAFE_RAG_INJECTION_MAX: float = float(os.getenv("TYPESAFE_RAG_INJECTION_MAX", "0.70"))

    # Discord Incoming Webhook (ops). Vazio = alertas desligados (fail-open).
    # Em prod: mesmo URL do n8n `N8N_ERROR_WEBHOOK_URL` (Easypanel), sem versionar.
    DISCORD_ALERT_WEBHOOK_URL: str = (os.getenv("DISCORD_ALERT_WEBHOOK_URL") or "").strip()

    @classmethod
    def validate(cls) -> None:
        if cls.FLASK_ENV == "production" and cls.API_KEY is None:
            raise EnvironmentError(
                "API_KEY é obrigatória. "
            )


Config.validate()
