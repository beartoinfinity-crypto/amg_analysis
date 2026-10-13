import tkinter as tk
from tkinter import messagebox, ttk

from amg import extractors
from amg.generator import normalize_text


class LDMExtractor:
    def __init__(self, root):
        self.root = root
        root.title('AMG LDM Field Extractor')
        root.geometry('900x700')
        root.minsize(700, 500)

        input_frame = ttk.LabelFrame(root, text='Paste raw LDM message', padding=8)
        input_frame.pack(fill='both', expand=False, padx=8, pady=8)
        self.input_text = tk.Text(input_frame, height=10, wrap='none',
                                  font=('Consolas', 10), undo=True)
        vscroll_in = ttk.Scrollbar(input_frame, orient='vertical',
                                   command=self.input_text.yview)
        hscroll_in = ttk.Scrollbar(input_frame, orient='horizontal',
                                   command=self.input_text.xview)
        self.input_text.configure(yscrollcommand=vscroll_in.set,
                                  xscrollcommand=hscroll_in.set)
        vscroll_in.pack(side='right', fill='y')
        hscroll_in.pack(side='bottom', fill='x')
        self.input_text.pack(fill='both', expand=True)

        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill='x', padx=8)
        ttk.Button(btn_frame, text='Extract fields', command=self.extract).pack(side='left')
        ttk.Button(btn_frame, text='Clear', command=self.clear_all).pack(side='left', padx=6)
        ttk.Button(btn_frame, text='Copy results', command=self.copy_results).pack(side='left')

        results_frame = ttk.LabelFrame(root, text='Extracted fields', padding=8)
        results_frame.pack(fill='both', expand=True, padx=8, pady=8)
        self.results = tk.Text(results_frame, wrap='none', font=('Consolas', 10),
                               state=tk.DISABLED, bg='#f8f9fa')
        vscroll_out = ttk.Scrollbar(results_frame, orient='vertical',
                                    command=self.results.yview)
        hscroll_out = ttk.Scrollbar(results_frame, orient='horizontal',
                                    command=self.results.xview)
        self.results.configure(yscrollcommand=vscroll_out.set,
                               xscrollcommand=hscroll_out.set)
        vscroll_out.pack(side='right', fill='y')
        hscroll_out.pack(side='bottom', fill='x')
        self.results.pack(fill='both', expand=True)

        self.status_var = tk.StringVar(value='Paste an LDM message and click Extract.')
        ttk.Label(root, textvariable=self.status_var, padding=8).pack(fill='x')

    def clear_all(self):
        self.input_text.delete('1.0', 'end')
        self.results.config(state=tk.NORMAL)
        self.results.delete('1.0', 'end')
        self.results.config(state=tk.DISABLED)
        self.status_var.set('Cleared.')
        self.input_text.focus_set()

    def extract(self):
        raw = self.input_text.get('1.0', 'end-1c').strip()
        if not raw:
            messagebox.showwarning('No input', 'Paste an LDM message first.')
            return
        text = normalize_text(raw)
        try:
            facts, segments = extractors.extract_load(text)
        except Exception as error:
            messagebox.showerror('Parse error', str(error))
            return
        lines = []
        lines.append('=== Header / aggregate facts ===')
        if facts.get('reg'):
            lines.append(f'  REG:        {facts["reg"]}')
        if facts.get('ac_type'):
            lines.append(f'  AC type:    {facts["ac_type"]}')
        if facts.get('crew'):
            c = facts['crew']
            lines.append(f'  CRW:        cockpit={c.get("cockpit", 0)}, '
                         f'cabin={c.get("cabin", 0)}, total={c.get("total", 0)}')
        if facts.get('cabins'):
            lines.append(f'  Cabins:     {facts["cabins"]}')
        for key, label in (('px7', 'PX7 (local)'), ('px6', 'PX6 (transit)'),
                           ('pax', 'PAX (total)'), ('px1', 'PX1 (first)'),
                           ('px2', 'PX2 (business)'), ('px3', 'PX3 (economy)'),
                           ('ddl', 'DDL (deadload)'), ('local_station', 'DES')):
            if key in facts:
                lines.append(f'  {label}: {facts[key]}')
        if facts.get('basic_weight'):
            lines.append(f'  BW:         {facts["basic_weight"]}')
        if facts.get('balance_index'):
            lines.append(f'  BI:         {facts["balance_index"]}')
        if facts.get('si'):
            lines.append(f'  SI:         {facts["si"]}')
        if facts.get('station_breakdown'):
            lines.append(f'  SI breakdown: {facts["station_breakdown"]}')

        lines.append('')
        lines.append(f'=== Destination segments ({len(segments)}) ===')
        for i, seg in enumerate(segments, 1):
            lines.append(f'  Segment {i}: dest={seg["dest"]}')
            lines.append(f'    Pax: adults={seg["adults"]}, children={seg["children"]}, '
                         f'infants={seg["infants"]}, total={seg["pax_total"]}')
            lines.append(f'    Deadload: {seg["deadload"]}')
            if seg.get('classes'):
                lines.append(f'    Classes: {seg["classes"]}')
            if seg.get('pads'):
                lines.append(f'    PAD:     {seg["pads"]}')
            if seg.get('categories'):
                lines.append(f'    Categories: {seg["categories"]}')
            if seg.get('nil_traffic'):
                lines.append(f'    NIL TRAFFIC')

        self.results.config(state=tk.NORMAL)
        self.results.delete('1.0', 'end')
        self.results.insert('1.0', '\n'.join(lines))
        self.results.config(state=tk.DISABLED)
        self.status_var.set(f'Extracted {len(segments)} segment(s) and '
                            f'{len(facts)} fact(s).')

    def copy_results(self):
        text = self.results.get('1.0', 'end-1c')
        if text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set('Results copied.')


def main(argv=None):
    root = tk.Tk()
    LDMExtractor(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
