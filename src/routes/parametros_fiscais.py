from flask import Blueprint, request

from src.db import get_db_conn
from src.cache import cache_get, cache_set
from src.config import Config
from src.utils.validators import ParametroFiscalInvalido, validate_parametros_fiscais_query
import src.queries.parametros_fiscais as q
from src.utils.api_response import fail, ok

parametros_fiscais_bp = Blueprint("parametros_fiscais", __name__)

CACHE_NS = "parametros_fiscais"

# Lista branca: nota_interna (valores candidatos de linhas a_confirmar) nunca sai daqui.
CAMPOS_PARAMETRO = (
    "chave",
    "tributo",
    "enquadramento",
    "tipo_base",
    "base_calculo",
    "aliquota_pct",
    "valor",
    "unidade",
    "cotas",
    "cota_unica_em",
    "desconto_cota_unica",
    "regra_dia_nao_util",
    "autonomo_estabelecido",
    "confianca",
    "fonte",
    "fonte_url",
    "observacao",
    "vigencia_de",
    "vigencia_ate",
)


@parametros_fiscais_bp.route("/parametros-fiscais", methods=["GET"])
def get_parametros_fiscais():
    try:
        perfil = validate_parametros_fiscais_query(request.args)
    except ParametroFiscalInvalido as e:
        return fail(e.code, e.detail, e.status)

    chave = ":".join(str(perfil[campo]) for campo in ("municipio_ibge", "profissao", "regime", "consultorio_fixo", "data"))
    cached = cache_get(CACHE_NS, chave)
    if cached is not None:
        return ok(200, cached)

    with get_db_conn() as conn:
        rows = q.list_parametros(
            conn,
            perfil["municipio_ibge"],
            perfil["profissao"],
            perfil["regime"],
            perfil["consultorio_fixo"],
            perfil["data"],
        )

    parametros, escalonar = _montar(rows, perfil["municipio_ibge"], perfil["regime"])
    resposta = {"perfil": perfil, "parametros": parametros, "escalonar": escalonar}

    # Só resposta bem-sucedida chega aqui: erro de banco propaga e não é cacheado.
    cache_set(CACHE_NS, chave, resposta, Config.CACHE_TTL_PARAMETROS_FISCAIS)
    return ok(200, resposta)


def _montar(rows: list[dict], municipio_ibge: str, regime: str) -> tuple[list[dict], list[dict]]:
    parametros = []
    escalonar = []

    for row in rows:
        if row["confianca"] == "a_confirmar":
            # Sem valor e sem nota_interna: valor não confirmado não sai do serviço.
            escalonar.append({
                "tributo": row["tributo"],
                "motivo": "a_confirmar",
                "chave": row["chave"],
                "observacao": row["observacao"],
                "fonte": row["fonte"],
            })
        else:
            parametros.append({campo: row[campo] for campo in CAMPOS_PARAMETRO})

    # Linha ausente não tem observação: o serviço precisa saber o que deveria existir.
    presentes = {row["tributo"] for row in rows}
    escalonar.extend(
        {"tributo": tributo, "motivo": "sem_dado", "observacao": None}
        for tributo in q.tributos_esperados(municipio_ibge, regime)
        if tributo not in presentes
    )

    return parametros, escalonar
