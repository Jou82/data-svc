"""
Queries de comprovantes — funções puras que recebem conn + parâmetros e retornam rows.
"""
from psycopg2.extras import RealDictCursor


# Cláusula de intervalo de data por coluna. As strings SQL são fixas (nenhum valor de
# usuário é interpolado — só datas validadas via placeholder %(...)s), então não há injeção.
# Range explícito: `data_fim` é inclusivo (usa `< data_fim + 1 dia`). Sem range: mês de `referencia`.
def _clausula_periodo(coluna: str, usa_range: bool) -> str:
    if usa_range:
        return (f"{coluna} >= %(data_inicio)s::date "
                f"AND {coluna} < (%(data_fim)s::date + INTERVAL '1 day')")
    return (f"{coluna} >= date_trunc('month', TO_DATE(%(referencia)s, 'YYYY-MM')) "
            f"AND {coluna} < date_trunc('month', TO_DATE(%(referencia)s, 'YYYY-MM')) + INTERVAL '1 month'")


def get_saldo(conn, usuario_id: int, mes: str = None, data_inicio=None, data_fim=None) -> dict:
    usa_range = bool(data_inicio and data_fim)
    venda_clause = _clausula_periodo("data_venda", usa_range)
    gasto_clause = _clausula_periodo("data_compra", usa_range)
    params = {"usuario_id": usuario_id}
    if usa_range:
        params.update({"data_inicio": data_inicio, "data_fim": data_fim})
    else:
        params["referencia"] = mes

    sql = f"""
        SELECT
            COALESCE(SUM(CASE WHEN operacao = 'venda' THEN valor_total END), 0)::numeric(14,2) AS total_vendas,
            COALESCE(SUM(CASE WHEN operacao = 'gasto' THEN valor_total END), 0)::numeric(14,2) AS total_gastos,
            (COALESCE(SUM(CASE WHEN operacao = 'venda' THEN valor_total END), 0)
            - COALESCE(SUM(CASE WHEN operacao = 'gasto' THEN valor_total END), 0))::numeric(14,2) AS saldo
        FROM public.comprovantes
        WHERE usuario_id = %(usuario_id)s
        AND (
            (operacao = 'venda' AND {venda_clause})
            OR
            (operacao = 'gasto' AND {gasto_clause})
        );
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row)


def list_comprovantes(conn, usuario_id: int, mes: str = None, modo: str = "relatorio",
                      data_inicio=None, data_fim=None) -> list[dict]:
    modo = modo.strip().lower()
    usa_range = bool(data_inicio and data_fim)
    data_expr = ("CASE WHEN operacao = 'gasto' THEN data_compra "
                 "WHEN operacao = 'venda' THEN data_venda END")
    periodo_clause = _clausula_periodo(f"({data_expr})", usa_range)
    params = {"usuario_id": usuario_id, "modo": modo}
    if usa_range:
        params.update({"data_inicio": data_inicio, "data_fim": data_fim})
    else:
        params["referencia"] = mes

    sql = f"""
        SELECT
            id,
            operacao,
            item,
            quantidade,
            valor_unitario,
            valor_total,
            canal_venda,
            pagador_nome,
            pagador_cpf,
            atendido_nome,
            atendido_cpf,
            natureza_pagamento,
            {data_expr} AS data_lancamento
        FROM public.comprovantes
        WHERE usuario_id = %(usuario_id)s
        AND (
            -- filtro de modo: 'relatorio' traz tudo; 'gastos' só gastos; 'vendas' só vendas
            %(modo)s = 'relatorio'
            OR operacao = %(modo)s  -- 'gastos' → 'gasto'; 'vendas' → 'venda' (normalizar no código)
        )
        AND {periodo_clause}
        ORDER BY data_lancamento DESC;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    


