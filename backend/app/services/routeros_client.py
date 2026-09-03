"""
Unified async client for talking to MikroTik RouterOS devices, whether they
are the top-level "management router" the app authenticates against directly,
or a CPE sitting behind it.

Two transports are supported:
  - REST  (RouterOS 7+, recommended): plain HTTPS JSON API on /rest/*.
  - API / API-SSL (binary, works on RouterOS 6 and 7): used as a fallback for
    older CPEs that were never upgraded - very common for outdoor antennas
    that are "if it ain't broke, don't touch it" gear.

Both transports can additionally be tunnelled through a SOCKS5 proxy running
on a *management router*. That's how we reach CPEs that have no route back
to the app at all - e.g. a bridge-mode antenna with only a management IP
that's only reachable from inside that router's own LAN. Turning on
`IP > SOCKS` on the management router (one checkbox) makes every device on
its network reachable this way, without opening anything to the internet.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from httpx_socks import AsyncProxyTransport
from librouteros import AsyncApi, AsyncApiProtocol, AsyncSocketTransport
from librouteros.exceptions import ConnectionClosed, FatalError, LibRouterosError, MultiTrapError, TrapError
from librouteros.login import async_plain
from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy as SocksProxy

logger = logging.getLogger(__name__)


class RouterOSError(Exception):
    """Any failure talking to a RouterOS device: network, auth, or command error."""


@dataclass
class SocksRelay:
    host: str
    port: int
    username: str | None = None
    password: str | None = None


@dataclass
class ConnectionTarget:
    host: str
    port: int
    username: str
    password: str
    api_type: str = "rest"          # "rest" | "api" | "api-ssl"
    verify_tls: bool = False
    timeout: float = 12.0
    relay: SocksRelay | None = None  # set to route through a management router's SOCKS proxy


class _RestClient:
    def __init__(self, target: ConnectionTarget):
        self.target = target
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "_RestClient":
        scheme = "https"
        base_url = f"{scheme}://{self.target.host}:{self.target.port}/rest/"
        transport = None
        if self.target.relay:
            proxy_url = self._proxy_url()
            # `verify` must be passed to the transport itself, not just the
            # AsyncClient - when a custom transport is set, httpx no longer
            # derives the TLS context from AsyncClient(verify=...) for it.
            transport = AsyncProxyTransport.from_url(proxy_url, verify=self.target.verify_tls)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=(self.target.username, self.target.password),
            verify=self.target.verify_tls,
            timeout=self.target.timeout,
            transport=transport,
        )
        return self

    def _proxy_url(self) -> str:
        r = self.target.relay
        auth = f"{r.username}:{r.password}@" if r.username else ""
        return f"socks5://{auth}{r.host}:{r.port}"

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def _raise_for_status(self, resp: httpx.Response):
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RouterOSError(f"REST {resp.request.method} {resp.request.url} -> {resp.status_code}: {detail}")

    async def get(self, path: str) -> Any:
        try:
            resp = await self._client.get(path)
        except httpx.HTTPError as e:
            raise RouterOSError(f"connection error calling {path}: {e}") from e
        await self._raise_for_status(resp)
        return resp.json()

    async def post(self, path: str, json: dict | None = None) -> Any:
        try:
            resp = await self._client.post(path, json=json or {})
        except httpx.HTTPError as e:
            raise RouterOSError(f"connection error calling {path}: {e}") from e
        await self._raise_for_status(resp)
        if resp.content:
            return resp.json()
        return None

    async def put(self, path: str, json: dict) -> Any:
        try:
            resp = await self._client.put(path, json=json)
        except httpx.HTTPError as e:
            raise RouterOSError(f"connection error calling {path}: {e}") from e
        await self._raise_for_status(resp)
        return resp.json() if resp.content else None

    async def patch(self, path: str, json: dict) -> Any:
        resp = await self._client.patch(path, json=json)
        await self._raise_for_status(resp)
        return resp.json() if resp.content else None

    async def delete(self, path: str) -> None:
        resp = await self._client.delete(path)
        await self._raise_for_status(resp)


class _BinaryApiClient:
    """Wraps librouteros' native asyncio API, optionally over a SOCKS relay."""

    def __init__(self, target: ConnectionTarget):
        self.target = target
        self._api: AsyncApi | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> "_BinaryApiClient":
        ssl_ctx = None
        if self.target.api_type == "api-ssl":
            ssl_ctx = ssl.create_default_context()
            if not self.target.verify_tls:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            if self.target.relay:
                reader, writer = await self._open_via_relay(ssl_ctx)
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host=self.target.host, port=self.target.port, ssl=ssl_ctx),
                    timeout=self.target.timeout,
                )
        except (OSError, asyncio.TimeoutError) as e:
            raise RouterOSError(f"connection to {self.target.host}:{self.target.port} failed: {e}") from e

        self._writer = writer
        transport = AsyncSocketTransport(reader=reader, writer=writer)
        protocol = AsyncApiProtocol(transport=transport, encoding="ASCII", timeout=self.target.timeout)
        self._api = AsyncApi(protocol=protocol)
        try:
            await async_plain(self._api, self.target.username, self.target.password)
        except (TrapError, MultiTrapError) as e:
            raise RouterOSError(f"authentication failed: {e}") from e
        except (ConnectionClosed, FatalError, OSError, asyncio.TimeoutError) as e:
            raise RouterOSError(f"connection failed: {e}") from e
        return self

    async def _open_via_relay(self, ssl_ctx: ssl.SSLContext | None):
        r = self.target.relay
        proxy = SocksProxy.create(
            proxy_type=ProxyType.SOCKS5,
            host=r.host,
            port=r.port,
            username=r.username,
            password=r.password,
        )
        sock = await proxy.connect(dest_host=self.target.host, dest_port=self.target.port, timeout=self.target.timeout)
        sock.setblocking(False)
        if ssl_ctx:
            reader, writer = await asyncio.open_connection(sock=sock, ssl=ssl_ctx, server_hostname=self.target.host)
        else:
            reader, writer = await asyncio.open_connection(sock=sock)
        return reader, writer

    async def __aexit__(self, *exc):
        if self._api:
            try:
                await self._api.close()
            except Exception:
                pass

    async def call(self, cmd: str, **params: Any) -> list[dict]:
        try:
            return [row async for row in self._api(cmd, **params)]
        except (TrapError, MultiTrapError) as e:
            raise RouterOSError(f"{cmd} failed: {e}") from e
        except (ConnectionClosed, FatalError, LibRouterosError) as e:
            raise RouterOSError(f"{cmd} connection error: {e}") from e


