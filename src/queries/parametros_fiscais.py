"""
Queries de parâmetros fiscais — somente leitura sobre public.parametro_fiscal.

Colunas listadas explicitamente: `nota_interna`, `carga` e `id` nunca saem do serviço.
"""
from datetime import date

from psycopg2.extras import RealDictCursor


UF_POR_MUNICIPIO = {"2927408": "BA", "3303302": "RJ", "3304557": "RJ"}

# Regime do perfil → regimes de linha que valem para ele (pf_pj vale para os dois).
REGIMES_APLICAVEIS = {
    "pf": ["pf", "pf_pj"],
    "pj": ["pj", "pf_pj"],
    "mei": ["mei"],
}

# shortcut: ISS de nível não superior (Salvador 16.2, Niterói P2) não se aplica às
# sete profissões da base. A solução limpa é uma coluna de nível no banco (pendente com a Joana).
ENQUADRAMENTOS_NAO_SUPERIOR = {
    ("2927408", "iss", "16.2"),
    ("3303302", "iss", "P2"),
}

TRIBUTOS_POR_REGIME = {
    "pf": ("inss_ci", "receita_saude", "irpf", "anuidade_pf"),
    "pj": ("simples", "anuidade_pj"),
    "mei": ("mei",),
}

TRIBUTOS_MUNICIPAIS = {
    ("2927408", "pf"): ("iss", "tff", "tll", "visa"),
    ("2927408", "pj"): ("tff", "alvara"),
    ("3303302", "pf"): ("iss", "tarm", "tfvs", "licenca_sanitaria"),
    ("3303302", "pj"): ("alvara",),
    ("3304557", "pf"): ("iss", "tls"),
    ("3304557", "pj"): ("alvara", "tls"),
}


def tributos_esperados(municipio_ibge: str, regime: str) -> tuple[str, ...]:
    return TRIBUTOS_POR_REGIME[regime] + TRIBUTOS_MUNICIPAIS.get((municipio_ibge, regime), ())


SQL_PARAMETROS = """
    SELECT
        chave,
        tributo,
        enquadramento,
        tipo_base,
        base_calculo,
        aliquota_pct,
        valor,
        unidade,
        cotas,
        cota_unica_em,
        desconto_cota_unica,
        regra_dia_nao_util,
        autonomo_estabelecido,
        confianca,
        fonte,
        fonte_url,
        observacao,
        vigencia_de,
        vigencia_ate
    FROM public.parametro_fiscal
    WHERE %(data)s BETWEEN vigencia_de AND COALESCE(vigencia_ate, 'infinity')
      AND regime = ANY(%(regimes)s)
      AND (profissao IS NULL OR profissao = %(profissao)s)
      AND (
            ente_tipo = 'federal'
         OR (ente_tipo = 'municipal' AND municipio_ibge = %(municipio_ibge)s)
         OR (ente_tipo = 'conselho' AND uf = %(uf)s)
      )
"""

SQL_FILTRO_CONSULTORIO = """
      AND (autonomo_estabelecido IS NULL OR autonomo_estabelecido = %(consultorio_fixo)s)
"""

SQL_ORDEM = "    ORDER BY tributo, chave;\n"


def list_parametros(
    conn,
    municipio_ibge: str,
    profissao: str,
    regime: str,
    consultorio_fixo: bool | None,
    data: date,
) -> list[dict]:
    sql = SQL_PARAMETROS
    params = {
        "data": data,
        "regimes": REGIMES_APLICAVEIS[regime],
        "profissao": profissao,
        "municipio_ibge": municipio_ibge,
        "uf": UF_POR_MUNICIPIO[municipio_ibge],
    }
    if consultorio_fixo is not None:
        sql += SQL_FILTRO_CONSULTORIO
        params["consultorio_fixo"] = consultorio_fixo
    sql += SQL_ORDEM

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]

    return [
        row for row in rows
        if (municipio_ibge, row["tributo"], row["enquadramento"]) not in ENQUADRAMENTOS_NAO_SUPERIOR
    ]
