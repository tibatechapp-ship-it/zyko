#!/data/data/com.termux/files/usr/bin/bash
# Termux:Widget shortcut — drop this file in ~/.shortcut/ and it appears in
# the Android home screen widget. Tapping it starts the ZYKO gateway.
source /data/data/com.termux/files/usr/bin/termux-toast 2>/dev/null || true
termux-toast "ZYKO gateway starting…" 2>/dev/null || true
zyko serve --host 127.0.0.1 --port 8787
