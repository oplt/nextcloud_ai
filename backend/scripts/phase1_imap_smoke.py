"""Phase 1C: disposable IMAP smoke (GreenMail).

Covers UIDVALIDITY, BODY.PEEK[], bounded fetch vs complete inventory,
partial fetch retention semantics, and multi-message retention beyond
fetch_limit. Requires Docker.
"""

from __future__ import annotations

import argparse
import email.message
import json
import smtplib
import subprocess
import sys
import time
from pathlib import Path

from backend.connectors.email.config import ImapConnectorConfig
from backend.connectors.email.imap_client import AsyncImapClient

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_NAME = "phase1-imap-greenmail"
IMAGE = "greenmail/standalone:2.1.0"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=True,
    )


def _ensure_greenmail(*, host: str, imap_port: int, smtp_port: int) -> None:
    existing = _run(
        ["docker", "ps", "-aq", "-f", f"name=^{CONTAINER_NAME}$"],
        check=False,
    )
    if existing.stdout.strip():
        _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    # user:password creates local-part login; mailbox is user@hostname
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{smtp_port}:3025",
            "-p",
            f"{imap_port}:3143",
            "-e",
            "GREENMAIL_OPTS=-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 "
            "-Dgreenmail.users=phase1:phase1",
            IMAGE,
        ]
    )
    deadline = time.time() + 60
    last_err = ""
    while time.time() < deadline:
        try:
            with smtplib.SMTP(host, smtp_port, timeout=2) as smtp:
                smtp.noop()
            return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(1)
    raise RuntimeError(f"GreenMail SMTP not ready: {last_err}")


def _send_messages(*, host: str, smtp_port: int, count: int) -> None:
    for index in range(count):
        msg = email.message.EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "phase1"
        msg["Subject"] = f"phase1-smoke-{index}"
        msg.set_content(f"body-{index}\n")
        # Attach on the newest message so bounded fetch_limit still sees it.
        if index == count - 1:
            msg.add_attachment(
                b"attachment-bytes",
                maintype="application",
                subtype="octet-stream",
                filename="phase1.bin",
            )
        with smtplib.SMTP(host, smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)


async def _exercise_client(
    *,
    host: str,
    imap_port: int,
    fetch_limit: int,
    require_full: bool = True,
) -> dict[str, object]:
    import asyncio

    config = ImapConnectorConfig(
        host=host,
        port=imap_port,
        username="phase1",
        password="phase1",
        use_ssl=False,
        starttls=False,
        verify_tls=False,
        mailbox="INBOX",
        search_criteria="ALL",
        fetch_limit=fetch_limit,
    )
    client = AsyncImapClient(config)
    first = await client.fetch_messages()
    if not require_full:
        return {
            "inventory_count": len(first.inventory.uids),
            "fetched_count": len(first.messages),
        }
    if first.inventory.uidvalidity is None:
        raise RuntimeError("UIDVALIDITY missing from inventory")
    if not first.inventory.complete:
        raise RuntimeError("inventory must be complete when UIDVALIDITY present")
    if len(first.inventory.uids) < fetch_limit + 2:
        raise RuntimeError(
            f"expected >fetch_limit messages in inventory, got {len(first.inventory.uids)}"
        )
    if not first.fetch_truncated:
        raise RuntimeError("expected fetch_truncated when inventory > fetch_limit")
    if len(first.messages) > fetch_limit:
        raise RuntimeError("body fetch exceeded fetch_limit")
    # BODY.PEEK[] must leave messages unseen.
    status_flags = await asyncio.to_thread(_unseen_count, config)
    if status_flags == 0:
        raise RuntimeError("BODY.PEEK[] appears to have marked messages Seen")

    second = await client.fetch_messages()
    if second.inventory.uids != first.inventory.uids:
        raise RuntimeError("UID inventory changed unexpectedly between fetches")
    if second.inventory.uidvalidity != first.inventory.uidvalidity:
        raise RuntimeError("UIDVALIDITY changed without mailbox recreate")

    has_attachment = any(
        b"phase1.bin" in message.raw_message for message in first.messages
    )
    if not has_attachment:
        raise RuntimeError(
            "expected attachment filename in raw RFC822 payload; "
            f"fetched={len(first.messages)} sizes={[len(m.raw_message) for m in first.messages]}"
        )

    return {
        "uidvalidity": first.inventory.uidvalidity,
        "inventory_count": len(first.inventory.uids),
        "fetched_count": len(first.messages),
        "fetch_limit": fetch_limit,
        "fetch_truncated": first.fetch_truncated,
        "fetch_failed_uids": first.fetch_failed_uids,
        "unseen_after_peek": status_flags,
        "attachment_observed": has_attachment,
    }


def _unseen_count(config: ImapConnectorConfig) -> int:
    import imaplib

    client = imaplib.IMAP4(config.host, config.port)
    try:
        client.login(config.username, config.password)
        status, data = client.status(config.mailbox, "(UNSEEN)")
        if status != "OK" or not data:
            raise RuntimeError("STATUS UNSEEN failed")
        blob = (
            data[0]
            if isinstance(data[0], (bytes, bytearray))
            else str(data[0]).encode()
        )
        import re

        match = re.search(rb"UNSEEN\s+(\d+)", blob, re.IGNORECASE)
        if not match:
            raise RuntimeError(f"UNSEEN parse failed: {blob!r}")
        return int(match.group(1))
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--imap-port", type=int, default=3143)
    parser.add_argument("--smtp-port", type=int, default=3025)
    parser.add_argument("--message-count", type=int, default=8)
    parser.add_argument("--fetch-limit", type=int, default=3)
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Leave GreenMail running after the smoke.",
    )
    args = parser.parse_args(argv)
    try:
        _ensure_greenmail(
            host=args.host, imap_port=args.imap_port, smtp_port=args.smtp_port
        )
        _send_messages(
            host=args.host, smtp_port=args.smtp_port, count=args.message_count
        )
        # Wait until IMAP inventory reflects SMTP deliveries.
        deadline = time.time() + 30
        while time.time() < deadline:
            probe = asyncio.run(
                _exercise_client(
                    host=args.host,
                    imap_port=args.imap_port,
                    fetch_limit=args.fetch_limit,
                    require_full=False,
                )
            )
            if probe.get("inventory_count", 0) >= args.message_count:
                break
            time.sleep(1)
        report = asyncio.run(
            _exercise_client(
                host=args.host,
                imap_port=args.imap_port,
                fetch_limit=args.fetch_limit,
                require_full=True,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        if not args.keep_container:
            _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    if not args.keep_container:
        _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