def _rest_path_for(path: str) -> str:
    return path.strip("/")


def _api_cmd_for(path: str, action: str) -> str:
    return "/" + "/".join([*path.strip("/").split("/"), action])


class RouterOSClient:
    """
    High-level, transport-agnostic facade used by the rest of the app.
    Usage:
        async with RouterOSClient(target) as ros:
            resources = await ros.list("interface")
            info = await ros.get_single("system/resource")
            await ros.run_action("system", "reboot")
    """

    def __init__(self, target: ConnectionTarget):
        self.target = target
        self._impl: _RestClient | _BinaryApiClient | None = None

    async def __aenter__(self) -> "RouterOSClient":
        if self.target.api_type == "rest":
            self._impl = await _RestClient(self.target).__aenter__()
        else:
            self._impl = await _BinaryApiClient(self.target).__aenter__()
        return self

    async def __aexit__(self, *exc):
        if self._impl:
            await self._impl.__aexit__(*exc)

    async def list(self, path: str) -> list[dict]:
        """Equivalent of `/<path>/print` - returns a list of rows."""
        if isinstance(self._impl, _RestClient):
            data = await self._impl.get(_rest_path_for(path))
            return data if isinstance(data, list) else [data]
        cmd = "/" + "/".join([*path.strip("/").split("/"), "print"])
        return await self._impl.call(cmd)

    async def get_single(self, path: str) -> dict:
        """For singleton resources like system/resource, system/identity."""
        rows = await self.list(path)
        if isinstance(rows, list):
            return rows[0] if rows else {}
        return rows

    async def create(self, path: str, **params: Any) -> dict:
        """
        Adds a new item to a list resource, e.g.
        create("system/script", name="my-script", source=":log info \"hi\"").
        Returns the created row (including its .id). RouterOS REST uses PUT
        for this (POST is reserved for item-specific actions like "run") -
        the binary API equivalent is `/<path>/add`.
        """
        if isinstance(self._impl, _RestClient):
            result = await self._impl.put(_rest_path_for(path), json=params)
            return result or {}
        cmd = _api_cmd_for(path, "add")
        rows = await self._impl.call(cmd, **params)
        return rows[0] if rows else {}

    async def run_action(self, path: str, action: str, **params: Any) -> Any:
        """
        Equivalent of `/<path>/<action> param=value ...`, e.g.
        run_action("system", "reboot") or
        run_action("system/script", "run", **{".id": "*1"}).
        """
        if isinstance(self._impl, _RestClient):
            return await self._impl.post(f"{_rest_path_for(path)}/{action}", json=params or None)
        cmd = _api_cmd_for(path, action)
        return await self._impl.call(cmd, **params)

    async def update(self, path: str, item_id: str, **params: Any) -> Any:
        """Equivalent of `/<path>/set .id=<item_id> param=value ...`."""
        if isinstance(self._impl, _RestClient):
            return await self._impl.patch(f"{_rest_path_for(path)}/{item_id}", json=params)
        cmd = _api_cmd_for(path, "set")
        return await self._impl.call(cmd, **{".id": item_id, **params})

    async def remove(self, path: str, item_id: str) -> None:
        if isinstance(self._impl, _RestClient):
            await self._impl.delete(f"{_rest_path_for(path)}/{item_id}")
            return
        cmd = _api_cmd_for(path, "remove")
        await self._impl.call(cmd, **{".id": item_id})


@asynccontextmanager
async def connect(target: ConnectionTarget) -> AsyncIterator[RouterOSClient]:
    client = RouterOSClient(target)
    await client.__aenter__()
    try:
        yield client
    finally:
        await client.__aexit__(None, None, None)
