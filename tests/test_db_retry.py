import psycopg2
import pytest

from src.utils import db_retry


class TestRunDbWithRetry:
    def test_sucesso_na_primeira_tentativa(self, mocker):
        fn = mocker.Mock(return_value=["ok"])
        assert db_retry.run_db_with_retry(fn, operation="test") == ["ok"]
        fn.assert_called_once()

    def test_retenta_operational_error_e_sucede(self, mocker):
        fn = mocker.Mock(
            side_effect=[
                psycopg2.OperationalError("timeout"),
                {"id": 1},
            ]
        )
        sleep = mocker.patch("src.utils.db_retry.time.sleep")
        out = db_retry.run_db_with_retry(fn, max_attempts=3, operation="test")
        assert out == {"id": 1}
        assert fn.call_count == 2
        sleep.assert_called_once()

    def test_esgota_tentativas(self, mocker):
        fn = mocker.Mock(side_effect=psycopg2.OperationalError("timeout"))
        mocker.patch("src.utils.db_retry.time.sleep")
        with pytest.raises(psycopg2.OperationalError):
            db_retry.run_db_with_retry(fn, max_attempts=2, operation="test")
        assert fn.call_count == 2
