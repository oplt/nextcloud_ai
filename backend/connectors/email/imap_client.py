from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import imaplib
import re
import ssl

from .config import ImapConnectorConfig

_UIDVALIDITY_RE = re.compile(rb"UIDVALIDITY\s+(\d+)", re.IGNORECASE)


@dataclass(slots=True)
class ImapMessagePayload:
    uid: str
    raw_message: bytes


@dataclass(slots=True)
class MailboxInventory:
    """Authoritative mailbox UID set (independent of body fetch window)."""

    mailbox: str
    uidvalidity: int | None
    uids: list[str]
    complete: bool
    search_criteria: str


@dataclass(slots=True)
class ImapFetchResult:
    inventory: MailboxInventory
    messages: list[ImapMessagePayload] = field(default_factory=list)
    fetch_failed_uids: list[str] = field(default_factory=list)
    fetch_truncated: bool = False


class AsyncImapClient:
    def __init__(self, config: ImapConnectorConfig) -> None:
        self.config = config

    async def verify_credentials(self) -> None:
        await asyncio.to_thread(self._verify_credentials_sync)

    async def fetch_messages(self) -> ImapFetchResult:
        return await asyncio.to_thread(self._fetch_messages_sync)

    async def aclose(self) -> None:
        return None

    def _verify_credentials_sync(self) -> None:
        with self._session(readonly=True):
            return None

    def _fetch_messages_sync(self) -> ImapFetchResult:
        with self._session(readonly=True) as client:
            uidvalidity = self._read_uidvalidity(client)
            status, data = client.uid("search", None, self.config.search_criteria)
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            raw_uids = data[0].split() if data and data[0] else []
            all_uids = [
                raw_uid.decode("utf-8", errors="ignore") for raw_uid in raw_uids
            ]
            inventory = MailboxInventory(
                mailbox=self.config.mailbox,
                uidvalidity=uidvalidity,
                uids=all_uids,
                # UID values are only authoritative within a UIDVALIDITY epoch.
                # Continue bounded ingestion when the server omits it, but never
                # reconcile deletions against an unknown epoch.
                complete=uidvalidity is not None,
                search_criteria=self.config.search_criteria,
            )
            if not raw_uids:
                return ImapFetchResult(inventory=inventory)

            # Bounded body window — never treat this subset as the full mailbox.
            window = raw_uids[-self.config.fetch_limit :]
            messages: list[ImapMessagePayload] = []
            failed: list[str] = []
            for raw_uid in window:
                uid = raw_uid.decode("utf-8", errors="ignore")
                # BODY.PEEK[] avoids setting \Seen (unlike RFC822).
                fetch_status, parts = client.uid("fetch", raw_uid, "(BODY.PEEK[])")
                if fetch_status != "OK":
                    failed.append(uid)
                    continue
                payload = _extract_rfc822_payload(parts)
                if not payload:
                    failed.append(uid)
                    continue
                messages.append(ImapMessagePayload(uid=uid, raw_message=payload))

            return ImapFetchResult(
                inventory=inventory,
                messages=messages,
                fetch_failed_uids=failed,
                fetch_truncated=len(all_uids) > len(window),
            )

    def _read_uidvalidity(self, client: imaplib.IMAP4) -> int | None:
        try:
            status, data = client.status(self.config.mailbox, "(UIDVALIDITY)")
        except Exception:
            return None
        if status != "OK" or not data:
            return None
        blob = (
            data[0]
            if isinstance(data[0], (bytes, bytearray))
            else str(data[0]).encode()
        )
        match = _UIDVALIDITY_RE.search(blob)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @contextmanager
    def _session(self, *, readonly: bool = True):
        client = self._connect()
        try:
            client.login(self.config.username, self.config.password)
            status, _ = client.select(self.config.mailbox, readonly=readonly)
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
        if self.config.starttls:
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
