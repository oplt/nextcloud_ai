from __future__ import annotations

import base64
import posixpath
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx

from backend.connectors.nextcloud.config import NextcloudConnectorConfig
from backend.connectors.nextcloud.exceptions import (
    NextcloudAPIError,
    NextcloudAuthenticationError,
)
from backend.connectors.nextcloud.schemas import DavNode, ShareGrant

DAV_NS = "DAV:"
OC_NS = "http://owncloud.org/ns"
NS = {"d": DAV_NS, "oc": OC_NS}


class AsyncNextcloudClient:
    def __init__(self, config: NextcloudConnectorConfig) -> None:
        self.config = config
        creds = f"{config.username}:{config.app_password.get_secret_value()}"
        auth_header = base64.b64encode(creds.encode("utf-8")).decode("ascii")
        self._client = httpx.AsyncClient(
            base_url=str(config.base_url).rstrip("/") + "/",
            headers={
                "Authorization": f"Basic {auth_header}",
                "OCS-APIRequest": "true",
                "Accept": "application/json",
            },
            verify=config.verify_tls,
            timeout=config.request_timeout_seconds,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def verify_credentials(self) -> None:
        response = await self._request("GET", "ocs/v2.php/cloud/user?format=json")
        if response.status_code in {401, 403}:
            raise NextcloudAuthenticationError(
                "Nextcloud connector authentication failed"
            )
        self._raise_for_status(
            response, "Could not verify Nextcloud connector credentials"
        )

    async def list_directory(self, remote_path: str, depth: int = 1) -> list[DavNode]:
        dav_path = self._dav_path(remote_path)
        body = """<?xml version=\"1.0\"?>
<d:propfind xmlns:d=\"DAV:\" xmlns:oc=\"http://owncloud.org/ns\">
  <d:prop>
    <d:getcontentlength />
    <d:getcontenttype />
    <d:getetag />
    <d:getlastmodified />
    <d:resourcetype />
    <oc:fileid />
  </d:prop>
</d:propfind>
"""
        response = await self._request(
            "PROPFIND",
            dav_path,
            headers={"Depth": str(depth), "Content-Type": "application/xml"},
            content=body,
        )
        self._raise_for_status(response, f"Could not list directory {remote_path}")
        return self._parse_multistatus(response.text)

    async def download_file(self, remote_path: str) -> bytes:
        response = await self._request("GET", self._dav_path(remote_path))
        self._raise_for_status(response, f"Could not download file {remote_path}")
        return response.content

    async def get_shares(self, remote_path: str) -> list[ShareGrant]:
        response = await self._request(
            "GET",
            "ocs/v2.php/apps/files_sharing/api/v1/shares",
            params={
                "format": "json",
                "path": self._normalize_path(remote_path),
                "reshares": "true",
            },
        )
        self._raise_for_status(response, f"Could not fetch shares for {remote_path}")
        payload = response.json()
        items = payload.get("ocs", {}).get("data", []) or []
        return [ShareGrant.model_validate(item) for item in items]

    def _dav_path(self, remote_path: str) -> str:
        normalized = self._normalize_path(remote_path)
        joined = posixpath.join(
            "remote.php/dav/files", self.config.username, normalized.lstrip("/")
        )
        return quote(joined)

    @staticmethod
    def _normalize_path(remote_path: str) -> str:
        remote_path = remote_path.strip()
        if not remote_path:
            return "/"
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path
        return posixpath.normpath(remote_path)

    def _parse_multistatus(self, xml_text: str) -> list[DavNode]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise NextcloudAPIError("Nextcloud returned invalid WebDAV XML") from exc

        results: list[DavNode] = []
        for response_el in root.findall("d:response", NS):
            href = response_el.findtext("d:href", default="", namespaces=NS)
            propstat = response_el.find("d:propstat", NS)
            if propstat is None:
                continue
            prop = propstat.find("d:prop", NS)
            if prop is None:
                continue

            resourcetype = prop.find("d:resourcetype", NS)
            is_directory = (
                resourcetype is not None
                and resourcetype.find("d:collection", NS) is not None
            )
            file_id = prop.findtext("oc:fileid", default=None, namespaces=NS)
            etag = prop.findtext("d:getetag", default=None, namespaces=NS)
            content_type = prop.findtext(
                "d:getcontenttype", default=None, namespaces=NS
            )
            size_text = prop.findtext("d:getcontentlength", default=None, namespaces=NS)
            last_modified_text = prop.findtext(
                "d:getlastmodified", default=None, namespaces=NS
            )
            path = self._href_to_path(href)
            size_bytes = int(size_text) if size_text and size_text.isdigit() else None
            last_modified = self._parse_http_datetime(last_modified_text)
            results.append(
                DavNode(
                    path=path,
                    href=href,
                    file_id=file_id,
                    etag=etag.strip('"') if etag else None,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    last_modified=last_modified,
                    is_directory=is_directory,
                )
            )
        return results

    def _href_to_path(self, href: str) -> str:
        parsed = urlparse(href)
        path = unquote(parsed.path)
        instance_path = unquote(urlparse(str(self.config.base_url)).path).rstrip("/")
        if instance_path and path.startswith(instance_path):
            path = path[len(instance_path) :]
        prefix = f"/remote.php/dav/files/{self.config.username}"
        if path.startswith(prefix):
            path = path[len(prefix) :]
        return path or "/"

    @staticmethod
    def _parse_http_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            return None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            base_url = str(self.config.base_url).rstrip("/")
            raise NextcloudAPIError(
                f"Could not reach Nextcloud at {base_url}. "
                "Check the connector base URL and that the server is reachable from the backend."
            ) from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response, message: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            details: Any
            try:
                details = response.json()
            except ValueError:
                details = response.text[:500]
            raise NextcloudAPIError(
                f"{message}. status={response.status_code} details={details}"
            ) from exc
