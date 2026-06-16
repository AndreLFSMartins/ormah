"""Tests for server lifecycle helpers: port-conflict detection and launchd plist."""

from __future__ import annotations

import socket
from unittest import mock

from ormah import server_manager


def test_is_port_in_use_true_when_socket_listening():
    """A bound, listening socket is reported as in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        host, port = srv.getsockname()
        assert server_manager.is_port_in_use(host, port) is True


def test_is_port_in_use_false_when_nothing_listening():
    """A port with no listener is reported as free."""
    # Grab an ephemeral port, then close it so nothing is listening.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        host, port = probe.getsockname()
    assert server_manager.is_port_in_use(host, port) is False


def test_plist_keepalive_only_on_unsuccessful_exit():
    """KeepAlive must not be unconditional: a clean exit (port already taken)
    must not trigger a launchd respawn storm."""
    plist = server_manager.PLIST_TEMPLATE.format(
        label="com.ormah.server",
        wrapper_path="/tmp/wrapper",
        bin_dir="/tmp/bin",
    )
    assert "<key>SuccessfulExit</key><false/>" in plist.replace(" ", "").replace("\n", "")
    # The old unconditional form must be gone.
    assert "<key>KeepAlive</key><true/>" not in plist.replace(" ", "").replace("\n", "")


def test_plist_has_throttle_interval():
    """A ThrottleInterval backstops genuine crash loops."""
    plist = server_manager.PLIST_TEMPLATE.format(
        label="com.ormah.server",
        wrapper_path="/tmp/wrapper",
        bin_dir="/tmp/bin",
    )
    compact = plist.replace(" ", "").replace("\n", "")
    assert "<key>ThrottleInterval</key>" in compact


def test_server_start_exits_clean_when_port_in_use():
    """`ormah server start` must NOT launch uvicorn when the port is already
    owned by another server — it returns cleanly so KeepAlive does not respawn."""
    from ormah import cli

    args = mock.Mock(daemon=False, reload=False)
    with mock.patch("ormah.server_manager.is_port_in_use", return_value=True), \
         mock.patch("uvicorn.run") as run:
        cli._cmd_server_start(args)
    run.assert_not_called()


def test_server_start_runs_uvicorn_when_port_free():
    """When the port is free, uvicorn is launched as normal."""
    from ormah import cli

    args = mock.Mock(daemon=False, reload=False)
    with mock.patch("ormah.server_manager.is_port_in_use", return_value=False), \
         mock.patch("uvicorn.run") as run:
        cli._cmd_server_start(args)
    run.assert_called_once()
