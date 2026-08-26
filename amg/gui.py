import threading
import tkinter as tk
from tkinter import messagebox, ttk

from amg.cli import ingest_archives, rebuild_archives, scan_archives


class ArchivePicker:
    def __init__(self, root, archive_dir, db_path):
        self.root = root
        self.archive_dir = archive_dir
        self.db_path = db_path
        self.busy = False
        self.stop_event = threading.Event()

        root.title("AMG Message Toolkit")
        root.geometry("760x520")

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Archives:").pack(side="left")
        ttk.Label(top, text=str(archive_dir), foreground="#555").pack(side="left", padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right")

        guide = ttk.Label(
            root, padding=(8, 0),
            foreground="#555",
            text="New archives: tick them (pending are pre-ticked) -> Import selected."
                 "   |   Full rebuild ignores ticks: wipes and re-parses ALL archives.",
        )
        guide.pack(fill="x")

        columns = ("pick", "name", "size", "state")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="none")
        for col, text, width, anchor in (
            ("pick", "", 40, "center"),
            ("name", "Archive", 380, "w"),
            ("size", "Size (MB)", 90, "e"),
            ("state", "State", 90, "center"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<Button-1>", self.on_click)

        bottom = ttk.Frame(root, padding=8)
        bottom.pack(fill="x")
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_cb = ttk.Checkbutton(
            bottom, text="Select all", variable=self.select_all_var,
            command=self.toggle_all,
        )
        self.select_all_cb.pack(side="left")
        self.import_button = ttk.Button(
            bottom, text="Import selected", command=self.start_import,
        )
        self.import_button.pack(side="right")
        self.rebuild_button = ttk.Button(
            bottom, text="Full rebuild", command=self.start_rebuild,
        )
        self.rebuild_button.pack(side="right", padx=6)
        self.stop_button = ttk.Button(
            bottom, text="Stop", command=self.stop_work, state=["disabled"],
        )
        self.stop_button.pack(side="right")
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right", padx=12)

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        entries = scan_archives(self.archive_dir, self.db_path)
        for entry in entries:
            checked = entry["state"] == "pending"
            self.tree.insert("", "end", iid=entry["name"], values=(
                "\u2611" if checked else "\u2610",
                entry["name"],
                f"{entry['size_bytes'] / (1024 * 1024):.2f}",
                entry["state"],
            ))
        if not self.busy:
            pending = sum(1 for e in entries if e["state"] == "pending")
            self.status_var.set(f"{pending} pending")

    def on_click(self, event):
        item = self.tree.identify_row(event.y)
        if item and not self.busy:
            values = list(self.tree.item(item, "values"))
            values[0] = "\u2610" if values[0] == "\u2611" else "\u2611"
            self.tree.item(item, values=values)

    def toggle_all(self):
        mark = "\u2611" if self.select_all_var.get() else "\u2610"
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = mark
            self.tree.item(item, values=values)

    def selected_names(self):
        return [
            item for item in self.tree.get_children()
            if self.tree.item(item, "values")[0] == "\u2611"
        ]

    def start_import(self):
        if self.busy:
            return
        names = self.selected_names()
        if not names:
            self.status_var.set("nothing selected")
            return
        paths = [self.archive_dir / name for name in names]
        if not messagebox.askyesno(
            "Import selected",
            f"Import {len(paths)} selected archive(s)?\n"
            "Already-indexed archives are skipped automatically.",
        ):
            return
        self.run_in_background(paths, rebuild=False)

    def start_rebuild(self):
        if self.busy:
            return
        names = list(self.tree.get_children())
        if not names:
            self.status_var.set("no archives found")
            return
        if not messagebox.askyesno(
            "Full rebuild",
            f"Re-parse ALL {len(names)} archives from scratch?\n"
            "Your tick-selection is ignored - every archive is rebuilt.\n"
            "Existing parsed data is replaced (about 1-2 minutes).",
        ):
            return
        paths = [self.archive_dir / name for name in names]
        self.run_in_background(paths, rebuild=True)

    def run_in_background(self, paths, rebuild):
        self.busy = True
        self.stop_event.clear()
        self.import_button.state(["disabled"])
        self.rebuild_button.state(["disabled"])
        self.select_all_cb.state(["disabled"])
        self.stop_button.state(["!disabled"])
        work = rebuild_archives if rebuild else ingest_archives
        label = "rebuilding" if rebuild else "importing"

        def progress(done, total, ingested, failed):
            self.root.after(
                0, self.set_status,
                f"{label} {done}/{total} - {ingested} imported, {failed} failed",
            )

        def should_stop():
            return self.stop_event.is_set()

        def worker():
            try:
                ingested, skipped, failed = work(
                    paths, self.db_path,
                    progress=lambda done, total, ing, skip, fail:
                        progress(done, total, ing, fail),
                    should_stop=should_stop,
                )
                stopped = self.stop_event.is_set()
                self.root.after(0, self.finish_import,
                                ingested, skipped, failed, stopped)
            except Exception as error:
                self.root.after(0, self.finish_error, str(error))

        threading.Thread(target=worker, daemon=True).start()

    def stop_work(self):
        self.stop_event.set()
        self.status_var.set("stopping after current archive...")

    def _set_busy(self, busy):
        state = ["disabled"] if busy else ["!disabled"]
        self.import_button.state(state)
        self.rebuild_button.state(state)
        self.select_all_cb.state(state)
        self.stop_button.state(["!disabled" if busy else "disabled"])

    def finish_error(self, message):
        self._set_busy(False)
        self.status_var.set(f"failed: {message}")

    def set_status(self, text):
        self.status_var.set(text)

    def finish_import(self, ingested, skipped, failed, stopped=False):
        self.busy = False
        self._set_busy(False)
        self.refresh()
        prefix = "stopped" if stopped else "done"
        self.status_var.set(
            f"{prefix}: {ingested} ingested, {skipped} skipped, {failed} failed"
        )


def run_gui(archive_dir, db_path):
    root = tk.Tk()
    ArchivePicker(root, archive_dir, db_path)
    root.mainloop()
    return 0
