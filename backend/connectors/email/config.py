from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ImapConnectorConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str = "INBOX"
    use_ssl: bool = True
    verify_tls: bool = True
    # When use_ssl is False, optionally upgrade with STARTTLS. Disposable
    # plaintext test servers (GreenMail) set this False.
    starttls: bool = True
    search_criteria: str = "ALL"
    fetch_limit: int = 100
