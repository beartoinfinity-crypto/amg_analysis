import threading
import tkinter as tk
from tkinter import ttk

from amg.cli import ingest_archives, scan_archives


class ArchivePicker:
    def __init__(self, root, archive_dir, db_path):
        self.root = root
        self.archive_dir = archive_dir
        self.db_path = db_path
        self.busy = False

        root.title("AMG Message Toolkit")
        root.geometry("760x520")

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Archives:").pack(side="left")
        ttk.Label(top, text=str(archive_dir), foreground="#555").pack(side="left", padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right")

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
        ttk.Checkbutton(
            bottom, text="Select all", variable=self.select_all_var,
            command=self.toggle_all,
        ).pack(side="left")
        self.import_button = ttk.Button(
            bottom, text="Import selected", command=self.start_import,
        )
        self.import_button.pack(side="right")
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
        self.busy = True
        self.import_button.state(["disabled"])
        paths = [self.archive_dir / name for name in names]
        total = len(paths)

        def worker():
            ingested = skipped = failed = 0
            for index, path in enumerate(paths, start=1):
                n_ing, n_skip, n_fail = ingest_archives([path], self.db_path)
                ingested += n_ing
                skipped += n_skip
                failed += n_fail
                self.root.after(0, self.set_status, f"importing {index}/{total}...")
            self.root.after(0, self.finish_import, ingested, skipped, failed)

        threading.Thread(target=worker, daemon=True).start()

    def set_status(self, text):
        self.status_var.set(text)

    def finish_import(self, ingested, skipped, failed):
        self.busy = False
        self.import_button.state(["!disabled"])
        self.refresh()
        self.status_var.set(
            f"done: {ingested} ingested, {skipped} skipped, {failed} failed"
        )


def run_gui(archive_dir, db_path):
    root = tk.Tk()
    ArchivePicker(root, archive_dir, db_path)
    root.mainloop()
    return 0
