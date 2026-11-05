# syntax=docker/dockerfile:1
FROM ubuntu:24.04

ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini python3 python3-gi gir1.2-gtk-3.0 \
      at-spi2-core dbus-x11 gsettings-desktop-schemas \
      xvfb x11-utils openbox fonts-dejavu-core \
      libx11-6 libxtst6 libxfixes3 libxrandr2 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Version and expected bytes are fixed in the build context, never fetched at build time.
COPY checksums.txt /opt/agent-desktop-checksums.txt
COPY AGENT_DESKTOP_LICENSE /usr/share/doc/agent-desktop/LICENSE
RUN set -eu; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      arm64) arch=aarch64 ;; amd64) arch=x86_64 ;; \
      *) echo 'Only Linux ARM64 and AMD64 are supported' >&2; exit 1 ;; \
    esac; \
    archive="agent-desktop-v1.1.0-${arch}-unknown-linux-gnu.tar.gz"; \
    cd /tmp; \
    curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
      "https://github.com/vercel-labs/agent-desktop/releases/download/v1.1.0/${archive}" \
      -o "$archive"; \
    awk -v file="$archive" '$2 == file {print}' /opt/agent-desktop-checksums.txt > expected.sha256; \
    test "$(wc -l < expected.sha256)" -eq 1; \
    sha256sum --check --strict expected.sha256; \
    mkdir -p /opt/agent-desktop; \
    tar --extract --gzip --file "$archive" --directory /opt/agent-desktop \
      --no-same-owner --no-same-permissions; \
    ln -s /opt/agent-desktop/agent-desktop /usr/local/bin/agent-desktop; \
    agent-desktop version; \
    rm "$archive" expected.sha256

# Ubuntu's base image can already have UID 1000 allocated to its unused ubuntu account.
RUN if getent passwd ubuntu >/dev/null; then userdel ubuntu; fi \
    && if getent group ubuntu >/dev/null; then groupdel ubuntu; fi \
    && groupadd --gid 1000 desktop \
    && useradd --uid 1000 --gid 1000 --home-dir /home/desktop --create-home desktop

COPY entrypoint.sh demo.py /opt/private-desktop/
# Linux agent-desktop identifies apps by executable basename, not a GTK label.
# A real executable copy (not a symlink) makes that selector unambiguous.
RUN cp /usr/bin/python3 /opt/private-desktop/privacy-demo \
    && chmod 0555 /opt/private-desktop/entrypoint.sh /opt/private-desktop/demo.py \
      /opt/private-desktop/privacy-demo

ENV HOME=/home/desktop \
    DISPLAY=:100 \
    XDG_RUNTIME_DIR=/run/user/1000 \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    XDG_CONFIG_HOME=/home/desktop/.config \
    XDG_CACHE_HOME=/home/desktop/.cache \
    XDG_DATA_HOME=/home/desktop/.local/share \
    GSETTINGS_BACKEND=keyfile \
    XDG_CURRENT_DESKTOP=GNOME \
    GDK_BACKEND=x11 \
    AGENT_DESKTOP_HOME=/run/private-desktop \
    AGENT_DESKTOP_SESSION=private-demo \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHOME=/usr \
    LC_ALL=C.UTF-8

USER 1000:1000
WORKDIR /home/desktop
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
  CMD test -f /run/private-desktop/ready && kill -0 "$(cat /run/private-desktop/demo.pid)"
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/private-desktop/entrypoint.sh"]
