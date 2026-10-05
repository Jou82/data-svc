"""
Queries do cron de lembretes de agendamentos (janela America/Sao_Paulo).
"""
from psycopg2.extras import RealDictCursor

# Mesma lógica do Cron n8n prod (±window_minutes em lembrete_minutos_antes).
_DUE_SQL = """
WITH _timeout AS (
    SELECT set_config('statement_timeout', '15s', true) AS x
)
SELECT
    a.id,
    a.usuario_id,
    a.nome_compromisso,
    TO_CHAR(a.hora_compromisso, 'HH24:MI:SS') AS hora_compromisso,
    a.status,
    u.numero_telefone,
    a.data_compromisso::text AS data_compromisso
FROM public.agendamentos a
JOIN public.usuarios u ON a.usuario_id = u.id
CROSS JOIN _timeout
WHERE a.status IN ('pendente', 'confirmado', 'agendado')
    AND a.data_compromisso = (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
    AND (a.lembrete_enviado IS NULL OR a.lembrete_enviado = FALSE)
    AND (
        (EXTRACT(HOUR FROM a.hora_compromisso) * 60 + EXTRACT(MINUTE FROM a.hora_compromisso))
        - (
            EXTRACT(HOUR FROM (NOW() AT TIME ZONE 'America/Sao_Paulo')::time) * 60
            + EXTRACT(MINUTE FROM (NOW() AT TIME ZONE 'America/Sao_Paulo')::time)
        )
    ) BETWEEN (COALESCE(a.lembrete_minutos_antes, 15) - %(window_minutes)s)
        AND (COALESCE(a.lembrete_minutos_antes, 15) + %(window_minutes)s)
ORDER BY a.hora_compromisso;
"""

_MARK_SENT_SQL = """
UPDATE public.agendamentos
SET
    lembrete_enviado = TRUE,
    data_lembrete = NOW(),
    data_modificacao = NOW()
WHERE id = %(agendamento_id)s
    AND (lembrete_enviado IS NULL OR lembrete_enviado = FALSE)
RETURNING id, usuario_id, nome_compromisso, lembrete_enviado;
"""

_GET_ROW_SQL = """
SELECT id, usuario_id, nome_compromisso, lembrete_enviado
FROM public.agendamentos
WHERE id = %(agendamento_id)s;
"""


def list_due(conn, window_minutes: int = 2) -> list[dict]:
    params = {"window_minutes": window_minutes}
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_DUE_SQL, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_enviado(conn, agendamento_id: int) -> dict:
    """
    Idempotente: se já enviado, devolve estado atual sem erro.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(_MARK_SENT_SQL, {"agendamento_id": agendamento_id})
        row = cursor.fetchone()
        if row:
            out = dict(row)
            out["already_sent"] = False
            return out

        cursor.execute(_GET_ROW_SQL, {"agendamento_id": agendamento_id})
        existing = cursor.fetchone()
        if existing is None:
            return {"found": False}

        out = dict(existing)
        out["found"] = True
        out["already_sent"] = bool(existing.get("lembrete_enviado"))
        return out
