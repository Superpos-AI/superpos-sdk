"""Gmail service worker — interact with the Gmail API via a service account.

Install the optional dependency::

    pip install superpos-sdk[gmail]

Credentials (env-first, payload fallback):

- ``GMAIL_CREDENTIALS`` — JSON string of a Google service account key file,
  or a path to the key file.  The service account must have domain-wide
  delegation enabled and the Gmail API scopes granted.  Can also be passed
  per-task as ``credentials`` in the params dict.
- ``GMAIL_SUBJECT`` — email address to impersonate (required for service
  accounts).

Supported operations
--------------------

``list_messages``
    ``{"query": "is:unread", "max_results": 10, "gmail_subject": "user@example.com"}``

``get_message``
    ``{"message_id": "...", "gmail_subject": "user@example.com", "format": "full"}``

``send_message``
    ``{"to": "...", "subject": "...", "body": "...", "html": false,
       "cc": "...", "bcc": "...", "from_email": "user@example.com"}``

``create_draft``
    ``{"to": "...", "subject": "...", "body": "...", "html": false,
       "from_email": "user@example.com"}``
"""

from __future__ import annotations

import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from superpos_sdk.service_worker import ServiceWorker


class GmailWorker(ServiceWorker):
    """Service worker that proxies Gmail API calls via a service account.

    Credentials are read from the ``GMAIL_CREDENTIALS`` environment variable
    (JSON string or file path).  The impersonated user is taken from
    ``GMAIL_SUBJECT`` env var or the ``gmail_subject`` key in *params*.
    """

    CAPABILITY = "data:gmail"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _creds(self, subject: str, credentials: str | None = None) -> Any:
        """Return google-auth credentials scoped for Gmail."""
        try:
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "google-auth is required for GmailWorker. "
                "Install it with: pip install superpos-sdk[gmail]"
            ) from exc

        raw = credentials or os.environ.get("GMAIL_CREDENTIALS", "")
        if not raw:
            raise ValueError(
                "GMAIL_CREDENTIALS env var not set. "
                "Set it to a service account JSON string or file path."
            )

        # Accept a file path or a raw JSON string.
        if raw.strip().startswith("{"):
            info = json.loads(raw)
        else:
            with open(raw) as fh:
                info = json.load(fh)

        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
        ]
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        return creds.with_subject(subject)

    def _require_credentials(self, credentials: str | None = None) -> None:
        """Raise ValueError early if no credentials are available."""
        if not (credentials or os.environ.get("GMAIL_CREDENTIALS", "")):
            raise ValueError(
                "GMAIL_CREDENTIALS env var not set. "
                "Set it to a service account JSON string or file path."
            )

    def _service(self, subject: str, credentials: str | None = None) -> Any:
        """Build and return a Gmail API service object."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "google-api-python-client is required for GmailWorker. "
                "Install it with: pip install superpos-sdk[gmail]"
            ) from exc

        creds = self._creds(subject, credentials)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _subject(self, params: dict[str, Any]) -> str:
        subject = params.get("gmail_subject") or os.environ.get("GMAIL_SUBJECT", "")
        if not subject:
            raise ValueError(
                "Gmail subject (impersonated user) not found. "
                "Set GMAIL_SUBJECT env var or pass gmail_subject in params."
            )
        return subject

    def _build_mime(
        self,
        params: dict[str, Any],
        from_email: str,
    ) -> str:
        """Build a base64url-encoded RFC 2822 message."""
        html = bool(params.get("html", False))
        subtype = "html" if html else "plain"

        if params.get("cc") or params.get("bcc"):
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(params.get("body", ""), subtype))
        else:
            msg = MIMEText(params.get("body", ""), subtype)  # type: ignore[assignment]

        msg["To"] = params["to"]
        msg["From"] = params.get("from_email") or from_email
        msg["Subject"] = params.get("subject", "")
        if params.get("cc"):
            msg["Cc"] = params["cc"]
        if params.get("bcc"):
            msg["Bcc"] = params["bcc"]

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return raw

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def list_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        """List messages matching a Gmail query.

        Args:
            params: Optional ``query`` (Gmail search string), ``max_results``
                (default 10), ``gmail_subject`` (impersonated user).

        Returns:
            Dict with ``messages`` list and ``result_size_estimate``.
        """
        self._require_credentials(params.get("credentials"))
        subject = self._subject(params)
        svc = self._service(subject, params.get("credentials"))

        kwargs: dict[str, Any] = {
            "userId": "me",
            "maxResults": params.get("max_results", 10),
        }
        if params.get("query"):
            kwargs["q"] = params["query"]

        result = svc.users().messages().list(**kwargs).execute()  # type: ignore[attr-defined]
        return {
            "messages": result.get("messages", []),
            "result_size_estimate": result.get("resultSizeEstimate", 0),
            "next_page_token": result.get("nextPageToken"),
        }

    def get_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single message by ID.

        Args:
            params: Must include ``message_id``.  Optional: ``gmail_subject``
                (impersonated user), ``format`` (full/metadata/minimal,
                default full).

        Returns:
            Gmail message resource dict.
        """
        self._require_credentials(params.get("credentials"))
        subject = self._subject(params)
        svc = self._service(subject, params.get("credentials"))

        result = (
            svc.users()  # type: ignore[attr-defined]
            .messages()
            .get(
                userId="me",
                id=params["message_id"],
                format=params.get("format", "full"),
            )
            .execute()
        )
        return result

    def send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send an email.

        Args:
            params: Must include ``to`` and ``subject``.  Optional: ``body``,
                ``html`` (bool), ``cc``, ``bcc``, ``from_email``,
                ``gmail_subject`` (impersonated user).

        Returns:
            Sent message resource dict with ``id`` and ``threadId``.
        """
        self._require_credentials(params.get("credentials"))
        gmail_subject = self._subject(params)
        from_email = params.get("from_email") or gmail_subject
        svc = self._service(gmail_subject, params.get("credentials"))

        raw = self._build_mime(params, from_email)
        result = (
            svc.users()  # type: ignore[attr-defined]
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return result

    def create_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a draft email.

        Args:
            params: Must include ``to`` and ``subject``.  Optional: ``body``,
                ``html``, ``from_email``, ``gmail_subject``.

        Returns:
            Draft resource dict with ``id`` and ``message``.
        """
        self._require_credentials(params.get("credentials"))
        gmail_subject = self._subject(params)
        from_email = params.get("from_email") or gmail_subject
        svc = self._service(gmail_subject, params.get("credentials"))

        raw = self._build_mime(params, from_email)
        result = (
            svc.users()  # type: ignore[attr-defined]
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        return result
