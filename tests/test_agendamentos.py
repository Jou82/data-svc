from datetime import date, timedelta

from src.config import Config


class TestListAgendamentos:
    def test_lista_compromissos_futuros_com_scope_future(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=9)).isoformat()
        agendamentos_fake = [
            {
                "id": 9,
                "nome_compromisso": "Follow-up comercial",
                "data_compromisso": data_futura,
                "hora_compromisso": "15:30",
                "status": "agendado",
            }
        ]
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cache_get_mock = mocker.patch("src.routes.agendamentos.cache_get", return_value=None)
        list_mock = mocker.patch("src.routes.agendamentos.q.list_agendamentos", return_value=agendamentos_fake)
        cache_set_mock = mocker.patch("src.routes.agendamentos.cache_set")

        resp = client.get(f"/usuarios/{usuario_id}/agendamentos?scope=future")

        assert resp.status_code == 200
        assert resp.get_json() == agendamentos_fake
        cache_get_mock.assert_called_once_with("agendamentos", f"{usuario_id}:future")
        list_mock.assert_called_once_with(conn, usuario_id)
        cache_set_mock.assert_called_once_with(
            "agendamentos",
            f"{usuario_id}:future",
            agendamentos_fake,
            Config.CACHE_TTL_AGENDAMENTOS,
        )

    def test_usa_cache_na_segunda_chamada(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=9)).isoformat()
        agendamentos_fake = [
            {
                "id": 9,
                "nome_compromisso": "Follow-up comercial",
                "data_compromisso": data_futura,
                "hora_compromisso": "15:30",
                "status": "agendado",
            }
        ]
        get_db_conn_mock, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cache_get_mock = mocker.patch(
            "src.routes.agendamentos.cache_get",
            side_effect=[None, agendamentos_fake],
        )
        list_mock = mocker.patch("src.routes.agendamentos.q.list_agendamentos", return_value=agendamentos_fake)
        mocker.patch("src.routes.agendamentos.cache_set")

        resp_1 = client.get(f"/usuarios/{usuario_id}/agendamentos?scope=future")
        resp_2 = client.get(f"/usuarios/{usuario_id}/agendamentos?scope=future")

        assert resp_1.status_code == 200
        assert resp_2.status_code == 200
        assert resp_1.get_json() == agendamentos_fake
        assert resp_2.get_json() == agendamentos_fake
        assert cache_get_mock.call_count == 2
        list_mock.assert_called_once_with(conn, usuario_id)
        get_db_conn_mock.assert_called_once()

    def test_retorna_400_sem_scope(self, client):
        resp = client.get("/usuarios/1/agendamentos")

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "parâmetro 'scope' inválido" in data["detail"]

    def test_retorna_400_para_scope_invalido(self, client):
        resp = client.get("/usuarios/1/agendamentos?scope=week")

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "parâmetro 'scope' inválido" in data["detail"]


class TestCreateAgendamento:
    def test_cria_compromisso(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=2)).isoformat()
        payload = {
            "nome_compromisso": "Call de fechamento",
            "data_compromisso": data_futura,
            "hora_compromisso": "23:59",
        }
        agendamento_fake = {
            "id": 20,
            "nome_compromisso": payload["nome_compromisso"],
            "data_compromisso": data_futura,
            "hora_compromisso": "23:59",
            "status": "confirmado",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        create_mock = mocker.patch("src.routes.agendamentos.q.create", return_value=agendamento_fake)
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos", json=payload)

        assert resp.status_code == 201
        assert resp.get_json() == agendamento_fake
        # O validador preenche o default de lembrete (15 min) antes de chamar q.create.
        create_mock.assert_called_once_with(conn, usuario_id, {**payload, "lembrete_minutos_antes": 15})
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_400_sem_campos_obrigatorios(self, client):
        resp = client.post("/usuarios/1/agendamentos", json={})

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "campos obrigatórios ausentes" in data["detail"]

    def test_invalida_cache_apos_criacao(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=2)).isoformat()
        payload = {
            "nome_compromisso": "Revisão de proposta",
            "data_compromisso": data_futura,
            "hora_compromisso": "23:59",
        }

        mock_db_conn("src.routes.agendamentos.get_db_conn")
        mocker.patch("src.routes.agendamentos.q.create", return_value={"id": 21, "status": "confirmado"})
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos", json=payload)

        assert resp.status_code == 201
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")


