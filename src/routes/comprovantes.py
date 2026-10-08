from datetime import date
from flask import Blueprint, abort, request

from src.db import get_db_conn
from src.cache import cache_get, cache_invalidate_prefix, cache_set
from src.config import Config
from src.utils.validators import validate_comprovante_payload, validate_mes, validate_modo, validate_intervalo
import src.queries.comprovantes as q
from src.pdf.livro_caixa import build_livro_caixa_pdf, pdf_to_base64_payload
from src.utils.api_response import fail, ok

comprovantes_bp = Blueprint("comprovantes", __name__)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/saldo", methods=["GET"])
def get_saldo(usuario_id: int):
    # Range explícito (data_inicio+data_fim) tem prioridade; senão cai no filtro por mês.
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    if data_inicio or data_fim:
        data_inicio, data_fim = validate_intervalo(data_inicio, data_fim)
        cache_key = f"{usuario_id}:{data_inicio}:{data_fim}"
    else:
        mes = validate_mes(request.args.get("mes"))
        cache_key = f"{usuario_id}:{mes}"

    saldo_mes = cache_get("saldo", cache_key)
    if saldo_mes:
        return ok(200, saldo_mes)

    with get_db_conn() as conn:
        if data_inicio and data_fim:
            saldo_mes = q.get_saldo(conn, usuario_id, data_inicio=data_inicio, data_fim=data_fim)
        else:
            saldo_mes = q.get_saldo(conn, usuario_id, mes)

        cache_set("saldo", cache_key, saldo_mes, Config.CACHE_TTL_SALDO)

        return ok(200, saldo_mes)
    


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes", methods=["GET"])
def list_comprovantes(usuario_id: int):
    modo = validate_modo(request.args.get("modo"))
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    if data_inicio or data_fim:
        data_inicio, data_fim = validate_intervalo(data_inicio, data_fim)
        cache_key = f"{usuario_id}:{data_inicio}:{data_fim}:{modo}"
    else:
        mes = validate_mes(request.args.get("mes"))
        cache_key = f"{usuario_id}:{mes}:{modo}"

    comprovantes = cache_get("comprovantes", cache_key)
    if comprovantes:
        return ok(200, comprovantes)

    with get_db_conn() as conn:
        if data_inicio and data_fim:
            comprovantes = q.list_comprovantes(conn, usuario_id, modo=modo,
                                               data_inicio=data_inicio, data_fim=data_fim)
        else:
            comprovantes = q.list_comprovantes(conn, usuario_id, mes, modo)

        cache_set("comprovantes", cache_key, comprovantes, Config.CACHE_TTL_COMPROVANTES)

        return ok(200, comprovantes)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes", methods=["POST"])
