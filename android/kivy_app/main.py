"""ZYKO Chat — a minimal native Android UI via Kivy (optional extra).

Install on device (Termux or Chaquopy-based packaging):

    pip install kivy          # or: pkg install python-kivy on some builds
    python main.py

The UI runs ZYKO in a worker thread (zyko's sync API is thread-safe by
design: the shared IO loop lives in its own daemon thread), so the interface
never freezes while the model responds.
"""

from __future__ import annotations

import threading

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

try:
    from zyko import Zyko
except ImportError as exc:  # pragma: no cover
    raise SystemExit("zyko is not installed — run: pip install . (see android/README.md)") from exc


class ZykoChatApp(App):
    def build(self):
        self.zyko = None
        self.title = "ZYKO Chat"

        root = BoxLayout(orientation="vertical", padding=8, spacing=8)

        self.log = Label(markup=True, halign="left", valign="top", size_hint_y=None)
        self.log.bind(width=lambda _i, w: setattr(self.log, "text_size", (w, None)))
        self.log.bind(texture_size=lambda _i, size: setattr(self.log, "height", size[1]))
        scroll = ScrollView()
        scroll.add_widget(self.log)
        root.add_widget(scroll)

        row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        self.input = TextInput(multiline=False, hint_text="Ask ZYKO…")
        self.input.bind(on_text_validate=self._on_send)
        send = Button(text="Send", size_hint_x=None, width=100)
        send.bind(on_press=self._on_send)
        row.add_widget(self.input)
        row.add_widget(send)
        root.add_widget(row)

        self._history = ""
        return root

    # ------------------------------------------------------------------ send
    def _on_send(self, *_args) -> None:
        prompt = self.input.text.strip()
        if not prompt:
            return
        self.input.text = ""
        self._append(f"[b]you:[/b] {prompt}")
        threading.Thread(target=self._worker, args=(prompt,), daemon=True).start()

    def _worker(self, prompt: str) -> None:
        try:
            if self.zyko is None:
                self.zyko = Zyko()
            outcome = self.zyko.ask(prompt)
            answer = outcome.response.text if outcome.response else "(no content)"
            via = outcome.receipt.get("chosen", "?")
            self._append(f"[color=1f8f4f][b]zyko[/b][/color] ({via}): {answer}")
        except Exception as exc:  # surface errors inside the chat log
            self._append(f"[color=a02020]error: {exc}[/color]")

    def _append(self, line: str) -> None:
        self._history += line + "\n\n"
        self.log.text = self._history


if __name__ == "__main__":
    ZykoChatApp().run()
