import argparse
import queue
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinter import simpledialog

from amg import generator, sender


class MessageGenerator:
    def __init__(self, root, db_path):
        self.root = root
        self.db_path = Path(db_path)
        self.fields = []
        self.entries = []
        self.template_id = None
        self.current_text = ''
        self.current_type = ''
        self.results = queue.Queue()
        self.busy = False
        root.title('AMG Test Message Generator')
        root.geometry('1100x850')
        root.minsize(850, 650)
        top = ttk.Frame(root, padding=8)
        top.pack(fill='x')
        self.db_var = tk.StringVar(value=str(db_path))
        ttk.Label(top, textvariable=self.db_var).pack(side='left')
        ttk.Button(top, text='Choose template library', command=self.choose_database).pack(side='right')
        picker = ttk.LabelFrame(root, text='1. Template library (JSON or database; read-only)', padding=8)
        picker.pack(fill='x', padx=8)
        controls = ttk.Frame(picker)
        controls.pack(fill='x')
        self.msg_type = tk.StringVar(value='PNL')
        self.flight_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.plain_var = tk.BooleanVar(value=False)
        ttk.Label(controls, text='Type').pack(side='left')
        self.type_box = ttk.Combobox(controls, textvariable=self.msg_type, width=8, state='readonly')
        self.type_box.pack(side='left', padx=4)
        self.type_box.bind('<<ComboboxSelected>>', lambda event: self.search_templates())
        for label, var, width in (
            ('Flight filter', self.flight_var, 12),
            ('Scheduled date filter YYYY-MM-DD', self.date_var, 12),
        ):
            ttk.Label(controls, text=label).pack(side='left')
            ttk.Entry(controls, textvariable=var, width=width).pack(side='left', padx=4)
        self.search_button = ttk.Button(controls, text='Search', command=self.search_templates)
        self.search_button.pack(side='left', padx=4)
        self.plain_checkbox = ttk.Checkbutton(
            picker, text='Load un-redacted database original (may contain personal data)',
            variable=self.plain_var, command=self.toggle_plain,
        )
        self.plain_checkbox.pack(anchor='w', pady=4)
        columns = ('id', 'flight', 'date', 'airport', 'received', 'part')
        self.tree = ttk.Treeview(picker, columns=columns, show='headings', height=5, selectmode='browse')
        for col, title, width in (
            ('id', 'ID', 70), ('flight', 'Flight', 100), ('date', 'Scheduled date', 120),
            ('airport', 'Header airport', 120), ('received', 'Received', 180), ('part', 'Part', 60),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill='x')
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        metadata = ttk.Frame(root, padding=8)
        metadata.pack(fill='x')
        ttk.Label(metadata, text='Test direction (relative to HKG; metadata, not a body rewrite):').pack(side='left')
        self.direction_var = tk.StringVar(value='unspecified')
        ttk.Combobox(metadata, textvariable=self.direction_var,
                     values=('unspecified', 'arrival', 'departure'), state='readonly', width=14).pack(side='left', padx=8)
        editor = ttk.LabelFrame(root, text='2. Structured edits (blank keeps original; apply explicitly)', padding=8)
        editor.pack(fill='both', expand=True, padx=8)
        ttk.Button(editor, text='Apply fields to template', command=self.update_preview).pack(anchor='e')
        self.canvas = tk.Canvas(editor, height=140, highlightthickness=0)
        scroll = ttk.Scrollbar(editor, orient='vertical', command=self.canvas.yview)
        self.rows_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor='nw', tags='frame')
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure('frame', width=event.width))
        self.rows_frame.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        preview = ttk.LabelFrame(root, text='3. Editable preview (copy/save exports exactly this text)', padding=8)
        preview.pack(fill='both', expand=True, padx=8, pady=8)
        text_frame = ttk.Frame(preview)
        text_frame.pack(fill='both', expand=True)
        self.preview = tk.Text(text_frame, height=14, wrap='none', font=('Consolas', 10), undo=True)
        vscroll = ttk.Scrollbar(text_frame, orient='vertical', command=self.preview.yview)
        hscroll = ttk.Scrollbar(text_frame, orient='horizontal', command=self.preview.xview)
        self.preview.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        vscroll.pack(side='right', fill='y')
        hscroll.pack(side='bottom', fill='x')
        self.preview.pack(fill='both', expand=True)
        buttons = ttk.Frame(preview)
        buttons.pack(fill='x', pady=4)
        self.send_btn = ttk.Button(buttons, text='Send', command=self.on_send)
        self.send_btn.pack(side='right')
        ttk.Button(buttons, text='Copy preview', command=self.copy_message).pack(side='right', padx=6)
        ttk.Button(buttons, text='Save plain .txt', command=lambda: self.save_message(False)).pack(side='right', padx=6)
        ttk.Button(buttons, text='Save framed .rcv', command=lambda: self.save_message(True)).pack(side='right')

        log_frame = ttk.LabelFrame(root, text='Send log', padding=4)
        log_frame.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.send_log = tk.Text(log_frame, height=6, wrap='word', font=('Consolas', 9),
                                state=tk.DISABLED, bg='#f8f9fa')
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.send_log.yview)
        self.send_log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side='right', fill='y')
        self.send_log.pack(fill='both', expand=True)
        self._append_log('Ready. Load a template and click Send.\n')

        self.warning_var = tk.StringVar(value='Select a template library and template. No messages are sent or ingested.')
        ttk.Label(root, textvariable=self.warning_var, wraplength=1020, padding=8).pack(fill='x')
        self.poll_id = root.after(100, self.poll_results)
        self.send_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self.config_password: str | None = None
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_types()

    def close(self):
        self.root.after_cancel(self.poll_id)
        self.root.destroy()

    def clear_template(self):
        self.template_id = None
        self.current_text = ''
        self.current_type = ''
        self.fields = []
        self.render_rows()
        self.preview.delete('1.0', 'end')

    def choose_database(self):
        if self.busy:
            return
        chosen = filedialog.askopenfilename(
            title='Choose template library',
            filetypes=[('JSON template libraries', '*.json'),
                       ('SQLite databases', '*.db *.sqlite *.sqlite3'), ('All files', '*.*')],
        )
        if chosen:
            self.db_path = Path(chosen)
            self.db_var.set(chosen)
            self.plain_var.set(False)
            self.flight_var.set('')
            self.date_var.set('')
            self.clear_template()
            self.refresh_types()

    def is_json_library(self):
        return self.db_path.suffix.lower() == '.json'

    def refresh_types(self):
        if self.is_json_library():
            self.plain_var.set(False)
            self.plain_checkbox.state(['disabled'])
        else:
            self.plain_checkbox.state(['!disabled'])
        self.tree.delete(*self.tree.get_children())
        self.type_box.configure(values=())
        try:
            types = generator.message_types(self.db_path)
            self.type_box.configure(values=types)
            if self.msg_type.get() not in types:
                self.msg_type.set(types[0] if types else '')
            self.search_templates()
        except (ValueError, OSError, sqlite3.Error) as error:
            self.msg_type.set('')
            self.warning_var.set(f'Cannot open template library: {error}. Choose an existing JSON library or AMG database.')

    def search_templates(self):
        if self.busy:
            return
        self.clear_template()
        self.tree.delete(*self.tree.get_children())
        self.busy = True
        self.search_button.state(['disabled'])
        self.type_box.state(['disabled'])
        self.warning_var.set('Searching template library...')
        args = (self.db_path, self.msg_type.get(), self.flight_var.get(), self.date_var.get())

        def worker():
            try:
                self.results.put((generator.templates(*args), None))
            except Exception as error:
                self.results.put(([], str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_results(self):
        try:
            rows, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.search_button.state(['!disabled'])
            self.type_box.state(['!disabled'])
            for row in rows:
                self.tree.insert('', 'end', iid=str(row[0]), values=tuple('' if v is None else v for v in row))
            self.warning_var.set(f'Search failed: {error}' if error else f'{len(rows)} matching templates. Select a template.')
        self.poll_id = self.root.after(100, self.poll_results)

    def on_select(self, event=None):
        selection = self.tree.selection()
        if selection:
            self.template_id = int(selection[0])
            self.load_preview()

    def toggle_plain(self):
        if self.is_json_library():
            self.plain_var.set(False)
            return
        if self.plain_var.get() and not messagebox.askyesno(
            'Historical personal data', 'The original may contain passenger names and contact details. Load it locally?',
        ):
            self.plain_var.set(False)
            return
        self.load_preview()

    def load_preview(self):
        if self.template_id is None:
            return
        try:
            plain = self.plain_var.get() and not self.is_json_library()
            msg_type, text = generator.load_template(self.db_path, self.template_id, plain)
            self.current_text = generator.normalize_text(text)
            self.current_type = msg_type
            self.fields = generator.editable_fields(self.current_text, msg_type)
            self.render_rows()
            self.preview.delete('1.0', 'end')
            self.preview.insert('1.0', self.current_text)
            self.preview.edit_modified(False)
            self.show_review_warnings(self.current_text, msg_type)
        except Exception as error:
            self.clear_template()
            messagebox.showerror('Load failed', str(error))

    def show_review_warnings(self, text, msg_type):
        warnings = generator.review_warnings(text, msg_type)
        if self.is_json_library():
            warnings = [warning for warning in warnings if not warning.startswith('Historical text may contain')]
            warnings = [warning.replace('historical part', 'template part') for warning in warnings]
            warnings.insert(0, 'Test template. Review all content before use; no messages are sent or ingested.')
        self.warning_var.set(' | '.join(warnings))

    def render_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self.entries = []
        for field in self.fields:
            row = ttk.Frame(self.rows_frame)
            row.pack(fill='x', pady=1)
            ttk.Label(row, text=field.label, width=34, anchor='w').pack(side='left')
            entry = ttk.Entry(row, width=18)
            entry.pack(side='left', padx=4)
            ttk.Label(row, text=f'Original: {field.value}').pack(side='left', padx=6)
            self.entries.append(entry)
        if not self.fields:
            ttk.Label(self.rows_frame, text='No structured fields selected. Unrecognized formats can be edited in the preview.').pack(anchor='w')

    def update_preview(self):
        if not self.current_text:
            return
        try:
            text = generator.apply_fields(self.current_text, self.fields, [entry.get() for entry in self.entries])
        except ValueError as error:
            messagebox.showerror('Invalid field', str(error))
            return
        if self.preview.edit_modified() and not messagebox.askyesno(
            'Replace preview?', 'Applying fields starts from the selected template and replaces manual preview edits. Continue?',
        ):
            return
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', text)
        self.preview.edit_modified(False)
        self.show_review_warnings(text, self.current_type)

    def copy_message(self):
        text = self.preview.get('1.0', 'end-1c')
        if text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.warning_var.set('Preview copied. Review all content before sharing.')

    def save_message(self, framed):
        text = self.preview.get('1.0', 'end-1c')
        if not text.strip():
            return
        suffix = '.rcv' if framed else '.txt'
        path = filedialog.asksaveasfilename(
            defaultextension=suffix,
            initialfile=f'test_{self.current_type}_{self.direction_var.get()}_{self.template_id}{suffix}',
            filetypes=[('Test message', '*' + suffix)],
        )
        if not path:
            return
        try:
            target = Path(path)
            if (target.resolve() == self.db_path.resolve()
                    or (target.exists() and target.samefile(self.db_path))):
                messagebox.showerror('Save blocked', 'Cannot overwrite the active template library.')
                return
            generator.save_message(path, text, framed)
            self.warning_var.set(f'Saved {path}. No message was sent or ingested.')
        except (ValueError, OSError, UnicodeError) as error:
            messagebox.showerror('Save failed', str(error))

    def _append_log(self, text: str):
        if self.send_log is None:
            return
        self.send_log.config(state=tk.NORMAL)
        self.send_log.insert(tk.END, text)
        self.send_log.see(tk.END)
        self.send_log.config(state=tk.DISABLED)

    def on_send(self):
        text = self.preview.get('1.0', 'end-1c').strip()
        if not text:
            messagebox.showwarning('No message', 'Nothing to send. Load and edit a template first.')
            return
        if not messagebox.askyesno('Confirm send', 'Send this message to the API?'):
            return
        if self.send_btn is not None:
            self.send_btn.config(state=tk.DISABLED)
        self._append_log('\n' + '=' * 40 + '\n')
        self._append_log('Loading config...\n')

        def ask_password() -> str:
            import threading as _threading
            event = _threading.Event()
            result: list[str] = []

            def _prompt():
                r = simpledialog.askstring(
                    'Config password',
                    'Enter master password for .env.enc:',
                    show='*',
                    parent=self.root,
                )
                result.append(r if r else '')
                event.set()

            self.root.after(0, _prompt)
            event.wait()
            pw = result[0]
            if pw:
                self.config_password = pw
            return pw

        def worker():
            try:
                config = sender.load_config(
                    password=self.config_password,
                    password_prompt=ask_password,
                )
                self._append_log(f'POST {config["API_URL"]}\n')
                result = sender.send_message(text, config)
                status = result['status_code']
                body = result.get('body', '')
                self._append_log(f'Status: {status}\n')
                if body:
                    self._append_log(f'Response: {body}\n')
                self._append_log('Message sent successfully.\n')
            except Exception as error:
                self._append_log(f'Error: {error}\n')
            finally:
                if self.send_btn is not None:
                    self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()


def run_generator(db_path):
    root = tk.Tk()
    MessageGenerator(root, db_path)
    root.mainloop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Standalone AMG test-message generator')
    parser.add_argument('--db', '--templates', dest='db', metavar='PATH',
                        help='JSON template library or AMG database (default: bundled JSON library)')
    args = parser.parse_args(argv)
    path = Path(args.db) if args.db is not None else generator.default_template_path()
    return run_generator(path)


if __name__ == '__main__':
    main()
