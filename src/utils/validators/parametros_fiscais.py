from datetime import date

from src.queries.parametros_fiscais import UF_POR_MUNICIPIO
from src.utils.validators.validators import now_time_zone


PROFISSOES = frozenset({
    "dentista",
    "fisioterapeuta",
    "fonoaudiologo",
    "medico",
    "nutricionista",
    "psicologo",
    "terapeuta_ocupacional",
})
REGIMES = frozenset({"pf", "pj", "mei"})


class ParametroFiscalInvalido(Exception):
    def __init__(self, code: str, detail: str, status: int):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


def _obrigatorio(args, campo: str) -> str:
    valor = (args.get(campo) or "").strip()
    if not valor:
        raise ParametroFiscalInvalido("parametro_invalido", f"o parâmetro '{campo}' é obrigatório", 400)
    return valor


def validate_parametros_fiscais_query(args) -> dict:
    """Valida o query string de GET /parametros-fiscais e devolve o perfil normalizado."""
    municipio = _obrigatorio(args, "municipio_ibge")
    profissao = _obrigatorio(args, "profissao")
    regime = _obrigatorio(args, "regime")

    if municipio not in UF_POR_MUNICIPIO:
        raise ParametroFiscalInvalido(
            "municipio_nao_suportado",
            "município sem parâmetros: use 2927408 (Salvador), 3303302 (Niterói) ou 3304557 (Rio)",
            422,
        )
    if profissao not in PROFISSOES:
        raise ParametroFiscalInvalido("parametro_invalido", "profissao não suportada", 400)
    if regime not in REGIMES:
        raise ParametroFiscalInvalido("parametro_invalido", "regime deve ser pf, pj ou mei", 400)

    consultorio = args.get("consultorio_fixo")
    if consultorio is None:
        consultorio_fixo = None
    elif consultorio in ("true", "false"):
        consultorio_fixo = consultorio == "true"
    else:
        raise ParametroFiscalInvalido("parametro_invalido", "consultorio_fixo deve ser true ou false", 400)

    data_informada = args.get("data")
    if data_informada is None:
        data = now_time_zone().date()
    else:
        try:
            data = date.fromisoformat(data_informada.strip())
        except ValueError:
            raise ParametroFiscalInvalido("parametro_invalido", "data deve estar no formato AAAA-MM-DD", 400)

    return {
        "municipio_ibge": municipio,
        "profissao": profissao,
        "regime": regime,
        "consultorio_fixo": consultorio_fixo,
        "data": data,
    }
