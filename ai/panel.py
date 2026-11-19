"""Greeniac panel — a small window showing the services and their live logs.

Opened from the tray icon ("Abrir panel"). Shows each service's status, lets you
restart it, and tails its log so you can see what it's doing in real time. Reuses
the process helpers and service list from tray.py.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import tray  # SERVICES, is_running, restart, HERE
import singleton

BG = "#121e16"
SURF = "#1d2c23"
SURF2 = "#2a3c31"
TEXT = "#e7f6e7"
MUTED = "#a6c7b0"
ACCENT = "#62b83a"
DANGER = "#e06a5a"


def read_tail(path: str, n: int = 500) -> str:
    try:
        with open(os.path.join(tray.HERE, path), encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-n:])
    except OSError:
        return "(sin log todavía)"


class Panel:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Greeniac — Servicios")
        root.geometry("760x520")
        root.configure(bg=BG)
        try:
            root.iconbitmap(os.path.join(tray.HERE, "greeniac.ico"))
        except Exception:  # noqa: BLE001 — icon is cosmetic
            pass

        self.dots: dict[str, tk.Label] = {}
        self.toggles: dict[str, tk.Button] = {}
        self.selected = tk.StringVar(value=tray.SERVICES[0]["label"])

        # ── Services panel ──
        head = tk.Label(root, text="Servicios en la PC", bg=BG, fg=ACCENT,
                        font=("Segoe UI", 13, "bold"))
        head.pack(anchor="w", padx=14, pady=(12, 6))

        svc_frame = tk.Frame(root, bg=BG)
        svc_frame.pack(fill="x", padx=14)
        for svc in tray.SERVICES:
            row = tk.Frame(svc_frame, bg=SURF)
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="●", bg=SURF, fg=MUTED, font=("Segoe UI", 12))
            dot.pack(side="left", padx=(10, 8), pady=6)
            self.dots[svc["script"]] = dot
            tk.Label(row, text=svc["label"], bg=SURF, fg=TEXT,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Button(row, text="Reiniciar", bg=SURF2, fg=TEXT, relief="flat",
                      activebackground=ACCENT, cursor="hand2",
                      command=lambda s=svc: self.restart(s)).pack(side="right", padx=10, pady=4)
            toggle = tk.Button(row, text="Detener", bg=SURF2, fg=TEXT, relief="flat",
                               activebackground=DANGER, cursor="hand2", width=7,
                               command=lambda s=svc: self.toggle(s))
            toggle.pack(side="right")
            self.toggles[svc["script"]] = toggle
            tk.Button(row, text="Ver log", bg=SURF2, fg=TEXT, relief="flat",
                      activebackground=ACCENT, cursor="hand2",
                      command=lambda s=svc: self.selected.set(s["label"])).pack(side="right", padx=8)

        # ── Log viewer ──
        logbar = tk.Frame(root, bg=BG)
        logbar.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(logbar, text="Registro en vivo:", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        combo = ttk.Combobox(logbar, textvariable=self.selected, state="readonly",
                             values=[s["label"] for s in tray.SERVICES], width=28)
        combo.pack(side="left", padx=8)

        self.logbox = ScrolledText(root, bg="#0c130f", fg=TEXT, insertbackground=TEXT,
                                   font=("Consolas", 9), relief="flat", wrap="none")
        self.logbox.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self.refresh()

    def restart(self, svc: dict):
        self.dots[svc["script"]].config(fg=MUTED)
        threading.Thread(target=lambda: tray.restart(svc["script"]), daemon=True).start()

    def toggle(self, svc: dict):
        """Stop the service (and keep it stopped) or start it again."""
        script = svc["script"]
        self.dots[script].config(fg=MUTED)
        if tray.is_running(script):
            threading.Thread(target=lambda: tray.stop_service(script), daemon=True).start()
        else:
            threading.Thread(target=lambda: tray.start_service(script), daemon=True).start()

    def refresh(self):
        # status dots
        for svc in tray.SERVICES:
            script = svc["script"]
            running = tray.is_running(script)
            self.dots[script].config(fg=ACCENT if running else DANGER)
            self.toggles[script].config(text="Detener" if running else "Iniciar")
        # log of the selected service
        svc = next((s for s in tray.SERVICES if s["label"] == self.selected.get()), tray.SERVICES[0])
        at_bottom = self.logbox.yview()[1] > 0.999
        self.logbox.delete("1.0", "end")
        self.logbox.insert("1.0", read_tail(svc["log"]))
        if at_bottom:
            self.logbox.see("end")
        self.root.after(1500, self.refresh)


def main():
    guard = singleton.single_instance(47809)  # noqa: F841 — one panel window at a time
    # Give the window its own taskbar identity so Windows shows the Greeniac icon
    # instead of grouping it under the generic pythonw.exe (Python) icon.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Greeniac.Servicios")
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    Panel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
