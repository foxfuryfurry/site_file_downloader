"""Tkinter interface for searching Rule34 tags and downloading results."""

import queue
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from .config import load_config
from .services.download_service import download_by_tags


class DownloaderApp:
    """Desktop UI for the Rule34 tag-based downloader."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Rule34 Tag Downloader")
        self.root.minsize(560, 400)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.is_downloading = False
        self.tags = tk.StringVar()
        self._build_ui()
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        ttk.Label(frame, text="Search tags (space-separated):").grid(
            row=0, column=0, sticky=tk.W
        )
        tag_entry = ttk.Entry(frame, textvariable=self.tags)
        tag_entry.grid(row=1, column=0, sticky=tk.EW, pady=(4, 10))
        tag_entry.bind("<Return>", lambda _event: self._start_download())

        self.download_button = ttk.Button(
            frame, text="Search and download", command=self._start_download
        )
        self.download_button.grid(row=3, column=0, sticky=tk.W, pady=(0, 10))

        self.log = tk.Text(frame, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.log.grid(row=4, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.grid(row=4, column=1, sticky=tk.NS)
        self.log.configure(yscrollcommand=scrollbar.set)

    def _append_log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _start_download(self) -> None:
        if self.is_downloading:
            return
        tags = self.tags.get().strip()
        if not tags:
            messagebox.showinfo("Tags required", "Enter one or more tags to search.")
            return

        self.is_downloading = True
        self.download_button.configure(state=tk.DISABLED)
        self._append_log(f"Searching for: {tags}")
        threading.Thread(
            target=self._download_worker, args=(tags,), daemon=True
        ).start()

    def _download_worker(self, tags: str) -> None:
        try:
            config = load_config()
            download_by_tags(tags, config, lambda message: self.events.put(("log", message)))
            self.events.put(("done", ""))
        except Exception as exc:
            diagnostic = traceback.format_exc()
            print(f"Download worker failed: {exc}", flush=True)
            print(diagnostic, flush=True)
            self.events.put(("debug", diagnostic))
            self.events.put(("error", str(exc)))

    def _process_events(self) -> None:
        while True:
            try:
                event, message = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self._append_log(message)
            elif event == "debug":
                self._append_log(f"Debug traceback:\n{message}")
            elif event == "error":
                self._append_log(f"Error: {message}")
                messagebox.showerror("Download failed", message)
                self._finish_download()
            elif event == "done":
                self._finish_download()
        self.root.after(100, self._process_events)

    def _finish_download(self) -> None:
        self.is_downloading = False
        self.download_button.configure(state=tk.NORMAL)


def run_app() -> None:
    """Create and run the desktop application."""
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