def create_comprovante(usuario_id: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("body_invalido", "JSON inválido ou ausente", 400)

    body = validate_comprovante_payload(body)

    with get_db_conn() as conn:
        comprovante = q.upsert(conn, usuario_id, body)

        # Inclui comprovantes_ultimo — senão GET /ultimo?limit=N serve lista stale
        # e "foi X" edita o lançamento errado (pool[0] velho).
        _invalidar_cache_comprovantes(usuario_id)

        return ok(200, comprovante)


def _parse_limit(raw: str | None) -> int | None:
    """?limit= ausente → None (comportamento antigo). Presente: inteiro 1..50, senão 400."""
    if raw is None:
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 0
    if not 1 <= limit <= 50:
        abort(400, description="parâmetro 'limit' deve ser um inteiro entre 1 e 50")
    return limit


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes/ultimo", methods=["GET"])
def get_comprovante_ultimo(usuario_id: int):
    limit = _parse_limit(request.args.get("limit"))

    if limit is not None:
        # Chave com o prefixo `{usuario_id}` pra cair na mesma invalidação das rotas de escrita.
        cache_key = f"{usuario_id}:limit:{limit}"
        ultimos = cache_get("comprovantes_ultimo", cache_key)
        if ultimos:
            return ok(200, ultimos)

        with get_db_conn() as conn:
            items = q.get_ultimos(conn, usuario_id, limit)
            ultimos = {"items": items, "count": len(items)}
            cache_set("comprovantes_ultimo", cache_key, ultimos, Config.CACHE_TTL_COMPROVANTES)
            return ok(200, ultimos)

    comprovante = cache_get("comprovantes_ultimo", f"{usuario_id}")
    if comprovante:
        return ok(200, comprovante)

    with get_db_conn() as conn:
        comprovante = q.get_ultimo(conn, usuario_id)

        if not comprovante:
            return fail("comprovante_nao_encontrado", "Nenhum comprovante encontrado para este usuário", 404)

        cache_set("comprovantes_ultimo", f"{usuario_id}", comprovante, Config.CACHE_TTL_COMPROVANTES)

        return ok(200, comprovante)


def _invalidar_cache_comprovantes(usuario_id: int):
    cache_invalidate_prefix("saldo", f"{usuario_id}:")
    cache_invalidate_prefix("comprovantes", f"{usuario_id}:")
    cache_invalidate_prefix("comprovantes_ultimo", f"{usuario_id}")


def _patch_comprovante(usuario_id: int, comprovante_id: int | None):
    """Corpo compartilhado do PATCH /ultimo e PATCH /<comprovante_id>.

    Com `comprovante_id` explícito na URL ele prevalece; no /ultimo vem do body (ou None → último).
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("body_invalido", "JSON inválido ou ausente", 400)

    valor_total = body.get("valor_total")
    item = body.get("item")
    if comprovante_id is None:
        comprovante_id = body.get("comprovante_id")

    with get_db_conn() as conn:
        comprovante = q.update_ultimo(conn, usuario_id, valor_total, item, comprovante_id)

        if not comprovante:
            return fail("nao_encontrado", "Nenhum comprovante encontrado para este usuário", 404)

        _invalidar_cache_comprovantes(usuario_id)

        return ok(200, comprovante)


def _delete_comprovante(usuario_id: int, comprovante_id: int | None):
    """Corpo compartilhado do DELETE /ultimo e DELETE /<comprovante_id>."""
    if comprovante_id is None:
        body = request.get_json(silent=True)
        comprovante_id = body.get("comprovante_id") if isinstance(body, dict) else None

    with get_db_conn() as conn:
        result = q.delete_ultimo(conn, usuario_id, comprovante_id)

        if not result:
            return fail("nao_encontrado", "Nenhum comprovante encontrado para este usuário", 404)

        _invalidar_cache_comprovantes(usuario_id)

        return ok(200, result)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes/ultimo", methods=["PATCH"])
def patch_comprovante_ultimo(usuario_id: int):
    return _patch_comprovante(usuario_id, None)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes/ultimo", methods=["DELETE"])
def delete_comprovante_ultimo(usuario_id: int):
    return _delete_comprovante(usuario_id, None)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes/<int:comprovante_id>", methods=["PATCH"])
def patch_comprovante_por_id(usuario_id: int, comprovante_id: int):
    """Edita um comprovante específico; 404 se não pertence ao usuário (filtro `usuario_id` na query)."""
    return _patch_comprovante(usuario_id, comprovante_id)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/comprovantes/<int:comprovante_id>", methods=["DELETE"])
def delete_comprovante_por_id(usuario_id: int, comprovante_id: int):
    """Remove um comprovante específico; 404 se não pertence ao usuário."""
    return _delete_comprovante(usuario_id, comprovante_id)


@comprovantes_bp.route("/usuarios/<int:usuario_id>/livro-caixa", methods=["GET"])
def get_livro_caixa(usuario_id: int):
    mes = validate_mes(request.args.get("mes"))

    livro_caixa = cache_get("livro-caixa", f"{usuario_id}:{mes}")
    if livro_caixa:
        return ok(200, livro_caixa)

    with get_db_conn() as conn:
        livro_caixa = q.get_livro_caixa(conn, usuario_id, mes)

        cache_set("livro-caixa", f"{usuario_id}:{mes}", livro_caixa, Config.CACHE_TTL_COMPROVANTES)

        return ok(200, livro_caixa)

@comprovantes_bp.route("/usuarios/<int:usuario_id>/livro-caixa/pdf", methods=["GET"])
def get_livro_caixa_pdf(usuario_id: int):
    """Gera PDF do Livro Caixa (layout design PL) e devolve base64 p/ Z-API."""
    mes_raw = request.args.get("mes") or date.today().strftime("%Y-%m")
    mes = validate_mes(mes_raw)
    parcial = str(request.args.get("parcial", "true")).lower() not in ("0", "false", "no")

    with get_db_conn() as conn:
        detalhado = q.get_livro_caixa_detalhado(conn, usuario_id, mes)

    if not detalhado:
        return fail("nao_encontrado", "Usuário não encontrado", 404)

    pdf_bytes = build_livro_caixa_pdf(detalhado)
    return ok(200, pdf_to_base64_payload(pdf_bytes, mes, parcial=parcial))

