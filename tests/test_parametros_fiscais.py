import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import psycopg2
import pytest

import src.queries.parametros_fiscais as q
from src.cache import cache_invalidate
from src.utils.validators.validators import now_time_zone

ENDPOINT = "/parametros-fiscais"
SALVADOR = "2927408"
NITEROI = "3303302"
RIO = "3304557"


@pytest.fixture(autouse=True)
def _cache_limpo():
    cache_invalidate("parametros_fiscais")
    yield
    cache_invalidate("parametros_fiscais")


def _row(**campos):
    base = {
        "chave": "ssa.iss.pf.todas.16_1",
        "tributo": "iss",
        "enquadramento": "16.1",
        "tipo_base": "base_x_aliquota",
        "base_calculo": Decimal("27919.25"),
        "aliquota_pct": Decimal("5"),
        "valor": Decimal("1395.96"),
        "unidade": "BRL_ano",
        "cotas": [date(2026, 6, 30)],
        "cota_unica_em": date(2026, 6, 30),
        "desconto_cota_unica": Decimal("7"),
        "regra_dia_nao_util": "antecipa",
        "autonomo_estabelecido": None,
        "confianca": "alta",
        "fonte": "Lei municipal",
        "fonte_url": "https://example.test/lei",
        "observacao": "obs",
        "vigencia_de": date(2026, 1, 1),
        "vigencia_ate": date(2026, 12, 31),
        "nota_interna": "CANDIDATO 4242.00",
    }
    base.update(campos)
    return base


def _mock_db(mocker):
    conn = object()
    ctx = mocker.MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    mocker.patch("src.routes.parametros_fiscais.get_db_conn", return_value=ctx)
    return conn


def _get(client, mocker, rows, **params):
    query = {"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf",
             "consultorio_fixo": "true", "data": "2026-11-04", **params}
    query = {k: v for k, v in query.items() if v is not None}
    mocker.patch("src.routes.parametros_fiscais.q.list_parametros", return_value=rows)
    return client.get(ENDPOINT, query_string=query)


