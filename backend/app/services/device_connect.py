"""
Builds a ConnectionTarget (host/creds/transport/relay) for a DB row, so the
rest of the app never has to think about credential decryption or whether a
given CPE needs to be reached through its management router's SOCKS relay.
"""
from __future__ import annotations

from app.core.crypto import decrypt
from app.models.cpe import CPE, ConnectionMode
from app.models.management_router import ManagementRouter
from app.services.routeros_client import ConnectionTarget, SocksRelay


def target_for_management_router(router: ManagementRouter) -> ConnectionTarget:
    return ConnectionTarget(
        host=router.host,
        port=router.port,
        username=router.username,
        password=decrypt(router.password_encrypted),
        api_type=router.api_type.value if hasattr(router.api_type, "value") else router.api_type,
        verify_tls=router.verify_tls,
    )


def target_for_cpe(cpe: CPE, mgmt_router: ManagementRouter) -> ConnectionTarget:
    relay = None
    if cpe.connection_mode == ConnectionMode.socks_relay:
        if not mgmt_router.use_socks_relay:
            raise ValueError(
                f"CPE '{cpe.name}' is configured for SOCKS relay but its management "
                f"router '{mgmt_router.name}' does not have use_socks_relay enabled."
            )
        relay = SocksRelay(host=mgmt_router.host, port=mgmt_router.socks_port)
    elif cpe.connection_mode == ConnectionMode.vpn_tunnel:
        # No app-level relay object needed: once the PPTP/L2TP tunnel is up,
        # the OS routing table sends traffic for the remote LAN straight out
        # the tunnel interface, so this behaves exactly like "direct" at the
        # connection layer. See services/vpn_service.py.
        if mgmt_router.vpn_status.value != "connected":
            raise ValueError(
                f"CPE '{cpe.name}' is configured to reach its management router's LAN via VPN, "
                f"but the tunnel on '{mgmt_router.name}' is not connected (status: {mgmt_router.vpn_status.value})."
            )

    return ConnectionTarget(
        host=cpe.host,
        port=cpe.port,
        username=cpe.username or "",
        password=decrypt(cpe.password_encrypted) if cpe.password_encrypted else "",
        api_type=cpe.api_type.value if hasattr(cpe.api_type, "value") else cpe.api_type,
        verify_tls=False,
        relay=relay,
    )