def upsert(conn, usuario_id: int, data: dict) -> dict:
    params = {
        "usuario_id": usuario_id,
        "item": data.get("item"),
        "quantidade": data.get("quantidade"),
        "valor_unitario": data.get("valor_unitario"),
        "valor_total": data.get("valor_total"),
        "operacao": data.get("operacao"),
        "item_hash": data.get("item_hash"),
        "data_venda": data.get("data_venda"),
        "data_compra": data.get("data_compra"),
        "canal_venda": data.get("canal_venda"),
        "pagador_nome": data.get("pagador_nome"),
        "pagador_cpf": data.get("pagador_cpf"),
        "atendido_nome": data.get("atendido_nome"),
        "atendido_cpf": data.get("atendido_cpf"),
        "natureza_pagamento": data.get("natureza_pagamento"),
    }

    sql = """
        INSERT INTO public.comprovantes (
            usuario_id, item, quantidade, valor_unitario, valor_total,
            data_compra, data_venda, operacao, last_update, item_hash, canal_venda,
            pagador_nome, pagador_cpf, atendido_nome, atendido_cpf, natureza_pagamento)
        VALUES (
            %(usuario_id)s, %(item)s, %(quantidade)s, %(valor_unitario)s, %(valor_total)s,
            %(data_compra)s, %(data_venda)s, %(operacao)s, NOW(), %(item_hash)s, %(canal_venda)s,
            %(pagador_nome)s, %(pagador_cpf)s, %(atendido_nome)s, %(atendido_cpf)s, %(natureza_pagamento)s)
        ON CONFLICT (item_hash)
        DO UPDATE SET
            quantidade    = EXCLUDED.quantidade,
            valor_unitario = EXCLUDED.valor_unitario,
            valor_total   = EXCLUDED.valor_total,
            last_update   = EXCLUDED.last_update,
            canal_venda   = EXCLUDED.canal_venda,
            pagador_nome  = COALESCE(EXCLUDED.pagador_nome, public.comprovantes.pagador_nome),
            pagador_cpf   = COALESCE(EXCLUDED.pagador_cpf, public.comprovantes.pagador_cpf),
            atendido_nome = COALESCE(EXCLUDED.atendido_nome, public.comprovantes.atendido_nome),
            atendido_cpf  = COALESCE(EXCLUDED.atendido_cpf, public.comprovantes.atendido_cpf),
            natureza_pagamento = COALESCE(EXCLUDED.natureza_pagamento, public.comprovantes.natureza_pagamento)
        RETURNING id, operacao, item, valor_total, data_compra, data_venda, canal_venda,
                  pagador_nome, pagador_cpf, atendido_nome, atendido_cpf, natureza_pagamento,
                  (xmax = 0) AS inserted;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row)


def update_ultimo(conn, usuario_id: int, valor_total=None, item=None, comprovante_id=None, operacao=None) -> dict | None:
    """Atualiza o comprovante indicado por comprovante_id; sem id, cai no último (por last_update DESC)."""
    if operacao is not None:
        op = str(operacao).strip().lower()
        if op in ("rendimento", "venda"):
            operacao = "venda"
        elif op in ("pagamento", "gasto"):
            operacao = "gasto"
        else:
            operacao = None

    params = {
        "usuario_id": usuario_id,
        "valor_total": valor_total,
        "item": item,
        "comprovante_id": comprovante_id,
        "operacao": operacao,
    }

    sql = """
        UPDATE public.comprovantes SET
            valor_total = COALESCE(%(valor_total)s, valor_total),
            valor_unitario = CASE
                WHEN %(valor_total)s IS NULL THEN valor_unitario
                WHEN COALESCE(quantidade, 1) = 1 THEN %(valor_total)s
                ELSE valor_unitario
            END,
            item = COALESCE(%(item)s, item),
            operacao = COALESCE(%(operacao)s, operacao),
            last_update = NOW()
        WHERE id = COALESCE(
            %(comprovante_id)s,
            (SELECT id FROM public.comprovantes WHERE usuario_id=%(usuario_id)s ORDER BY last_update DESC LIMIT 1)
        ) AND usuario_id = %(usuario_id)s
        RETURNING id, operacao, item, valor_total;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_ultimo(conn, usuario_id: int, comprovante_id=None) -> dict | None:
    """Deleta o comprovante indicado por comprovante_id; sem id, cai no último (por last_update DESC)."""
    params = {"usuario_id": usuario_id, "comprovante_id": comprovante_id}

    sql = """
        DELETE FROM public.comprovantes
        WHERE id = COALESCE(
            %(comprovante_id)s,
            (SELECT id FROM public.comprovantes WHERE usuario_id=%(usuario_id)s ORDER BY last_update DESC LIMIT 1)
        ) AND usuario_id = %(usuario_id)s
        RETURNING id;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def get_ultimo(conn, usuario_id: int) -> dict | None:
    """Retorna o último comprovante de um usuário (por last_update DESC)."""
    params = {"usuario_id": usuario_id}

    sql = """
        SELECT id, operacao, item, quantidade, valor_unitario, valor_total,
               to_char(COALESCE(data_venda, data_compra),'DD/MM/YY') AS data_fmt,
               pagador_nome, pagador_cpf, atendido_nome, natureza_pagamento
        FROM public.comprovantes
        WHERE usuario_id=%(usuario_id)s
        ORDER BY last_update DESC LIMIT 1;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def list_recentes(conn, usuario_id: int, limit: int = 10) -> list[dict]:
    """Últimos N comprovantes do usuário (qualquer mês), mais recentes primeiro."""
    limit = max(1, min(int(limit or 10), 50))
    params = {"usuario_id": usuario_id, "limit": limit}

    sql = """
        SELECT id, operacao, item, quantidade, valor_unitario, valor_total,
               data_venda, data_compra,
               COALESCE(data_venda, data_compra) AS data_lancamento,
               to_char(COALESCE(data_venda, data_compra),'DD/MM/YY') AS data_fmt,
               pagador_nome, pagador_cpf, atendido_nome, natureza_pagamento
        FROM public.comprovantes
        WHERE usuario_id=%(usuario_id)s
        ORDER BY last_update DESC
        LIMIT %(limit)s;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]



# Alias usado pelas rotas GET /comprovantes/ultimo?limit=
get_ultimos = list_recentes

def get_livro_caixa(conn, usuario_id: int, mes: str) -> dict:
    """Agrega dados do livro de caixa para um mês específico."""
    params = {
        "usuario_id": usuario_id,
        "mes": mes,
    }

    sql = """
        SELECT
            COALESCE(SUM(valor_total) FILTER (WHERE operacao='venda'),0)::numeric(14,2) AS total_rendimentos,
            COALESCE(SUM(valor_total) FILTER (WHERE operacao='gasto'),0)::numeric(14,2) AS total_pagamentos,
            (COALESCE(SUM(valor_total) FILTER (WHERE operacao='venda'),0)
             - COALESCE(SUM(valor_total) FILTER (WHERE operacao='gasto'),0))::numeric(14,2) AS saldo,
            COUNT(*) FILTER (WHERE operacao='venda') AS total_sessoes,
            COALESCE(AVG(valor_total) FILTER (WHERE operacao='venda'),0)::numeric(14,2) AS ticket_medio
        FROM public.comprovantes
        WHERE usuario_id=%(usuario_id)s
            AND to_char(COALESCE(data_venda,data_compra),'YYYY-MM') = %(mes)s;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row)


