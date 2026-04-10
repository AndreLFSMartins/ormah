"""Unified CLI entry point for ormah.

Usage:
    ormah server start      Start server (foreground)
    ormah server start -d   Start server (daemon via launchd)
    ormah server stop       Stop daemon
    ormah server status     Check if running
    ormah setup             One-shot setup (hooks, MCP, server)
    ormah uninstall         Remove all ormah integrations and data
    ormah mcp               Run MCP stdio server
    ormah recall <query>    Search memories
    ormah remember <text>   Store a memory
    ormah ingest <file>     Ingest a conversation log
    ormah ingest-session <path>  Ingest a Claude Code session
    ormah node <id>         Get a specific memory
    ormah whisper inject    Hook handler: inject context
    ormah whisper store     Hook handler: store memories
"""

from __future__ import annotations

import argparse
import sys


def _cmd_server_start(args):
    if args.daemon:
        from ormah.console import info, warn
        from ormah.server_manager import get_ormah_bin_path, install_autostart, wait_for_server
        from ormah.setup import WRAPPER_PATH, generate_server_wrapper

        ormah_bin = get_ormah_bin_path()
        if not WRAPPER_PATH.exists():
            generate_server_wrapper(ormah_bin)
        install_autostart(ormah_bin, wrapper_path=str(WRAPPER_PATH))
        if not wait_for_server(show_progress=True):
            warn("Server did not start in time")
            info("Check ~/.local/share/ormah/logs/ormah.log")
    else:
        import uvicorn
        from ormah.config import settings

        uvicorn.run(
            "ormah.main:app",
            host=settings.host,
            port=settings.port,
            reload=args.reload,
        )


def _cmd_server_stop(args):
    from ormah.server_manager import uninstall_autostart

    uninstall_autostart()


def _cmd_server_status(args):
    from ormah.server_manager import is_server_running
    from ormah.config import settings

    if is_server_running():
        print(f"Server is running on port {settings.port}.")
    else:
        print("Server is not running.")
        sys.exit(1)


def _cmd_setup(args):
    from ormah.setup import run_setup

    run_setup(
        ci=args.ci,
        update=args.update,
        skip_client_setup=args.skip_client_setup,
    )


def _cmd_uninstall(args):
    from ormah.setup import run_uninstall

    run_uninstall(yes=args.yes)


def _cmd_mcp(args):
    from ormah.adapters.mcp_adapter import main as mcp_main

    mcp_main()


