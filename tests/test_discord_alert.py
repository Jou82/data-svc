import json
import urllib.error

import psycopg2
import pytest

from src.utils import discord_alert, db_retry
from src.config import Config


class TestFormatContent:
    def test_truncates_and_prefixes(self):
        content = discord_alert.format_content(
            source="data-svc",
            reason="db_retry esgotado",
            detail="x" * 2000,
        )
        assert content.startswith("**MEIrelles data-svc**")
        assert "db_retry esgotado" in content
        assert len(content) <= 1900


class TestSendDiscordAlert:
    def test_disabled_when_url_empty(self, mocker):
        mocker.patch.object(Config, "DISCORD_ALERT_WEBHOOK_URL", "")
        urlopen = mocker.patch("src.utils.discord_alert.urllib.request.urlopen")
        assert discord_alert.send_discord_alert(source="data-svc", reason="x") is False
        urlopen.assert_not_called()

    def test_posts_content_json(self, mocker):
        mocker.patch.object(Config, "DISCORD_ALERT_WEBHOOK_URL", "https://discord.example/hook")
        resp = mocker.Mock()
        resp.status = 204
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        urlopen = mocker.patch(
            "src.utils.discord_alert.urllib.request.urlopen",
            return_value=resp,
        )

        ok = discord_alert.send_discord_alert(
            source="data-svc",
            reason="db_retry esgotado op=`lembretes_due`",
            detail="OperationalError: timeout",
        )

        assert ok is True
        req = urlopen.call_args[0][0]
        body = json.loads(req.data.decode())
        assert "content" in body
        assert "MEIrelles data-svc" in body["content"]
        assert "lembretes_due" in body["content"]

    def test_fail_open_on_network_error(self, mocker):
        mocker.patch.object(Config, "DISCORD_ALERT_WEBHOOK_URL", "https://discord.example/hook")
        mocker.patch(
            "src.utils.discord_alert.urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        )
        assert discord_alert.send_discord_alert(source="data-svc", reason="x") is False


class TestDbRetryAlerts:
    def test_alert_on_retry_exhausted(self, mocker):
        alert = mocker.patch("src.utils.db_retry.send_discord_alert", return_value=True)
        mocker.patch("src.utils.db_retry.time.sleep")

        def boom():
            raise psycopg2.OperationalError("connection timeout")

        with pytest.raises(psycopg2.OperationalError):
            db_retry.run_db_with_retry(boom, max_attempts=3, operation="lembretes_due")

        alert.assert_called_once()
        kwargs = alert.call_args.kwargs
        assert kwargs["source"] == "data-svc"
        assert "lembretes_due" in kwargs["reason"]
        assert "OperationalError" in kwargs["detail"]

    def test_no_alert_on_success_after_retry(self, mocker):
        alert = mocker.patch("src.utils.db_retry.send_discord_alert")
        mocker.patch("src.utils.db_retry.time.sleep")
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise psycopg2.OperationalError("brief")
            return "ok"

        assert db_retry.run_db_with_retry(flaky, max_attempts=3, operation="x") == "ok"
        alert.assert_not_called()
