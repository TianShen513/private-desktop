# private-desktop

A local privacy gateway for [agent-desktop](https://github.com/vercel-labs/agent-desktop), with a disposable offline Linux desktop. Runs on macOS and Windows through Docker Desktop, and on Linux through Docker Engine (rootful or rootless) or Docker Desktop for Linux.

**Developer preview, version 0.1.** This release provides a working GTK demo and four restricted MCP tools. It does not operate native macOS, Windows, or Linux host apps, and it does not guarantee that every task can be performed without disclosing information.

```text
AI client ── sanitized MCP results / validated actions ── local gateway
                                                               │
                                                     Docker exec (no shell)
                                                               │
                                      offline Linux container + agent-desktop
```

The gateway replaces unapproved UI text with random, session-scoped placeholders. Raw values and token mappings remain local. Actions can target opaque element references without receiving the private text behind them.

## Requirements

- Python 3.10 or newer.
- **macOS or Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/), installed and running in **Linux containers** mode. Check Docker's current system requirements and licensing for your use.
- **Linux:** [Docker Engine](https://docs.docker.com/engine/install/) 23 or newer on an AMD64 or ARM64 host, either [rootless](https://docs.docker.com/engine/security/rootless/) (recommended) or the system daemon. Docker Desktop for Linux also works. Podman is not supported yet. See [Linux hosts](#linux-hosts).
- Internet access for the initial image build. Running the desktop itself is offline.

On Windows, use Docker Desktop's supported WSL 2 or Hyper-V backend. On Apple Silicon Macs, the build uses a native ARM64 Linux image; Intel Macs and x64 Windows use AMD64. Docker Desktop supplies the Linux VM. Each run gets a separate container inside that VM, **not a separate VM for each task**. On a Linux host with Docker Engine there is no VM: the container runs directly on the host kernel, using the host's architecture.

## Quick start

Download `private-desktop.pyz` and `SHA256SUMS` from [Releases](https://github.com/TianShen513/private-desktop/releases/latest). Keep the archive in a dedicated folder. Compare its SHA-256 hash with `SHA256SUMS` before running it.

macOS:

```sh
shasum -a 256 private-desktop.pyz
python3 private-desktop.pyz doctor
python3 private-desktop.pyz build
python3 private-desktop.pyz start
python3 private-desktop.pyz demo
python3 private-desktop.pyz stop
```

Linux:

```sh
sha256sum private-desktop.pyz
python3 private-desktop.pyz doctor
python3 private-desktop.pyz build
python3 private-desktop.pyz start
python3 private-desktop.pyz demo
python3 private-desktop.pyz stop
```

Windows PowerShell:

```powershell
Get-FileHash .\private-desktop.pyz -Algorithm SHA256
py -3 .\private-desktop.pyz doctor
py -3 .\private-desktop.pyz build
py -3 .\private-desktop.pyz start
py -3 .\private-desktop.pyz demo
py -3 .\private-desktop.pyz stop
```

Use a Python 3.10+ interpreter for these commands. A checksum downloaded from the same release detects file corruption; it is not an independent publisher signature.

The first build downloads Ubuntu packages and pinned agent-desktop release artifacts, then builds the local image. The desktop starts an offline GTK demo with synthetic private data. The `demo` command shows a filtered desktop observation in your terminal. There is no remote desktop viewer or published port in this release.

To install from source instead:

```sh
git clone https://github.com/TianShen513/private-desktop.git
cd private-desktop
python -m pip install .
private-desktop doctor
private-desktop build
private-desktop start
private-desktop demo
```

Use `python3` on macOS and Linux, or `py -3` on Windows, if `python` does not select your Python 3.10+ installation. On Linux distributions that mark the system Python as externally managed, install into a virtual environment (`python3 -m venv .venv && . .venv/bin/activate`) or use the archive. The installed `private-desktop` command and the archive expose the same interface.

## Connect an AI client

Start the desktop first, then print an MCP configuration:

```sh
private-desktop start
private-desktop client-config
```

With the archive, run `python3 private-desktop.pyz client-config` (macOS and Linux) or `py -3 .\private-desktop.pyz client-config` (Windows) instead. Copy the printed configuration into your MCP client's settings. It uses local stdio; there is no gateway HTTP port. The launcher does not modify your client configuration automatically.

The server provides only:

| Tool | Input | Behavior |
| --- | --- | --- |
| `desktop_status` | `{}` | Reports limited sandbox status. |
| `desktop_snapshot` | `{}` | Observes the fixed demo app and filters the result. |
| `desktop_click` | `{"ref": "..."}` | Clicks a reference issued by the latest gateway snapshot. |
| `desktop_type` | `{"ref": "...", "text": "..."}` | Types literal text into an issued reference. |

Keep action confirmations enabled in the client. Do not give the same cloud agent direct Docker, host shell, raw agent-desktop, or filesystem tools: those would bypass this gateway. See [client setup](docs/CLIENTS.md).

## Privacy boundary

- **Outgoing desktop data:** the gateway forwards a small structured projection. Unknown UI text becomes a random placeholder. Only an exact list of vetted UI labels is forwarded as readable text.
- **Incoming actions:** unknown tools and arguments are refused. References must come from the gateway's latest snapshot. Tokens are never expanded into secrets on request.
- **Desktop isolation:** no host folder mounts, Docker socket, published ports, or guest internet access. The container runs as a non-root user with dropped capabilities, a read-only root filesystem, temporary writable storage, and resource limits.
- **Local state:** token mappings are memory-only. Desktop snapshots are held in temporary guest storage. The launcher retains a random ownership identifier locally so it can manage its own container.

This is **tokenization**, not encrypted cloud inference. UI structure, allowed labels, actions, and timing remain observable. The AI client may retain filtered transcripts. User prompts and attachments sent directly to that client are **outside** this filter. Raw local memory and Docker administrative access are also outside the threat model.

For this first release, screenshots, raw clipboard access, arbitrary app launches, batches, live-value reads, secret restoration, and guest networking are unavailable. Reading confidential prose that the cloud must understand requires a local model or a deliberate disclosure decision. See the [threat model](docs/THREAT_MODEL.md) for the complete boundary.

## Linux hosts

The launcher talks to whichever local engine the `docker` command selects: the active Docker context, or `DOCKER_HOST` when no context is set. It accepts only local `unix://` sockets, and `doctor` names the problem when the engine is stopped, the socket is not accessible to your user, or the engine cannot enforce the container's limits.

**Rootless Docker (recommended).** Install it with Docker's [rootless guide](https://docs.docker.com/engine/security/rootless/) (`dockerd-rootless-setuptool.sh install`). The daemon then runs as your user, so a container escape lands in an unprivileged account rather than root. Two host settings matter:

- The sandbox always sets CPU, memory, and process limits, so the engine needs the cgroup v2 `cpu`, `memory`, and `pids` controllers. Many distributions delegate only `memory` and `pids` to users. If `doctor` reports that limits are unavailable, delegate the controllers, then log out and back in:

  ```sh
  sudo mkdir -p /etc/systemd/system/user@.service.d
  printf '[Service]\nDelegate=cpu cpuset io memory pids\n' \
    | sudo tee /etc/systemd/system/user@.service.d/delegate.conf
  sudo systemctl daemon-reload
  ```

- Ubuntu 24.04 and later restrict unprivileged user namespaces with AppArmor. Follow the rootless guide's AppArmor step if `dockerd-rootless-setuptool.sh` reports a user-namespace error.

The setup tool creates a `rootless` Docker context, or prints a `DOCKER_HOST=unix:///run/user/<uid>/docker.sock` line to export. Either works.

**System daemon.** If you use the root-owned daemon, `doctor` reports a permission problem until your user can open `/var/run/docker.sock`. The usual fix is `sudo usermod -aG docker "$USER"` and a new login. Membership in the `docker` group is equivalent to root on that machine, which is outside this project's threat model, so prefer rootless Docker on a shared or sensitive host. Running the launcher itself with `sudo` is not needed.

**Snap and other confined installs.** The image build streams its recipe to Docker over standard input, so engines with a private `/tmp`, such as the Ubuntu Docker snap, can build it.

**Not supported.** Podman, including the `podman-docker` compatibility command, inspects containers differently and is reported as unsupported. Rootless engines without subordinate UID ranges (`/etc/subuid`), which is common on centrally managed lab machines, cannot run the sandbox's non-root user.

## Develop and verify

```sh
python -m pip install .
python -m unittest discover -s tests -v
python tools/build_zipapp.py
private-desktop build
python tests/smoke_sandbox.py private-desktop:0.1.0
```

CI runs the Python tests on macOS, Windows, and Linux, and runs the real desktop smoke test on Linux with both the system Docker daemon and rootless Docker. These checks exercise the implementation; they are not a third-party security audit.

The Python gateway uses the standard library. The sandbox includes agent-desktop 1.1.0 with pinned archive checksums. Upstream agent-desktop is Apache-2.0 licensed; this project's original code is MIT licensed. Installed Linux packages retain their own licenses.

Report vulnerabilities through the process in [SECURITY.md](SECURITY.md). Do not attach raw desktop captures or private transcripts to public issues.
