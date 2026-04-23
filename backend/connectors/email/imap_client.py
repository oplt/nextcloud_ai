from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import imaplib
import ssl

from backend.connectors.email.config import ImapConnectorConfig


@dataclass(slots=True)
class ImapMessagePayload:
    uid: str
    raw_message: bytes


class AsyncImapClient:
    def __init__(self, config: ImapConnectorConfig) -> None:
        self.config = config

    async def verify_credentials(self) -> None:
        await asyncio.to_thread(self._verify_credentials_sync)

    async def fetch_messages(self) -> list[ImapMessagePayload]:
        return await asyncio.to_thread(self._fetch_messages_sync)

    async def aclose(self) -> None:
        return None

    def _verify_credentials_sync(self) -> None:
        with self._session():
            return None

    def _fetch_messages_sync(self) -> list[ImapMessagePayload]:
        with self._session() as client:
            status, data = client.uid("search", None, self.config.search_criteria)
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            raw_uids = data[0].split() if data and data[0] else []
            if not raw_uids:
                return []

            messages: list[ImapMessagePayload] = []
            for raw_uid in raw_uids[-self.config.fetch_limit :]:
                uid = raw_uid.decode("utf-8", errors="ignore")
                fetch_status, parts = client.uid("fetch", raw_uid, "(RFC822)")
                if fetch_status != "OK":
                    continue
                payload = _extract_rfc822_payload(parts)
                if not payload:
                    continue
                messages.append(ImapMessagePayload(uid=uid, raw_message=payload))
            return messages

    @contextmanager
    def _session(self):
        client = self._connect()
        try:
            client.login(self.config.username, self.config.password)
            status, _ = client.select(self.config.mailbox)
            if status != "OK":
                raise RuntimeError(
                    f"IMAP mailbox '{self.config.mailbox}' could not be selected"
                )
            yield client
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

    def _connect(self):
        if self.config.use_ssl:
            ssl_context = ssl.create_default_context()
            if not self.config.verify_tls:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            return imaplib.IMAP4_SSL(
                self.config.host,
                self.config.port,
                ssl_context=ssl_context,
            )
        client = imaplib.IMAP4(self.config.host, self.config.port)
        if self.config.verify_tls:
            client.starttls(ssl_context=ssl.create_default_context())
        else:
            insecure_context = ssl._create_unverified_context()
            client.starttls(ssl_context=insecure_context)
        return client


def _extract_rfc822_payload(parts) -> bytes:
    for part in parts or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
            return part[1]
    return b""