class TestValidacao:
    @pytest.mark.parametrize(
        "params, status, erro",
        [
            ({"profissao": "psicologo", "regime": "pf"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "regime": "pf"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "profissao": "psicologo"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "xpto"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "profissao": "engenheiro", "regime": "pf"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "consultorio_fixo": "sim"}, 400, "parametro_invalido"),
            ({"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "data": "04/11/2026"}, 400, "parametro_invalido"),
            ({"municipio_ibge": "1234567", "profissao": "psicologo", "regime": "pf"}, 422, "municipio_nao_suportado"),
        ],
    )
    def test_rejeita_parametros_invalidos(self, client, mocker, params, status, erro):
        list_mock = mocker.patch("src.routes.parametros_fiscais.q.list_parametros")

        resp = client.get(ENDPOINT, query_string=params)

        assert resp.status_code == status
        assert resp.get_json()["error"] == erro
        list_mock.assert_not_called()

    def test_data_padrao_e_hoje_em_sao_paulo(self, client, mocker):
        _mock_db(mocker)
        mocker.patch("src.routes.parametros_fiscais.q.list_parametros", return_value=[])

        resp = client.get(ENDPOINT, query_string={
            "municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf",
        })

        assert resp.status_code == 200
        assert resp.get_json()["perfil"]["consultorio_fixo"] is None
        assert resp.get_json()["perfil"]["data"] == now_time_zone().date().isoformat()


class TestResposta:
    def test_separa_parametros_de_escalonar_e_nunca_expoe_nota_interna(self, client, mocker):
        _mock_db(mocker)
        rows = [
            _row(),
            _row(
                chave="cons.ba.anuidade_pf.pf.psicologo",
                tributo="anuidade_pf",
                enquadramento=None,
                tipo_base="valor_fixo",
                valor=None,
                unidade="BRL_ano",
                confianca="a_confirmar",
                observacao="Consulte o CRP-03.",
                fonte="CRP-03",
                nota_interna="CANDIDATO 4242.00",
            ),
        ]

        resp = _get(client, mocker, rows)

        body = resp.get_json()
        assert resp.status_code == 200
        assert "nota_interna" not in resp.get_data(as_text=True)
        assert "4242" not in resp.get_data(as_text=True)
        assert [p["tributo"] for p in body["parametros"]] == ["iss"]
        escalonado = next(e for e in body["escalonar"] if e["motivo"] == "a_confirmar")
        assert escalonado == {
            "tributo": "anuidade_pf",
            "motivo": "a_confirmar",
            "chave": "cons.ba.anuidade_pf.pf.psicologo",
            "observacao": "Consulte o CRP-03.",
            "fonte": "CRP-03",
        }
        assert "valor" not in escalonado

    def test_valores_numericos_saem_como_numero_e_datas_como_iso(self, client, mocker):
        _mock_db(mocker)

        resp = _get(client, mocker, [_row()])

        parametro = resp.get_json()["parametros"][0]
        assert parametro["valor"] == 1395.96
        assert isinstance(parametro["valor"], float)
        assert parametro["cotas"] == ["2026-06-30"]
        assert parametro["vigencia_ate"] == "2026-12-31"

    def test_nao_incidencia_fica_em_parametros_com_valor_nulo(self, client, mocker):
        _mock_db(mocker)
        row = _row(tipo_base="nao_incidencia", valor=None, base_calculo=None, aliquota_pct=None)

        resp = _get(client, mocker, [row], consultorio_fixo="false")

        parametro = resp.get_json()["parametros"][0]
        assert parametro["tipo_base"] == "nao_incidencia"
        assert parametro["valor"] is None

    def test_tributo_esperado_sem_linha_vira_sem_dado(self, client, mocker):
        _mock_db(mocker)

        resp = _get(client, mocker, [_row()], profissao="dentista", consultorio_fixo=None)

        sem_dado = {e["tributo"]: e for e in resp.get_json()["escalonar"] if e["motivo"] == "sem_dado"}
        assert "visa" in sem_dado
        assert sem_dado["visa"]["observacao"] is None
        assert "iss" not in sem_dado

    def test_perfil_ecoa_parametros_normalizados(self, client, mocker):
        _mock_db(mocker)

        resp = _get(client, mocker, [])

        assert resp.get_json()["perfil"] == {
            "municipio_ibge": SALVADOR,
            "profissao": "psicologo",
            "regime": "pf",
            "consultorio_fixo": True,
            "data": "2026-11-04",
        }


class TestCache:
    def test_segunda_chamada_identica_nao_consulta_o_banco(self, client, mocker):
        _mock_db(mocker)
        list_mock = mocker.patch("src.routes.parametros_fiscais.q.list_parametros", return_value=[_row()])
        query = {"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "data": "2026-11-04"}

        r1 = client.get(ENDPOINT, query_string=query)
        r2 = client.get(ENDPOINT, query_string=query)

        assert r1.get_json() == r2.get_json()
        list_mock.assert_called_once()

    def test_resultado_vazio_tambem_e_cacheado(self, client, mocker):
        _mock_db(mocker)
        list_mock = mocker.patch("src.routes.parametros_fiscais.q.list_parametros", return_value=[])
        query = {"municipio_ibge": RIO, "profissao": "medico", "regime": "pf", "data": "2026-11-04"}

        client.get(ENDPOINT, query_string=query)
        resp = client.get(ENDPOINT, query_string=query)

        assert resp.status_code == 200
        list_mock.assert_called_once()

    def test_erro_nao_e_cacheado(self, client, mocker):
        _mock_db(mocker)
        list_mock = mocker.patch(
            "src.routes.parametros_fiscais.q.list_parametros",
            side_effect=[RuntimeError("banco fora"), [_row()]],
        )
        query = {"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "data": "2026-11-04"}

        with pytest.raises(RuntimeError):
            client.get(ENDPOINT, query_string=query)
        resp = client.get(ENDPOINT, query_string=query)

        assert resp.status_code == 200
        assert list_mock.call_count == 2


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self, cursor_factory=None):
        return self.cursor_obj


class TestQuery:
    def test_sql_nao_seleciona_colunas_internas(self):
        conn = _FakeConn([])

        q.list_parametros(conn, SALVADOR, "psicologo", "pf", None, date(2026, 11, 4))

        assert "nota_interna" not in conn.cursor_obj.sql
        assert "carga" not in conn.cursor_obj.sql
        assert "id," not in conn.cursor_obj.sql

    def test_filtro_de_consultorio_so_entra_quando_informado(self):
        conn = _FakeConn([])

        q.list_parametros(conn, SALVADOR, "psicologo", "pf", None, date(2026, 11, 4))
        assert "autonomo_estabelecido = " not in conn.cursor_obj.sql
        assert "consultorio_fixo" not in conn.cursor_obj.params

        q.list_parametros(conn, SALVADOR, "psicologo", "pf", False, date(2026, 11, 4))
        assert "autonomo_estabelecido = " in conn.cursor_obj.sql
        assert conn.cursor_obj.params["consultorio_fixo"] is False

    def test_parametros_vao_como_bind_nao_como_f_string(self):
        conn = _FakeConn([])

        q.list_parametros(conn, RIO, "medico", "pj", None, date(2026, 11, 4))

        assert conn.cursor_obj.params["uf"] == "RJ"
        assert conn.cursor_obj.params["regimes"] == ["pj", "pf_pj"]
        assert "medico" not in conn.cursor_obj.sql

    def test_exclui_iss_de_nivel_nao_superior(self):
        conn = _FakeConn([
            {"tributo": "iss", "enquadramento": "16.2"},
            {"tributo": "iss", "enquadramento": "16.1"},
        ])

        rows = q.list_parametros(conn, SALVADOR, "psicologo", "pf", None, date(2026, 11, 4))

        assert [r["enquadramento"] for r in rows] == ["16.1"]

    def test_tributos_esperados_por_municipio_e_regime(self):
        assert q.tributos_esperados(SALVADOR, "pf") == (
            "inss_ci", "receita_saude", "irpf", "anuidade_pf", "iss", "tff", "tll", "visa",
        )
        assert q.tributos_esperados(SALVADOR, "mei") == ("mei",)
        assert "tls" in q.tributos_esperados(RIO, "pj")


# Cenários do briefing com a carga rev183 real. Pulados sem a URL de um banco de teste
# com public.parametro_fiscal carregada (nunca rodar contra STG/PRD a partir daqui).
INTEGRACAO_DB = os.environ.get("PARAMETROS_FISCAIS_TEST_DATABASE_URL")


@pytest.mark.skipif(not INTEGRACAO_DB, reason="PARAMETROS_FISCAIS_TEST_DATABASE_URL não definida")
class TestCargaRev183:
    @pytest.fixture
    def db_real(self, client, mocker):
        conn = psycopg2.connect(INTEGRACAO_DB)

        @contextmanager
        def _conn():
            yield conn

        mocker.patch("src.routes.parametros_fiscais.get_db_conn", side_effect=_conn)
        yield client
        conn.close()

    def _consulta(self, client, **params):
        query = {"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "data": "2026-11-04", **params}
        resp = client.get(ENDPOINT, query_string=query)
        assert resp.status_code == 200
        return resp.get_json()

    @staticmethod
    def _valor(body, tributo, enquadramento=None):
        return next(
            p["valor"] for p in body["parametros"]
            if p["tributo"] == tributo and (enquadramento is None or p["enquadramento"] == enquadramento)
        )

    def test_salvador_psicologo_consultorio_fixo(self, db_real):
        body = self._consulta(db_real, consultorio_fixo="true")

        assert self._valor(body, "iss", "16.1") == 1395.96
        assert self._valor(body, "tff") == 1395.96
        assert self._valor(body, "tll") == 167.23
        assert self._valor(body, "visa") == 227.44
        anuidade = next(e for e in body["escalonar"] if e["tributo"] == "anuidade_pf")
        assert anuidade["motivo"] == "a_confirmar"
        assert "valor" not in anuidade

    def test_salvador_dentista_visa_sem_dado(self, db_real):
        body = self._consulta(db_real, profissao="dentista")

        assert any(e["tributo"] == "visa" and e["motivo"] == "sem_dado" for e in body["escalonar"])
        assert self._valor(body, "anuidade_pf") == 547.93

    def test_rio_psicologo_iss_depende_do_consultorio(self, db_real):
        com = self._consulta(db_real, municipio_ibge=RIO, consultorio_fixo="true")
        sem = self._consulta(db_real, municipio_ibge=RIO, consultorio_fixo="false")

        assert self._valor(com, "iss") == 124.31
        iss_sem = next(p for p in sem["parametros"] if p["tributo"] == "iss")
        assert iss_sem["tipo_base"] == "nao_incidencia"
        assert iss_sem["valor"] is None

    def test_rio_medico_tls_sem_dado(self, db_real):
        body = self._consulta(db_real, municipio_ibge=RIO, profissao="medico")

        assert any(e["tributo"] == "tls" and e["motivo"] == "sem_dado" for e in body["escalonar"])

    def test_mei_limite_e_anuidade_na_data_do_briefing(self, db_real):
        mei = self._consulta(db_real, regime="mei", data="2027-01-15", profissao="medico")
        pf = self._consulta(db_real, profissao="medico", data="2027-01-15")

        limite = next(p for p in mei["parametros"] if p["tipo_base"] == "limite")
        assert limite["valor"] == 110000
        assert self._valor(pf, "anuidade_pf") == 989.00

    def test_nota_interna_nunca_aparece_nas_respostas(self, db_real):
        for params in (
            {"consultorio_fixo": "true"},
            {"profissao": "dentista"},
            {"municipio_ibge": RIO, "consultorio_fixo": "false"},
            {"regime": "mei", "profissao": "medico"},
        ):
            resp = db_real.get(ENDPOINT, query_string={"municipio_ibge": SALVADOR, "profissao": "psicologo", "regime": "pf", "data": "2026-11-04", **params})
            assert "nota_interna" not in resp.get_data(as_text=True)
            for e in resp.get_json()["escalonar"]:
                if e["motivo"] == "a_confirmar":
                    assert "valor" not in e

    def test_segunda_chamada_nao_consulta_o_banco(self, db_real, mocker):
        spy = mocker.spy(q, "list_parametros")

        self._consulta(db_real)
        self._consulta(db_real)

        spy.assert_called_once()
