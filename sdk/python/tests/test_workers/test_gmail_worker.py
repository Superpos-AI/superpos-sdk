"""Tests for GmailWorker."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from superpos_sdk.workers.gmail import GmailWorker

BASE_URL = "https://superpos.test"
HIVE_ID = "01HXYZ00000000000000000001"

# Minimal fake service account JSON
FAKE_CREDS_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "test",
        "private_key_id": "key1",
        "private_key": (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4PAtesbbOl2n1nOHb0m5ueEMrwV\n"
            "-----END RSA PRIVATE KEY-----\n"
        ),
        "client_email": "test@test.iam.gserviceaccount.com",
        "client_id": "123456",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


def _worker() -> GmailWorker:
    return GmailWorker(BASE_URL, HIVE_ID, name="gmail-worker", secret="s3cr3t")


def _mock_service(messages_list=None, message_get=None, send_result=None, draft_result=None):
    """Build a mock Gmail service object."""
    svc = MagicMock()
    users = svc.users.return_value
    msgs = users.messages.return_value
    if messages_list is not None:
        msgs.list.return_value.execute.return_value = messages_list
    if message_get is not None:
        msgs.get.return_value.execute.return_value = message_get
    if send_result is not None:
        msgs.send.return_value.execute.return_value = send_result
    drafts = users.drafts.return_value
    if draft_result is not None:
        drafts.create.return_value.execute.return_value = draft_result
    return svc


class TestGmailWorkerCredentials:
    def test_missing_credentials_raises(self):
        worker = _worker()
        with pytest.raises(ValueError, match="GMAIL_CREDENTIALS"):
            worker.list_messages({"gmail_subject": "user@example.com"})

    def test_missing_subject_raises(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()
        # mock _creds so it doesn't call real google-auth
        err = ValueError("Gmail subject (impersonated user) not found")
        with patch.object(worker, "_creds", side_effect=err):
            with pytest.raises(ValueError, match="Gmail subject"):
                worker.list_messages({})

    def test_env_credentials_used(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        fake_svc = _mock_service(messages_list={"messages": [], "resultSizeEstimate": 0})
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.list_messages({})

        assert result["messages"] == []

    def test_payload_credentials_override(self, monkeypatch):
        """Credentials passed in params take precedence over env vars."""
        monkeypatch.setenv("GMAIL_CREDENTIALS", "env-value-that-should-not-be-used")
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        # Capture what credentials value was passed to _service
        captured = {}

        def fake_service(subject, credentials=None):
            captured["credentials"] = credentials
            return _mock_service(messages_list={"messages": [], "resultSizeEstimate": 0})

        with patch.object(worker, "_service", side_effect=fake_service):
            worker.list_messages({"credentials": FAKE_CREDS_JSON})

        assert captured["credentials"] == FAKE_CREDS_JSON

    def test_subject_param_is_impersonated_user(self, monkeypatch):
        """gmail_subject in params is used as impersonation target, not email subject."""
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        captured = {}

        def fake_service(subject, credentials=None):
            captured["subject"] = subject
            return _mock_service(messages_list={"messages": [], "resultSizeEstimate": 0})

        with patch.object(worker, "_service", side_effect=fake_service):
            worker.list_messages({"gmail_subject": "admin@corp.com"})

        assert captured["subject"] == "admin@corp.com"


class TestGmailWorkerSendMessageSubjectAmbiguity:
    """The critical bug: 'subject' must be the email subject line, not the impersonated user."""

    def test_send_uses_gmail_subject_for_impersonation(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        captured = {}

        def fake_service(subject, credentials=None):
            captured["impersonated"] = subject
            return _mock_service(send_result={"id": "msg1", "threadId": "t1"})

        with patch.object(worker, "_service", side_effect=fake_service):
            result = worker.send_message(
                {
                    "to": "recipient@example.com",
                    "subject": "Hello World",
                    "body": "Test body",
                    "gmail_subject": "sender@corp.com",
                }
            )

        # impersonation must be sender@corp.com, NOT "Hello World"
        assert captured["impersonated"] == "sender@corp.com"
        assert result["id"] == "msg1"

    def test_send_subject_used_as_email_header(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "sender@corp.com")
        worker = _worker()

        fake_svc = _mock_service(send_result={"id": "msg2", "threadId": "t2"})
        with patch.object(worker, "_service", return_value=fake_svc):
            worker.send_message(
                {
                    "to": "recipient@example.com",
                    "subject": "Hello World",
                    "body": "Test body",
                }
            )

        # Verify the MIME message contains "Hello World" as Subject header
        call_args = fake_svc.users.return_value.messages.return_value.send.call_args
        raw_b64 = call_args[1]["body"]["raw"]
        import base64

        decoded = base64.urlsafe_b64decode(raw_b64 + "==").decode()
        assert "Subject: Hello World" in decoded

    def test_create_draft_uses_gmail_subject_for_impersonation(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        worker = _worker()

        captured = {}

        def fake_service(subject, credentials=None):
            captured["impersonated"] = subject
            return _mock_service(draft_result={"id": "draft1", "message": {}})

        with patch.object(worker, "_service", side_effect=fake_service):
            worker.create_draft(
                {
                    "to": "recipient@example.com",
                    "subject": "Draft subject",
                    "body": "Draft body",
                    "gmail_subject": "drafter@corp.com",
                }
            )

        assert captured["impersonated"] == "drafter@corp.com"


class TestGmailWorkerListMessages:
    def test_returns_messages_shape(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        fake_svc = _mock_service(
            messages_list={
                "messages": [{"id": "1"}, {"id": "2"}],
                "resultSizeEstimate": 2,
                "nextPageToken": "tok123",
            }
        )
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.list_messages({"query": "is:unread"})

        assert len(result["messages"]) == 2
        assert result["result_size_estimate"] == 2
        assert result["next_page_token"] == "tok123"

    def test_empty_result(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        fake_svc = _mock_service(messages_list={"resultSizeEstimate": 0})
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.list_messages({})

        assert result["messages"] == []
        assert result["next_page_token"] is None


class TestGmailWorkerGetMessage:
    def test_get_message_returns_resource(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        msg = {"id": "abc123", "threadId": "t1", "labelIds": ["INBOX"], "snippet": "Hi"}
        fake_svc = _mock_service(message_get=msg)
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.get_message({"message_id": "abc123"})

        assert result["id"] == "abc123"

    def test_get_message_passes_format(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "user@example.com")
        worker = _worker()

        fake_svc = _mock_service(message_get={"id": "abc"})
        with patch.object(worker, "_service", return_value=fake_svc):
            worker.get_message({"message_id": "abc", "format": "metadata"})

        call_kwargs = fake_svc.users.return_value.messages.return_value.get.call_args[1]
        assert call_kwargs["format"] == "metadata"


class TestGmailWorkerSendMessage:
    def test_send_returns_message_resource(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "sender@corp.com")
        worker = _worker()

        fake_svc = _mock_service(send_result={"id": "msg1", "threadId": "t1"})
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.send_message(
                {
                    "to": "user@example.com",
                    "subject": "Test",
                    "body": "Hello",
                }
            )

        assert result["id"] == "msg1"
        assert result["threadId"] == "t1"

    def test_send_with_cc_bcc(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "sender@corp.com")
        worker = _worker()

        fake_svc = _mock_service(send_result={"id": "msg2", "threadId": "t2"})
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.send_message(
                {
                    "to": "to@example.com",
                    "subject": "CC test",
                    "body": "Body",
                    "cc": "cc@example.com",
                    "bcc": "bcc@example.com",
                }
            )

        assert result["id"] == "msg2"


class TestGmailWorkerCreateDraft:
    def test_create_draft_returns_draft_resource(self, monkeypatch):
        monkeypatch.setenv("GMAIL_CREDENTIALS", FAKE_CREDS_JSON)
        monkeypatch.setenv("GMAIL_SUBJECT", "sender@corp.com")
        worker = _worker()

        fake_svc = _mock_service(draft_result={"id": "draft1", "message": {"id": "m1"}})
        with patch.object(worker, "_service", return_value=fake_svc):
            result = worker.create_draft(
                {
                    "to": "user@example.com",
                    "subject": "Draft",
                    "body": "Draft body",
                }
            )

        assert result["id"] == "draft1"