def get_livro_caixa_detalhado(conn, usuario_id: int, mes: str) -> dict | None:
    """Perfil + totais + linhas de pagamentos/rendimentos para o PDF do Livro Caixa."""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT id, nome, descricao_negocio, perfil_tipo
            FROM public.usuarios
            WHERE id = %(usuario_id)s
            LIMIT 1;
            """,
            {"usuario_id": usuario_id},
        )
        usuario = cursor.fetchone()
        if not usuario:
            return None

        totais = get_livro_caixa(conn, usuario_id, mes)

        cursor.execute(
            """
            SELECT
                id,
                item,
                natureza_pagamento,
                valor_total AS valor,
                COALESCE(data_compra, data_venda) AS data,
                pagador_nome,
                pagador_cpf,
                atendido_nome,
                atendido_cpf
            FROM public.comprovantes
            WHERE usuario_id = %(usuario_id)s
              AND operacao = 'gasto'
              AND to_char(COALESCE(data_compra, data_venda), 'YYYY-MM') = %(mes)s
            ORDER BY COALESCE(data_compra, data_venda) ASC NULLS LAST, id ASC;
            """,
            {"usuario_id": usuario_id, "mes": mes},
        )
        pagamentos = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                id,
                item,
                natureza_pagamento,
                valor_total AS valor,
                COALESCE(data_venda, data_compra) AS data,
                pagador_nome,
                pagador_cpf,
                atendido_nome,
                atendido_cpf
            FROM public.comprovantes
            WHERE usuario_id = %(usuario_id)s
              AND operacao = 'venda'
              AND to_char(COALESCE(data_venda, data_compra), 'YYYY-MM') = %(mes)s
            ORDER BY COALESCE(data_venda, data_compra) ASC NULLS LAST, id ASC;
            """,
            {"usuario_id": usuario_id, "mes": mes},
        )
        rendimentos = [dict(r) for r in cursor.fetchall()]

    return {
        "usuario_id": usuario_id,
        "mes": mes,
        "nome": usuario.get("nome"),
        "descricao_negocio": usuario.get("descricao_negocio"),
        "perfil_tipo": usuario.get("perfil_tipo"),
        "totais": totais,
        "pagamentos": pagamentos,
        "rendimentos": rendimentos,
    }

