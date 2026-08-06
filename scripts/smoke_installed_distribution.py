#!/usr/bin/env python3
"""Install release artifacts in isolated environments and exercise public entry points."""

from __future__ import annotations

import argparse
import asyncio
import importlib.resources
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_PACKAGE_ASSETS = (
    "web/index.html",
    "web/app.js",
    "web/favicon.svg",
    "web/styles.css",
    "workflow/company-analytics.v1.json",
)


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


async def _handshake(command: Path, *, state_dir: Path, required_tool: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    environment = os.environ.copy()
    environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(state_dir)
    parameters = StdioServerParameters(
        command=str(command),
        args=[],
        env=environment,
        cwd=state_dir,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            if required_tool not in names:
                raise RuntimeError(f"{command.name} did not expose required tool {required_tool!r}")


async def _runtime_smoke(state_dir: Path, *, require_site_packages: bool) -> None:
    import stock_research_agents
    from stock_research_agents import discovery

    package_path = Path(stock_research_agents.__file__).resolve()
    if require_site_packages and "site-packages" not in package_path.parts:
        raise RuntimeError(f"smoke test imported a source checkout instead of an installed package: {package_path}")

    capability = discovery()
    if capability["active_profile"] != "company-analytics.v1":
        raise RuntimeError("installed package did not expose company-analytics.v1")

    package_root = importlib.resources.files("stock_research_agents")
    missing = [relative for relative in EXPECTED_PACKAGE_ASSETS if not package_root.joinpath(relative).is_file()]
    if missing:
        raise RuntimeError(f"installed package is missing assets: {missing}")

    # Keep the virtual-environment path. Resolving the interpreter symlink would
    # jump to the base Python installation, where console scripts do not exist.
    executable_dir = Path(sys.executable).parent
    environment = os.environ.copy()
    environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(state_dir)
    _run([str(executable_dir / "stock-research-agents"), "--help"], cwd=state_dir, env=environment)
    await _handshake(
        executable_dir / "stock-research-agents-mcp",
        state_dir=state_dir,
        required_tool="discover_capability",
    )
    await _handshake(
        executable_dir / "stock-research-data-mcp",
        state_dir=state_dir,
        required_tool="research_data_get_regulatory_filings",
    )
    print(f"installed distribution ok: {package_path}")


def _install_and_smoke(artifact: Path) -> None:
    with tempfile.TemporaryDirectory(prefix=f"stock-research-agents-{artifact.suffix.lstrip('.')}-") as temporary:
        root = Path(temporary)
        environment_dir = root / "venv"
        _run([sys.executable, "-m", "venv", str(environment_dir)], cwd=root)
        python = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run([str(python), "-m", "pip", "install", str(artifact.resolve())], cwd=root)
        _run(
            [str(python), str(Path(__file__).resolve()), "--runtime", "--state-dir", str(root / "state")],
            cwd=root,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path, help="wheel and sdist artifacts to install independently")
    parser.add_argument("--runtime", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--state-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--allow-editable", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.runtime:
        if args.state_dir is None:
            parser.error("--runtime requires --state-dir")
        args.state_dir.mkdir(parents=True, exist_ok=True)
        asyncio.run(_runtime_smoke(args.state_dir, require_site_packages=not args.allow_editable))
        return 0

    if not args.artifacts:
        parser.error("at least one wheel or sdist artifact is required")
    for artifact in args.artifacts:
        if not artifact.is_file():
            parser.error(f"artifact does not exist: {artifact}")
        _install_and_smoke(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