def main():
    from importlib.metadata import version as pkg_version

    p = argparse.ArgumentParser(
        prog="ormah",
        description="Local-first memory system for AI agents.",
    )
    p.add_argument(
        "--version", action="version",
        version=f"ormah {pkg_version('ormah')}",
    )
    sub = p.add_subparsers(dest="cmd")

    # --- server ---
    server_p = sub.add_parser("server", help="Manage the ormah server")
    server_sub = server_p.add_subparsers(dest="server_cmd", required=True)

    start_p = server_sub.add_parser("start", help="Start the server")
    start_p.add_argument(
        "-d", "--daemon", action="store_true",
        help="Run as daemon (launchd on macOS)",
    )
    start_p.add_argument(
        "--reload", action="store_true",
        help="Enable auto-reload on file changes (dev mode)",
    )
    start_p.set_defaults(func=_cmd_server_start)

    stop_p = server_sub.add_parser("stop", help="Stop the daemon")
    stop_p.set_defaults(func=_cmd_server_stop)

    status_p = server_sub.add_parser("status", help="Check server status")
    status_p.set_defaults(func=_cmd_server_status)

    # --- setup ---
    setup_p = sub.add_parser("setup", help="One-shot setup (hooks, MCP, server)")
    setup_p.add_argument("--ci", action="store_true", help="Non-interactive mode for CI/testing")
    setup_p.add_argument("--update", action="store_true", help="Skip interactive questions, just reapply hooks and MCP config")
    setup_p.add_argument(
        "--skip-client-setup",
        action="store_true",
        help="Skip Claude/Codex/Desktop integration wiring; useful when a plugin manages the client side",
    )
    setup_p.set_defaults(func=_cmd_setup)

    # --- uninstall ---
    uninstall_p = sub.add_parser("uninstall", help="Remove all ormah integrations and data")
    uninstall_p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    uninstall_p.set_defaults(func=_cmd_uninstall)

    # --- mcp ---
    mcp_p = sub.add_parser("mcp", help="Run MCP stdio server")
    mcp_p.set_defaults(func=_cmd_mcp)

    # --- CLI commands (delegated to cli_adapter) ---
    from ormah.adapters.cli_adapter import (
        cmd_ingest,
        cmd_ingest_session,
        cmd_node,
        cmd_outdated,
        cmd_recall,
        cmd_remember,
        cmd_stats,
        cmd_whisper_inject,
        cmd_whisper_store,
        cmd_whisper_setup,
    )

    # recall
    rec = sub.add_parser("recall", help="Search memories")
    rec.add_argument("query", help="Search query")
    rec.add_argument("--limit", type=int, help="Max results")
    rec.add_argument("--types", help="Comma-separated memory types to filter")
    rec.add_argument("--json", action="store_true", help="Output raw JSON")
    rec.add_argument("--space", help="Override space detection")
    rec.set_defaults(func=cmd_recall)

    # remember
    rem = sub.add_parser("remember", help="Store a memory")
    rem.add_argument("content", help="Memory content (use - for stdin)")
    rem.add_argument("--title", help="Short title")
    rem.add_argument("--type", default="fact", help="Memory type (default: fact)")
    rem.add_argument(
        "--tier", default="working",
        help="Tier: core/working/archival (default: working)",
    )
    rem.add_argument("--tags", help="Comma-separated tags")
    rem.add_argument("--about-self", action="store_true", help="Link to user identity")
    rem.add_argument("--space", help="Override space detection")
    rem.set_defaults(func=cmd_remember)

    # ingest
    ing = sub.add_parser("ingest", help="Ingest a conversation log")
    ing.add_argument("source", help="File path or - for stdin")
    ing.add_argument("--space", help="Override space detection")
    ing.set_defaults(func=cmd_ingest)

    # ingest-session
    ings = sub.add_parser(
        "ingest-session", help="Ingest a Claude Code JSONL session transcript",
    )
    ings.add_argument("path", help="Path to Claude Code JSONL transcript")
    ings.add_argument(
        "--dry-run", action="store_true",
        help="Extract but don't store",
    )
    ings.add_argument("--space", help="Override project space")
    ings.add_argument(
        "--min-turns", type=int, default=5,
        help="Minimum user turns (default: 5)",
    )
    ings.set_defaults(func=cmd_ingest_session)

    # node
    nd = sub.add_parser("node", help="Get a specific memory by ID")
    nd.add_argument("id", help="Memory UUID")
    nd.add_argument("--json", action="store_true", help="Output raw JSON")
    nd.set_defaults(func=cmd_node)

    # outdated
    out = sub.add_parser("outdated", help="Mark a memory as outdated")
    out.add_argument("id", help="Memory UUID")
    out.add_argument("--reason", help="Reason for marking outdated")
    out.set_defaults(func=cmd_outdated)

    # stats
    sts = sub.add_parser("stats", help="Show memory store statistics")
    sts.add_argument("--json", action="store_true", help="Output raw JSON")
    sts.set_defaults(func=cmd_stats)

    # whisper
    wh = sub.add_parser("whisper", help="Claude Code hook integration")
    wh_sub = wh.add_subparsers(dest="whisper_cmd", required=True)

    wh_inject = wh_sub.add_parser("inject", help="(internal) UserPromptSubmit hook — called automatically by Claude Code")
    wh_inject.set_defaults(func=cmd_whisper_inject)

    wh_store = wh_sub.add_parser("store", help="(internal) PreCompact/SessionEnd hook — called automatically by Claude Code")
    wh_store.set_defaults(func=cmd_whisper_store)

    wh_setup = wh_sub.add_parser("setup", help="Write Claude Code hook config to settings.json")
    wh_setup.add_argument(
        "--global", dest="glob", action="store_true",
        help="Write to global ~/.claude/settings.json",
    )
    wh_setup.set_defaults(func=cmd_whisper_setup)

    # eval
    from eval.whisper.cli import cmd_eval_whisper_run
    ev = sub.add_parser("eval", help="Run evaluation harnesses")
    ev_sub = ev.add_subparsers(dest="eval_cmd", required=True)

    ev_wh = ev_sub.add_parser("whisper", help="Evaluate whisper pipeline quality")
    ev_wh_sub = ev_wh.add_subparsers(dest="eval_whisper_cmd", required=True)

    ev_wh_run = ev_wh_sub.add_parser("run", help="Run whisper eval against golden corpus")
    ev_wh_run.add_argument("--category", help="Filter by category (e.g. preference, factual)")
    ev_wh_run.add_argument("--show-failures", action="store_true", dest="show_failures",
                           help="Print failure details")
    ev_wh_run.add_argument(
        "--simulate-session",
        action="store_true",
        help="Force session simulation for all prompts in the corpus",
    )
    ev_wh_run.add_argument(
        "--preserve-self",
        action="store_true",
        help="Preserve the self node when reseeding eval cases",
    )
    ev_wh_run.add_argument("--json", action="store_true", help="Output as JSON")
    ev_wh_run.set_defaults(func=cmd_eval_whisper_run)

    args = p.parse_args()

    if not args.cmd:
        p.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
