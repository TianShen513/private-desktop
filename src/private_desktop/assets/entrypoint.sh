#!/usr/bin/env bash
# All writable paths must be disposable tmpfs mounts supplied by the host launcher.
set -euo pipefail
umask 077
unset AT_SPI_BUS_ADDRESS NO_AT_BRIDGE GTK_A11Y WAYLAND_DISPLAY

mkdir -p "$XDG_RUNTIME_DIR" "$AGENT_DESKTOP_HOME" \
  "$XDG_CONFIG_HOME/glib-2.0/settings" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
chmod 0700 "$XDG_RUNTIME_DIR" "$AGENT_DESKTOP_HOME"
printf '[org/gnome/desktop/interface]\ntoolkit-accessibility=true\nenable-animations=false\n' \
  > "$XDG_CONFIG_HOME/glib-2.0/settings/keyfile"

children=()
cleanup() {
  trap - EXIT TERM INT HUP
  rm -f "$AGENT_DESKTOP_HOME/ready"
  for pid in "${children[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT HUP

dbus-daemon --session --nofork --address="$DBUS_SESSION_BUS_ADDRESS" \
  > "$XDG_RUNTIME_DIR/dbus.log" 2>&1 &
children+=("$!")
Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp \
  > "$XDG_RUNTIME_DIR/xvfb.log" 2>&1 &
children+=("$!")
for _ in {1..100}; do
  if [ -S "$XDG_RUNTIME_DIR/bus" ] && xdpyinfo >/dev/null 2>&1; then break; fi
  sleep 0.1
done
[ -S "$XDG_RUNTIME_DIR/bus" ] && xdpyinfo >/dev/null 2>&1 || {
  echo 'Private desktop display or session bus failed to start' >&2; exit 1;
}
dbus-update-activation-environment DISPLAY XDG_RUNTIME_DIR XDG_CONFIG_HOME \
  XDG_CACHE_HOME XDG_DATA_HOME GSETTINGS_BACKEND XDG_CURRENT_DESKTOP GDK_BACKEND

openbox --config-file /etc/xdg/openbox/rc.xml \
  > "$XDG_RUNTIME_DIR/openbox.log" 2>&1 &
children+=("$!")
for _ in {1..100}; do
  if xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id'; then break; fi
  sleep 0.1
done
xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id' || {
  echo 'Private desktop window manager failed to start' >&2; exit 1;
}

/opt/private-desktop/privacy-demo /opt/private-desktop/demo.py > "$XDG_RUNTIME_DIR/demo.log" 2>&1 &
demo_pid=$!
children+=("$demo_pid")
printf '%s\n' "$demo_pid" > "$AGENT_DESKTOP_HOME/demo.pid"

# Wait for real accessibility registration; readiness is not just a live GUI process.
ready=0
for _ in {1..100}; do
  kill -0 "$demo_pid" 2>/dev/null || break
  if agent-desktop snapshot --app privacy-demo --compact \
    > "$AGENT_DESKTOP_HOME/startup.json" 2> /dev/null; then ready=1; break; fi
  sleep 0.2
done
rm -f "$AGENT_DESKTOP_HOME/startup.json"
[ "$ready" -eq 1 ] || {
  echo 'Demo accessibility tree did not become available' >&2
  cat "$XDG_RUNTIME_DIR/demo.log" >&2
  exit 1
}
touch "$AGENT_DESKTOP_HOME/ready"
echo 'Private desktop ready (app: privacy-demo; networking must be disabled by launcher)'

# Exit when any critical child stops. Tini reaps D-Bus-activated grandchildren.
wait -n "${children[@]}"
exit 1
