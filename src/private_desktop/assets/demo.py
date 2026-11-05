#!/usr/bin/env python3
"""An offline GTK target for exercising real accessibility actions."""
import ctypes

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

GLib.set_prgname("privacy-demo")
GLib.set_application_name("privacy-demo")
ctypes.CDLL(None).prctl(15, b"privacy-demo", 0, 0, 0)

window = Gtk.Window(title="Private Desktop Demo")
window.set_default_size(560, 340)
window.set_border_width(24)
window.connect("destroy", Gtk.main_quit)
layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
window.add(layout)

heading = Gtk.Label(label="Disposable desktop")
heading.set_xalign(0)
layout.pack_start(heading, False, False, 0)
label = Gtk.Label(label="Only synthetic data belongs in this demo.")
label.set_xalign(0)
layout.pack_start(label, False, False, 0)

entry = Gtk.Entry()
entry.set_placeholder_text("Write a demo note")
entry.get_accessible().set_name("Demo note")
layout.pack_start(entry, False, False, 0)

save = Gtk.Button(label="Save note")
save.get_accessible().set_name("Save note")
layout.pack_start(save, False, False, 0)
status = Gtk.Label(label="No note saved")
status.set_xalign(0)
layout.pack_start(status, False, False, 0)
save.connect("clicked", lambda _button: status.set_text("Saved: " + entry.get_text()))

# A deliberately private-looking value for local redaction tests. It is synthetic.
private_label = Gtk.Label(label="SYNTHETIC_PRIVATE_SENTINEL_7f39b2")
private_label.set_xalign(0)
layout.pack_start(private_label, False, False, 0)
window.show_all()
Gtk.main()