class TestUpdateAgendamento:
    def test_atualiza_status_apenas(self, client, mock_db_conn, mocker):
        usuario_id = 1
        agendamento_id = 5
        payload = {"status": "cancelado"}
        agendamento_atualizado = {
            "id": agendamento_id,
            "nome_compromisso": "Reunião com cliente",
            "data_compromisso": "2026-05-10",
            "hora_compromisso": "15:00",
            "status": "cancelado",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        update_mock = mocker.patch(
            "src.routes.agendamentos.q.update",
            return_value=agendamento_atualizado,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json=payload,
        )

        assert resp.status_code == 200
        assert resp.get_json() == agendamento_atualizado
        update_mock.assert_called_once_with(conn, agendamento_id, usuario_id, {"status": "cancelado"})
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_atualiza_nome_compromisso_apenas(self, client, mock_db_conn, mocker):
        usuario_id = 1
        agendamento_id = 5
        payload = {"nome_compromisso": "Novo nome do compromisso"}
        agendamento_atualizado = {
            "id": agendamento_id,
            "nome_compromisso": "Novo nome do compromisso",
            "data_compromisso": "2026-05-10",
            "hora_compromisso": "15:00",
            "status": "confirmado",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        update_mock = mocker.patch(
            "src.routes.agendamentos.q.update",
            return_value=agendamento_atualizado,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json=payload,
        )

        assert resp.status_code == 200
        assert resp.get_json() == agendamento_atualizado
        update_mock.assert_called_once_with(conn, agendamento_id, usuario_id, {"nome_compromisso": "Novo nome do compromisso"})
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_atualiza_multiplos_campos(self, client, mock_db_conn, mocker):
        usuario_id = 1
        agendamento_id = 5
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        payload = {
            "nome_compromisso": "Novo compromisso",
            "data_compromisso": data_futura,
            "hora_compromisso": "10:30",
            "status": "agendado",
        }
        agendamento_atualizado = {
            "id": agendamento_id,
            "nome_compromisso": "Novo compromisso",
            "data_compromisso": data_futura,
            "hora_compromisso": "10:30",
            "status": "agendado",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        update_mock = mocker.patch(
            "src.routes.agendamentos.q.update",
            return_value=agendamento_atualizado,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json=payload,
        )

        assert resp.status_code == 200
        assert resp.get_json() == agendamento_atualizado
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_404_agendamento_inexistente(self, client, mock_db_conn, mocker):
        usuario_id = 1
        agendamento_id = 999
        payload = {"status": "confirmado"}
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        update_mock = mocker.patch("src.routes.agendamentos.q.update", return_value=None)
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json=payload,
        )

        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "agendamento_nao_encontrado"
        assert str(agendamento_id) in data["detail"]
        invalidate_prefix_mock.assert_not_called()

    def test_retorna_400_body_vazio(self, client):
        usuario_id = 1
        agendamento_id = 5

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json={},
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "body" in data["detail"].lower() or "campo" in data["detail"].lower()

    def test_retorna_400_status_invalido(self, client):
        usuario_id = 1
        agendamento_id = 5

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json={"status": "invalido"},
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "status" in data["detail"].lower()

    def test_retorna_400_data_no_passado(self, client):
        usuario_id = 1
        agendamento_id = 5
        data_passada = (date.today() - timedelta(days=1)).isoformat()

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json={"data_compromisso": data_passada},
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "passado" in data["detail"].lower()

    def test_retorna_400_hora_invalida(self, client):
        usuario_id = 1
        agendamento_id = 5

        resp = client.put(
            f"/usuarios/{usuario_id}/agendamentos/{agendamento_id}",
            json={"hora_compromisso": "25:00"},
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "hora_compromisso" in data["detail"].lower()


class TestCancelAllAgendamentos:
    def test_cancela_todos_agendamentos_ativos(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        agendamentos_cancelados = [
            {
                "nome_compromisso": "Reunião com gerente",
                "data_compromisso": data_futura,
                "hora_compromisso": "10:00",
            },
            {
                "nome_compromisso": "Ligação de acompanhamento",
                "data_compromisso": data_futura,
                "hora_compromisso": "14:30",
            },
        ]
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cancel_all_mock = mocker.patch(
            "src.routes.agendamentos.q.cancel_all",
            return_value=agendamentos_cancelados,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos")

        assert resp.status_code == 200
        assert resp.get_json() == agendamentos_cancelados
        cancel_all_mock.assert_called_once_with(conn, usuario_id)
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_lista_vazia_sem_agendamentos_ativos(self, client, mock_db_conn, mocker):
        usuario_id = 1
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cancel_all_mock = mocker.patch(
            "src.routes.agendamentos.q.cancel_all",
            return_value=[],
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos")

        assert resp.status_code == 200
        assert resp.get_json() == []
        cancel_all_mock.assert_called_once_with(conn, usuario_id)
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_invalida_cache_apos_cancelamento_em_massa(self, client, mock_db_conn, mocker):
        usuario_id = 1
        agendamentos_cancelados = [
            {
                "nome_compromisso": "Compromisso 1",
                "data_compromisso": (date.today() + timedelta(days=3)).isoformat(),
                "hora_compromisso": "09:00",
            },
        ]
        mock_db_conn("src.routes.agendamentos.get_db_conn")
        mocker.patch("src.routes.agendamentos.q.cancel_all", return_value=agendamentos_cancelados)
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos")

        assert resp.status_code == 200
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")


class TestCancelRecurrence:
    def test_cancela_agendamentos_recorrentes(self, client, mock_db_conn, mocker):
        usuario_id = 1
        recorrencia_id = "550e8400-e29b-41d4-a716-446655440000"
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        agendamentos_cancelados = [
            {
                "nome_compromisso": "Reunião semanal",
                "data_compromisso": data_futura,
                "hora_compromisso": "10:00",
            },
            {
                "nome_compromisso": "Reunião semanal",
                "data_compromisso": (date.today() + timedelta(days=12)).isoformat(),
                "hora_compromisso": "10:00",
            },
        ]
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cancel_recurrence_mock = mocker.patch(
            "src.routes.agendamentos.q.cancel_recurrence",
            return_value=agendamentos_cancelados,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos/recorrencia/{recorrencia_id}")

        assert resp.status_code == 200
        assert resp.get_json() == agendamentos_cancelados
        cancel_recurrence_mock.assert_called_once_with(conn, usuario_id, recorrencia_id)
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_lista_vazia_sem_recorrencia(self, client, mock_db_conn, mocker):
        usuario_id = 1
        recorrencia_id = "550e8400-e29b-41d4-a716-446655440001"
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        cancel_recurrence_mock = mocker.patch(
            "src.routes.agendamentos.q.cancel_recurrence",
            return_value=[],
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos/recorrencia/{recorrencia_id}")

        assert resp.status_code == 200
        assert resp.get_json() == []
        cancel_recurrence_mock.assert_called_once_with(conn, usuario_id, recorrencia_id)
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_invalida_cache_apos_cancelamento_recorrencia(self, client, mock_db_conn, mocker):
        usuario_id = 1
        recorrencia_id = "550e8400-e29b-41d4-a716-446655440002"
        agendamentos_cancelados = [
            {
                "nome_compromisso": "Reunião mensal",
                "data_compromisso": (date.today() + timedelta(days=7)).isoformat(),
                "hora_compromisso": "14:00",
            },
        ]
        mock_db_conn("src.routes.agendamentos.get_db_conn")
        mocker.patch("src.routes.agendamentos.q.cancel_recurrence", return_value=agendamentos_cancelados)
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.delete(f"/usuarios/{usuario_id}/agendamentos/recorrencia/{recorrencia_id}")

        assert resp.status_code == 200
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")


class TestCreateRecurrence:
    def test_cria_agendamentos_recorrentes_semanais(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião semanal",
            "data_inicio": data_inicio,
            "hora_compromisso": "10:00",
            "frequencia": "semanal",
            "dia_semana_ou_mes": "seg",
            "quantidade_meses": 1,
        }
        agendamentos_fake = [
            {
                "id": 100,
                "nome_compromisso": "Reunião semanal",
                "data_compromisso": data_inicio,
                "hora_compromisso": "10:00",
                "status": "confirmado",
                "recorrencia_id": "uuid-123",
            },
            {
                "id": 101,
                "nome_compromisso": "Reunião semanal",
                "data_compromisso": (date.today() + timedelta(days=8)).isoformat(),
                "hora_compromisso": "10:00",
                "status": "confirmado",
                "recorrencia_id": "uuid-123",
            },
        ]
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        create_recurrence_mock = mocker.patch(
            "src.routes.agendamentos.q.create_recurrence",
            return_value=agendamentos_fake,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 201
        assert resp.get_json() == agendamentos_fake
        create_recurrence_mock.assert_called_once()
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_400_sem_campos_obrigatorios(self, client):
        usuario_id = 1
        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json={})

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"

    def test_retorna_400_frequencia_invalida(self, client):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião",
            "data_inicio": data_inicio,
            "hora_compromisso": "10:00",
            "frequencia": "diaria",
            "dia_semana_ou_mes": "seg",
            "quantidade_meses": 1,
        }

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert "frequencia" in data["detail"].lower()

    def test_retorna_400_quantidade_meses_invalida(self, client):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião",
            "data_inicio": data_inicio,
            "hora_compromisso": "10:00",
            "frequencia": "semanal",
            "dia_semana_ou_mes": "seg",
            "quantidade_meses": 13,
        }

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert "quantidade_meses" in data["detail"].lower()

    def test_cria_agendamentos_recorrentes_mensais(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião mensal",
            "data_inicio": data_inicio,
            "hora_compromisso": "15:00",
            "frequencia": "mensal",
            "dia_semana_ou_mes": "15",
            "quantidade_meses": 3,
        }
        agendamentos_fake = [
            {
                "id": 200,
                "nome_compromisso": "Reunião mensal",
                "data_compromisso": data_inicio,
                "hora_compromisso": "15:00",
                "status": "confirmado",
                "recorrencia_id": "uuid-456",
            },
        ]
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        create_recurrence_mock = mocker.patch(
            "src.routes.agendamentos.q.create_recurrence",
            return_value=agendamentos_fake,
        )
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 201
        assert resp.get_json() == agendamentos_fake
        create_recurrence_mock.assert_called_once()
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")

    def test_retorna_400_dia_semana_invalido(self, client):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião",
            "data_inicio": data_inicio,
            "hora_compromisso": "10:00",
            "frequencia": "semanal",
            "dia_semana_ou_mes": "seg2",
            "quantidade_meses": 1,
        }

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert "dia_semana" in data["detail"].lower() or "inválid" in data["detail"].lower()

    def test_retorna_400_data_inicio_no_passado(self, client):
        usuario_id = 1
        data_passada = (date.today() - timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião",
            "data_inicio": data_passada,
            "hora_compromisso": "10:00",
            "frequencia": "semanal",
            "dia_semana_ou_mes": "seg",
            "quantidade_meses": 1,
        }

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert "passado" in data["detail"].lower()

    def test_invalida_cache_apos_criacao_recorrencia(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_inicio = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "nome_compromisso": "Reunião",
            "data_inicio": data_inicio,
            "hora_compromisso": "10:00",
            "frequencia": "semanal",
            "dia_semana_ou_mes": "seg",
            "quantidade_meses": 1,
        }
        mock_db_conn("src.routes.agendamentos.get_db_conn")
        mocker.patch("src.routes.agendamentos.q.create_recurrence", return_value=[])
        invalidate_prefix_mock = mocker.patch("src.routes.agendamentos.cache_invalidate_prefix")

        resp = client.post(f"/usuarios/{usuario_id}/agendamentos/recorrentes", json=payload)

        assert resp.status_code == 201
        invalidate_prefix_mock.assert_called_once_with("agendamentos", f"{usuario_id}:")


class TestCheckConflicts:
    def test_detecta_conflito_existente(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        conflito_result = {
            "conflito": True,
            "total": 1,
            "descricao": "Reunião com cliente às 10:00",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        check_conflicts_mock = mocker.patch(
            "src.routes.agendamentos.q.check_conflicts",
            return_value=conflito_result,
        )

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_futura}&hora=10:00&nome_compromisso=Reunião"
        )

        assert resp.status_code == 200
        assert resp.get_json() == conflito_result
        check_conflicts_mock.assert_called_once()

    def test_retorna_sem_conflito(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        sem_conflito_result = {
            "conflito": False,
            "total": 0,
            "descricao": None,
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        check_conflicts_mock = mocker.patch(
            "src.routes.agendamentos.q.check_conflicts",
            return_value=sem_conflito_result,
        )

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_futura}&hora=15:00&nome_compromisso=Nova Reunião"
        )

        assert resp.status_code == 200
        assert resp.get_json() == sem_conflito_result

    def test_retorna_400_sem_parametros(self, client):
        usuario_id = 1

        resp = client.get(f"/usuarios/{usuario_id}/agendamentos/conflitos")

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "bad_request"
        assert "obrigatório" in data["detail"].lower()

    def test_retorna_400_data_invalida(self, client):
        usuario_id = 1

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data=2026-13-45&hora=10:00&nome_compromisso=Reunião"
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "data" in data["detail"].lower()

    def test_retorna_400_hora_invalida(self, client):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_futura}&hora=25:99&nome_compromisso=Reunião"
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "hora" in data["detail"].lower()

    def test_retorna_400_nome_vazio(self, client):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_futura}&hora=10:00&nome_compromisso="
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "nome_compromisso" in data["detail"].lower()

    def test_retorna_400_data_passada(self, client):
        usuario_id = 1
        data_passada = (date.today() - timedelta(days=1)).isoformat()

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_passada}&hora=10:00&nome_compromisso=Reunião"
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "passado" in data["detail"].lower()

    def test_detecta_multiplos_conflitos(self, client, mock_db_conn, mocker):
        usuario_id = 1
        data_futura = (date.today() + timedelta(days=5)).isoformat()
        multiplos_conflitos = {
            "conflito": True,
            "total": 2,
            "descricao": "Reunião com cliente às 10:00, Reunião de Sprint às 10:15",
        }
        _, conn = mock_db_conn("src.routes.agendamentos.get_db_conn")

        check_conflicts_mock = mocker.patch(
            "src.routes.agendamentos.q.check_conflicts",
            return_value=multiplos_conflitos,
        )

        resp = client.get(
            f"/usuarios/{usuario_id}/agendamentos/conflitos?"
            f"data={data_futura}&hora=10:00&nome_compromisso=Reunião"
        )

        assert resp.status_code == 200
        assert resp.get_json()["total"] == 2
        assert resp.get_json()["conflito"] is True
