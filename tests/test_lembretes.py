import psycopg2
import pytest


class TestLembretesDue:
    def test_due_vazio(self, client, mock_db_conn, mocker):
        _, conn = mock_db_conn("src.routes.lembretes.get_db_conn")
        list_mock = mocker.patch("src.routes.lembretes.q.list_due", return_value=[])
        retry_mock = mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=lambda fn, **_: fn(),
        )

        resp = client.get("/lembretes/due")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"items": [], "count": 0, "window_minutes": 2}
        list_mock.assert_called_once_with(conn, window_minutes=2)
        retry_mock.assert_called_once()

    def test_due_com_item(self, client, mock_db_conn, mocker):
        _, conn = mock_db_conn("src.routes.lembretes.get_db_conn")
        item = {
            "id": 42,
            "usuario_id": 7,
            "nome_compromisso": "INSS",
            "hora_compromisso": "09:00:00",
            "status": "confirmado",
            "numero_telefone": "5511999999999",
            "data_compromisso": "2026-10-05",
        }
        mocker.patch("src.routes.lembretes.q.list_due", return_value=[item])
        mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=lambda fn, **_: fn(),
        )

        resp = client.get("/lembretes/due?window_minutes=2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["count"] == 1
        assert body["items"][0]["id"] == 42

    def test_window_minutes_invalido(self, client):
        resp = client.get("/lembretes/due?window_minutes=abc")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_request"

    def test_retry_propaga_operational_error(self, client, mocker):
        mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=psycopg2.OperationalError("connection timeout"),
        )
        with pytest.raises(psycopg2.OperationalError):
            client.get("/lembretes/due")


class TestLembretesMarcarEnviado:
    def test_marca_novo(self, client, mock_db_conn, mocker):
        _, conn = mock_db_conn("src.routes.lembretes.get_db_conn")
        mark_mock = mocker.patch(
            "src.routes.lembretes.q.mark_enviado",
            return_value={
                "id": 10,
                "usuario_id": 3,
                "nome_compromisso": "Reunião",
                "lembrete_enviado": True,
                "already_sent": False,
            },
        )
        mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=lambda fn, **_: fn(),
        )
        inv_mock = mocker.patch("src.routes.lembretes.cache_invalidate_prefix")

        resp = client.post("/lembretes/10/enviado")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["id"] == 10
        assert body["already_sent"] is False
        mark_mock.assert_called_once_with(conn, 10)
        inv_mock.assert_called_once_with("agendamentos", "3:")

    def test_idempotente_ja_enviado(self, client, mock_db_conn, mocker):
        _, conn = mock_db_conn("src.routes.lembretes.get_db_conn")
        mocker.patch(
            "src.routes.lembretes.q.mark_enviado",
            return_value={
                "id": 10,
                "usuario_id": 3,
                "nome_compromisso": "Reunião",
                "lembrete_enviado": True,
                "found": True,
                "already_sent": True,
            },
        )
        mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=lambda fn, **_: fn(),
        )
        inv_mock = mocker.patch("src.routes.lembretes.cache_invalidate_prefix")

        resp = client.post("/lembretes/10/enviado")

        assert resp.status_code == 200
        assert resp.get_json()["already_sent"] is True
        inv_mock.assert_called_once()

    def test_nao_encontrado(self, client, mock_db_conn, mocker):
        mock_db_conn("src.routes.lembretes.get_db_conn")
        mocker.patch(
            "src.routes.lembretes.q.mark_enviado",
            return_value={"found": False},
        )
        mocker.patch(
            "src.routes.lembretes.run_db_with_retry",
            side_effect=lambda fn, **_: fn(),
        )

        resp = client.post("/lembretes/999/enviado")

        assert resp.status_code == 404
        assert resp.get_json()["error"] == "agendamento_nao_encontrado"
