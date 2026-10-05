import hashlib

from flask import Blueprint, request
from openai import OpenAI
from src.db import get_db_conn
from src import redis_cache, vector
from src.config import Config
from src.utils.api_response import ok, fail
from src.utils.texto import normalizar_busca
from src.typesafe import rag_passages
import src.queries.rag as queries

rag_bp = Blueprint("rag", __name__)
_openai_client: OpenAI | None = None

# tags de perfil em documents.metadata usam 'pl' (não 'profissional_liberal')
_PERFIL_MAP = {"profissional_liberal": "pl", "pl": "pl", "mei": "mei", "autonomo": "autonomo"}


def _perfil_do_filtro(body: dict) -> str | None:
    """Perfil vindo de `metadata_filter: {perfil: [...]}`, que é o que o n8n manda.

    Os nós vivos (Pivo MEI `qIJeMzdPy5dxITPq`, Pivo PL `6WqW7NG8pceqzRi0`) sempre
    montaram o body nessa forma, mas a rota só lia `body["perfil"]` — e
    `metadata_filter` nunca existiu no histórico dela. Resultado em produção:
    perfil sempre None, cláusula de filtro nunca aplicada (PL recebendo chunk de
    DAS) e, com RAG_BACKEND=upstash, todo request degradando para o pgvector.

    Tolerante de propósito: lista, string solta ou lixo caem em None (sem filtro),
    nunca em 500 — isto está no caminho de resposta ao usuário.
    """
    mf = body.get("metadata_filter")
    if not isinstance(mf, dict):
        return None
    valor = mf.get("perfil")
    if isinstance(valor, (list, tuple)):
        valor = valor[0] if valor else None
    return _PERFIL_MAP.get(str(valor or "").lower().strip())


def _source_prefix_do_body(body: dict) -> str | None:
    """Prefixo de `metadata.source` (ex. ``knowledge_duvidas``).

    Aceita top-level `source_prefix` ou `metadata_filter.source_prefix`.
    Só alfanumérico / `_` / `-` / `.` — o restante é descartado (sem filtro).
    """
    mf = body.get("metadata_filter") if isinstance(body.get("metadata_filter"), dict) else {}
    raw = body.get("source_prefix")
    if raw is None and isinstance(mf, dict):
        raw = mf.get("source_prefix")
    if raw is None:
        return None
    safe = "".join(c for c in str(raw) if c.isalnum() or c in "_-.")
    return safe or None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        # Embeddings always hit OpenAI directly — no base_url override (Gemini compat doesn't support embeddings)
        _openai_client = OpenAI(api_key=Config.EMBEDDINGS_API_KEY)
    return _openai_client


@rag_bp.post("/rag/busca")
def busca_rag():
    body = request.get_json()
    if not body or "pergunta" not in body:
        return fail("missing_field", "Campo obrigatório: pergunta", 400)

    # Forma canônica ANTES do embedding: usuário de WhatsApp digita sem acento, e
    # o text-embedding-3-small trata `carne-leao` e `carnê-leão` como palavras
    # diferentes (medido em PRD: 5 chunks a 0,6017 contra ZERO). Só funciona
    # porque o acervo é indexado pela MESMA função — ver src/utils/texto.py.
    pergunta = normalizar_busca(body["pergunta"])
    match_count = int(body.get("match_count", Config.RAG_MATCH_COUNT))
    match_threshold = float(body.get("match_threshold", Config.RAG_MATCH_THRESHOLD))
    # perfil opcional: filtra chunks por metadata.perfil (mei|autonomo|pl); inválido/ausente = sem filtro
    perfil = _PERFIL_MAP.get(str(body.get("perfil") or "").lower().strip()) or _perfil_do_filtro(body)
    source_prefix = _source_prefix_do_body(body)

    # Cache por hash da query normalizada + params (inclui perfil/source: filtro muda o
    # resultado; e o backend: o L2 dura REDIS_TTL_RAG=3600s e não sabe quem gerou
    # a linha, então sem isso virar RAG_BACKEND serviria o resultado do backend
    # anterior por uma hora — o A/B em produção estaria medindo o cache).
    # ts1/ts0: TypeSafe RAG score muda o conjunto — não misturar com cache sem filtro.
    backend = Config.RAG_BACKEND
    ts_flag = "ts1" if Config.TYPESAFE_RAG_SCORE else "ts0"
    cache_key = "rag:" + hashlib.sha256(
        f"{pergunta.strip().lower()}|{match_count}|{match_threshold}|{perfil or ''}|"
        f"{source_prefix or ''}|{backend}|{ts_flag}".encode("utf-8")
    ).hexdigest()
    cached = redis_cache.cache_get(cache_key)
    if cached is not None:
        return ok(200, {"resultados": cached})

    try:
        resp = _get_client().embeddings.create(
            input=pergunta, model=Config.EMBEDDING_MODEL
        )
        embedding = resp.data[0].embedding
    except Exception as e:
        return fail("embedding_error", str(e), 500)

    resultados = None
    if backend == "upstash":
        try:
            resultados = vector.busca_semantica(
                embedding,
                match_threshold,
                match_count,
                perfil,
                source_prefix=source_prefix,
            )
            # Log do caminho de SUCESSO, não só da falha. Sem ele o cutover é
            # inverificável: stdout limpo depois de virar a flag é ambíguo entre
            # "índice servindo" e "RAG_BACKEND nem foi lido". `resultados=0` é o
            # caso que mais precisa aparecer — 200 vazio legítimo e backend nunca
            # acionado produzem a mesma resposta HTTP.
            print(
                f"[rag] upstash ok: perfil={perfil} source_prefix={source_prefix} "
                f"resultados={len(resultados)}"
            )
            # Índice Upstash pode estar sem knowledge_duvidas_pl (prod 2026-10-03:
            # source_prefix + perfil=pl → 0 hits). Degrada pro pgvector em vez de
            # 200 vazio silencioso — o agente Dúvidas PL alucinava sem base.
            if not resultados and source_prefix:
                print(
                    f"[rag] upstash vazio com source_prefix={source_prefix}, "
                    "caindo no pgvector"
                )
                resultados = None
        except vector.VectorIndisponivel as e:
            # degrada para o pgvector em vez de 500 ou lista vazia. O log é
            # obrigatório: fallback mudo faz a Upstash parecer saudável enquanto
            # o Postgres serve 100% do tráfego.
            print(f"[rag] upstash indisponivel, caindo no pgvector: {e}")

    if resultados is None:
        with get_db_conn() as conn:
            resultados = queries.busca_semantica(
                conn,
                embedding,
                match_threshold,
                match_count,
                perfil,
                source_prefix=source_prefix,
            )

    # TypeSafe: julga cada chunk (Nouls). Flag off / sem key / erro → fail-open.
    resultados = rag_passages.filter_passages(pergunta, resultados, perfil)

    redis_cache.cache_set(cache_key, resultados, Config.REDIS_TTL_RAG)
    return ok(200, {"resultados": resultados})
