from flask import Blueprint, request

from src.cache import cache_invalidate_prefix
from src.db import get_db_conn
from src.utils.api_response import fail, ok
from src.utils.db_retry import run_db_with_retry
import src.queries.lembretes as q

lembretes_bp = Blueprint("lembretes", __name__)


def _parse_window_minutes(raw: str | None) -> int:
    if raw is None or raw == "":
        return 2
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("parâmetro 'window_minutes' deve ser inteiro") from exc
    if value < 0 or value > 10:
        raise ValueError("parâmetro 'window_minutes' deve estar entre 0 e 10")
    return value


@lembretes_bp.route("/lembretes/due", methods=["GET"])
def lembretes_due():
    try:
        window_minutes = _parse_window_minutes(request.args.get("window_minutes"))
    except ValueError as exc:
        return fail("bad_request", str(exc), 400)

    def _load():
        with get_db_conn() as conn:
            return q.list_due(conn, window_minutes=window_minutes)

    items = run_db_with_retry(_load, operation="lembretes_due")
    return ok(200, {"items": items, "count": len(items), "window_minutes": window_minutes})


@lembretes_bp.route("/lembretes/<int:agendamento_id>/enviado", methods=["POST"])
def lembretes_marcar_enviado(agendamento_id: int):
    def _mark():
        with get_db_conn() as conn:
            return q.mark_enviado(conn, agendamento_id)

    result = run_db_with_retry(_mark, operation="lembretes_marcar_enviado")

    if result.get("found") is False:
        return fail("agendamento_nao_encontrado", f"id {agendamento_id} não existe", 404)

    usuario_id = result.get("usuario_id")
    if usuario_id is not None:
        cache_invalidate_prefix("agendamentos", f"{usuario_id}:")

    if result.get("already_sent"):
        return ok(
            200,
            {
                "id": result["id"],
                "lembrete_enviado": True,
                "already_sent": True,
                "nome_compromisso": result.get("nome_compromisso"),
            },
        )

    return ok(
        200,
        {
            "id": result["id"],
            "lembrete_enviado": result.get("lembrete_enviado", True),
            "already_sent": False,
            "nome_compromisso": result.get("nome_compromisso"),
        },
    )
