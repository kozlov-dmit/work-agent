"""Self-provisioning: let the agent install tools into its container and have
those installs persist across container restarts.

Installs are recorded in a manifest under the (volume-mounted) state directory.
On container start, ``work-agent bootstrap`` replays the manifest so the same
packages are present again even though the container filesystem is ephemeral.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

MANIFEST_NAME = "provisioning.json"
SUPPORTED = ("apt", "pip", "npm")
_TIMEOUT = 600


def _install_command(manager: str, packages: list[str]) -> str:
    pkgs = " ".join(shlex.quote(p) for p in packages)
    if manager == "apt":
        return f"sudo apt-get update && sudo apt-get install -y {pkgs}"
    if manager == "pip":
        return f"pip install --user {pkgs}"
    if manager == "npm":
        return f"npm install -g {pkgs}"
    raise ValueError(f"Unsupported package manager: {manager}")


class Provisioning:
    """Reads/writes the provisioning manifest and runs installs."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / MANIFEST_NAME

    def load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {m: [] for m in SUPPORTED}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {m: [] for m in SUPPORTED}
        return {m: list(data.get(m, [])) for m in SUPPORTED}

    def record(self, manager: str, packages: list[str]) -> None:
        """Add packages to the manifest (deduplicated), without installing."""
        if manager not in SUPPORTED:
            raise ValueError(f"Unsupported package manager: {manager}")
        manifest = self.load()
        existing = manifest[manager]
        for pkg in packages:
            if pkg not in existing:
                existing.append(pkg)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(manifest, indent=2))

    def install(
        self, manager: str, packages: list[str], record: bool = True
    ) -> tuple[int, str]:
        """Install packages now; optionally record them for replay on restart."""
        command = _install_command(manager, packages)
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return 124, f"Install timed out after {_TIMEOUT}s"
        if record and proc.returncode == 0:
            self.record(manager, packages)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out

    def apply_all(self) -> str:
        """Reinstall everything in the manifest. Used at container startup."""
        manifest = self.load()
        lines: list[str] = []
        for manager in SUPPORTED:
            packages = manifest.get(manager) or []
            if not packages:
                continue
            code, _out = self.install(manager, packages, record=False)
            status = "ok" if code == 0 else f"FAILED (exit {code})"
            lines.append(f"{manager}: {', '.join(packages)} — {status}")
        return "\n".join(lines)
