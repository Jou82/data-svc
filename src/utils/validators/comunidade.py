from typing import Final

from flask import abort

from .validators import parse_boolish, require_fields


_CATEGORIAS_SERVICO: Final[set[str]] = {
    # MEI
    "motoboy", "bolos", "doces", "costura", "limpeza", "manicure",
    "cabeleireiro", "fotografia", "design_grafico", "aulas_particulares",
    "frete_mudanca", "jardinagem", "eletricista", "encanador", "pintor", "outros",
    # PL / conselho — estavam faltando e o seed já os usa; sem eles o ranking
    # devolvia 400 e a matriz de complementaridade PL do prompt era inalcançável.
    "advogado", "contador", "dentista", "fisioterapeuta", "nutricionista",
    "psicologo", "personal_trainer", "enfermeiro",
}


def validate_ranking_params(args) -> dict:
    """Valida os query params do ranking de profissionais da Comunidade MEIrelles.

    Args:
        args: request.args (MultiDict) da requisição GET.

    Returns:
        Dict com bairro_id, categoria, solicitante_id, limite, servico_contexto —
        pronto para **kwargs em queries.comunidade.ranking().
    """
    # Opcional: busca sem bairro é o caso comum (ninguém informa bairro no
    # onboarding) e o único caminho para serviço digital/online. `0` e vazio
    # contam como ausente — é o que o n8n manda quando não resolveu bairro.
    bairro_raw = args.get("bairro_id")
    bairro_id = None
    if bairro_raw not in (None, "", "0"):
        try:
            bairro_id = int(bairro_raw)
        except (TypeError, ValueError):
            abort(400, description="o parâmetro 'bairro_id' deve ser um inteiro maior que zero")
        if bairro_id <= 0:
            bairro_id = None

    categoria = str(args.get("categoria") or "").strip().lower()
    if not categoria:
        abort(400, description="o parâmetro 'categoria' é obrigatório")
    if categoria not in _CATEGORIAS_SERVICO:
        permitidos = ", ".join(sorted(_CATEGORIAS_SERVICO))
        abort(400, description=f"o parâmetro 'categoria' está inválido. Use: {permitidos}")

    try:
        solicitante_id = int(args.get("solicitante_id"))
        if solicitante_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        abort(400, description="o parâmetro 'solicitante_id' é obrigatório e deve ser um inteiro maior que zero")

    limit_raw = args.get("limit")
    if limit_raw is None:
        limite = 3
    else:
        try:
            limite = int(limit_raw)
        except (TypeError, ValueError):
            abort(400, description="o parâmetro 'limit' deve ser um inteiro entre 1 e 10")
        if limite < 1 or limite > 10:
            abort(400, description="o parâmetro 'limit' deve ser um inteiro entre 1 e 10")

    servico_contexto = args.get("servico_contexto")

    return {
        "bairro_id": bairro_id,
        "categoria": categoria,
        "solicitante_id": solicitante_id,
        "limite": limite,
        "servico_contexto": servico_contexto,
    }


def validate_bairro_lookup_params(args) -> dict:
    """Valida os query params da resolução de bairro.

    Aceita `nome` (bairro dito explicitamente) OU `texto` (mensagem livre, na qual
    procuramos qualquer bairro citado). Se vierem os dois, `nome` prevalece.
    """
    nome = str(args.get("nome") or "").strip()
    texto = str(args.get("texto") or "").strip()

    if not nome and not texto:
        abort(400, description="informe 'nome' ou 'texto'")

    if nome:
        # `nome` prevalece: zerar `texto` aqui mantém a precedência num lugar só,
        # em vez de depender do `if nome:` da query e da chave de cache.
        return {"nome": nome, "texto": None}

    # `texto` vira LIKE/position no SQL: limitar tamanho evita varredura cara com a
    # mensagem inteira do usuário.
    return {"nome": None, "texto": texto[:500]}


def validate_solicitante_id(args) -> int:
    try:
        solicitante_id = int(args.get("solicitante_id"))
        if solicitante_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        abort(400, description="o parâmetro 'solicitante_id' é obrigatório e deve ser um inteiro maior que zero")
    return solicitante_id


def validate_telefone_param(args) -> str:
    telefone = "".join(ch for ch in str(args.get("telefone") or "") if ch.isdigit())
    if len(telefone) < 10:
        abort(400, description="o parâmetro 'telefone' é obrigatório e deve ter ao menos 10 dígitos")
    return telefone


def validate_resposta_conexao_payload(body: dict) -> dict:
    """Valida o corpo da requisição de resposta (solicitante ou profissional) de uma conexão."""
    require_fields(body, "etapa", "resposta")

    try:
        etapa = int(body.get("etapa"))
    except (TypeError, ValueError):
        abort(400, description="o campo 'etapa' deve ser 1 ou 2")

    if etapa not in (1, 2):
        abort(400, description="o campo 'etapa' deve ser 1 ou 2")

    resposta = parse_boolish(body.get("resposta"), "resposta")

    # Só a etapa 2 fecha a conexão. Default true = comportamento anterior, para
    # não quebrar chamador existente.
    conectar = True
    if "conectar" in body:
        conectar = parse_boolish(body.get("conectar"), "conectar")

    return {"etapa": etapa, "resposta": resposta, "conectar": conectar}


def validate_cancelamento_payload(body: dict) -> dict:
    """Valida o corpo do cancelamento em lote de conexões do solicitante."""
    try:
        solicitante_id = int(body.get("solicitante_id"))
        if solicitante_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        abort(400, description="o campo 'solicitante_id' é obrigatório e deve ser um inteiro maior que zero")

    conexao_id = str(body.get("conexao_id") or "").strip() or None

    return {"solicitante_id": solicitante_id, "conexao_id": conexao_id}
