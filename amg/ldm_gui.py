import tkinter as tk
from tkinter import messagebox, ttk

from amg import extractors
from amg.generator import normalize_text


class ExtractorTab:
    def __init__(self, parent, label, extract_fn):
        self.extract_fn = extract_fn
        frame = ttk.Frame(parent, padding=8)

        input_frame = ttk.LabelFrame(frame, text=label, padding=8)
        input_frame.pack(fill='both', expand=False)
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

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', pady=4)
        ttk.Button(btn_frame, text='Extract fields', command=self.extract).pack(side='left')
        ttk.Button(btn_frame, text='Clear', command=self.clear_all).pack(side='left', padx=6)
        ttk.Button(btn_frame, text='Copy results', command=self.copy_results).pack(side='left')

        results_frame = ttk.LabelFrame(frame, text='Extracted fields', padding=8)
        results_frame.pack(fill='both', expand=True)
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

        self.frame = frame

    def clear_all(self):
        self.input_text.delete('1.0', 'end')
        self.results.config(state=tk.NORMAL)
        self.results.delete('1.0', 'end')
        self.results.config(state=tk.DISABLED)
        self.input_text.focus_set()

    def extract(self):
        raw = self.input_text.get('1.0', 'end-1c').strip()
        if not raw:
            messagebox.showwarning('No input', 'Paste a message first.')
            return
        text = normalize_text(raw)
        try:
            lines = self.extract_fn(text)
        except Exception as error:
            messagebox.showerror('Parse error', str(error))
            return
        self.results.config(state=tk.NORMAL)
        self.results.delete('1.0', 'end')
        self.results.insert('1.0', '\n'.join(lines))
        self.results.config(state=tk.DISABLED)

    def copy_results(self):
        text = self.results.get('1.0', 'end-1c')
        if text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)


def _extract_ldm(text):
    facts, segments = extractors.extract_load(text)
    lines = ['=== Header / aggregate facts ===']
    for key, label in (('reg', 'REG'), ('ac_type', 'AC type')):
        if facts.get(key):
            lines.append(f'  {label}: {facts[key]}')
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
    for key, label in (('basic_weight', 'BW'), ('balance_index', 'BI')):
        if facts.get(key):
            lines.append(f'  {label}: {facts[key]}')
    if facts.get('si'):
        lines.append(f'  SI: {facts["si"]}')
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
            lines.append(f'    PAD: {seg["pads"]}')
        if seg.get('categories'):
            lines.append(f'    Categories: {seg["categories"]}')
        if seg.get('nil_traffic'):
            lines.append(f'    NIL TRAFFIC')
    return lines


def _extract_mvt(text):
    facts = extractors.extract_movement(text)
    lines = ['=== MVT / MVA extracted facts ===']
    times = facts.get('times', {})
    time_labels = {
        'AD': 'AD (actual off-blocks)', 'EO': 'EO (estimated airborne)',
        'EL': 'EL (estimated landing)', 'EA': 'EA (estimated on-blocks)',
        'AA': 'AA (actual on-blocks)', 'TD': 'TD (actual touchdown)',
        'ED': 'ED (estimated departure)', 'RA': 'RA (revised arrival)',
    }
    for code, label in time_labels.items():
        if code in times:
            t = times[code]
            date_part = f' date={t["date"]}' if t.get('date') else ''
            lines.append(f'  {label}: {t["time"]}{date_part}')
    if facts.get('destination'):
        lines.append(f'  Destination: {facts["destination"]}')
    if facts.get('adp'):
        lines.append(f'  ADP: yes')
    if facts.get('abp'):
        lines.append(f'  ABP: yes')
    pax = facts.get('pax', {})
    if pax:
        parts = []
        if 'total' in pax:
            parts.append(f'total={pax["total"]}')
        if 'transit' in pax:
            parts.append(f'transit={pax["transit"]}')
        if 'disembarking' in pax:
            parts.append(f'disembarking={pax["disembarking"]}')
        if 'infants' in pax:
            parts.append(f'infants={pax["infants"]}')
        lines.append(f'  PAX: {", ".join(parts)}')
    delays = facts.get('delays', {})
    if delays:
        lines.append('')
        lines.append(f'=== Delay slots ({len(delays)}) ===')
        for slot, value in sorted(delays.items()):
            lines.append(f'  {slot}: {value}')
    if facts.get('delay_codes'):
        lines.append(f'  Delay codes: {facts["delay_codes"]}')
    if facts.get('delay_durations'):
        lines.append(f'  Delay durations: {facts["delay_durations"]}')
    if facts.get('si'):
        lines.append('')
        lines.append('=== SI section ===')
        si = facts['si']
        if isinstance(si, dict):
            for k, v in si.items():
                lines.append(f'  {k}: {v}')
        else:
            lines.append(f'  {si}')
    return lines


def _extract_fwd(text):
    facts, segments = extractors.extract_forward(text)
    lines = ['=== FWD extracted facts ===']
    if facts.get('crew'):
        lines.append(f'  Crew: {facts["crew"]}')
    if facts.get('destination'):
        lines.append(f'  Final destination: {facts["destination"]}')
    if facts.get('hops'):
        lines.append(f'  Hops: {facts["hops"]}')
    for dest in facts.get('destinations', []):
        parts = [f'{k}={v}' for k, v in dest.items() if k != 'nationalities']
        lines.append(f'  {dest.get("airport", "?")}: {", ".join(parts)}')
        if dest.get('nationalities'):
            nats = ', '.join(f'{c}={n}' for c, n in dest['nationalities'].items())
            lines.append(f'    Nationalities: {nats}')
    if facts.get('nationalities'):
        lines.append(f'  Merged nationalities: {facts["nationalities"]}')
    if facts.get('rows'):
        lines.append(f'  Transfer rows: {facts["rows"]}')
    lines.append('')
    lines.append(f'=== Transfer rows ({len(segments)}) ===')
    for i, seg in enumerate(segments, 1):
        lines.append(f'  {i}. hop={seg["hop"]}, flight={seg["flight"]}, '
                     f'dest={seg["destination"]}, detail={seg["detail"]}')
    return lines


def _extract_div(text):
    facts = extractors.extract_diversion(text)
    lines = ['=== DIV extracted facts ===']
    if facts.get('can'):
        lines.append(f'  CAN (cancelled/diverted): yes')
    if 'pob' in facts:
        lines.append(f'  PX (passengers on board): {facts["pob"]}')
    if 'eta' in facts:
        lines.append(f'  EA (estimated arrival): {facts["eta"]}')
    if 'dva' in facts:
        lines.append(f'  DVA (diverted airport): {facts["dva"]}')
    return lines


def _extract_ptm(text):
    facts, segments = extractors.extract_transfer(text)
    lines = ['=== PTM extracted facts ===']
    if 'total_transfers' in facts:
        lines.append(f'  PX5 (total transfers): {facts["total_transfers"]}')
    if 'total_baggage' in facts:
        lines.append(f'  BG2 (total bags): {facts["total_baggage"]}')
    if 'segments' in facts:
        lines.append(f'  Rows: {facts["segments"]}')
    lines.append('')
    lines.append(f'=== Transfer rows ({len(segments)}) ===')
    for i, seg in enumerate(segments, 1):
        lines.append(f'  {i}. flight={seg["flight"]}, day={seg["day"]}, '
                     f'dest={seg["airports"]}, detail={seg["cabin_bags"]}')
    return lines


def _extract_assist(text):
    facts = extractors.extract_assistance(text)
    lines = ['=== PSM / PAL / CAL extracted facts ===']
    if facts.get('assist_codes'):
        lines.append(f'  Assist codes: {", ".join(facts["assist_codes"])}')
    if facts.get('delta'):
        d = facts['delta']
        lines.append(f'  Delta: ADD={d.get("ADD", 0)}, '
                     f'DEL={d.get("DEL", 0)}, CHG={d.get("CHG", 0)}')
    if 'pax_total' in facts:
        lines.append(f'  PXR (PRM pax total): {facts["pax_total"]}')
    return lines


def _extract_asm(text):
    return [
        '=== ASM (Ad-Hoc Schedule) ===',
        'ASM messages are muted by default (ASM_AIRLINES_TO_PROCESS).',
        'Raw payload stored in SITA_INCOMING_LOG for manual review.',
        '',
        '=== Raw payload ===',
        text,
    ]


class MessageExtractor:
    def __init__(self, root):
        self.root = root
        root.title('AMG Message Field Extractor')
        root.geometry('950x750')
        root.minsize(750, 550)

        notebook = ttk.Notebook(root)
        notebook.pack(fill='both', expand=True, padx=8, pady=8)

        self.ldm_tab = ExtractorTab(notebook, 'Paste raw LDM message (AHM 583)',
                                    _extract_ldm)
        notebook.add(self.ldm_tab.frame, text='LDM')

        self.mvt_tab = ExtractorTab(notebook, 'Paste raw MVT / MVA message (AHM 780)',
                                    _extract_mvt)
        notebook.add(self.mvt_tab.frame, text='MVT / MVA')

        self.fwd_tab = ExtractorTab(notebook, 'Paste raw FWD message (SY311)',
                                    _extract_fwd)
        notebook.add(self.fwd_tab.frame, text='FWD')

        self.div_tab = ExtractorTab(notebook, 'Paste raw DIV message (AHM 781)',
                                    _extract_div)
        notebook.add(self.div_tab.frame, text='DIV')

        self.ptm_tab = ExtractorTab(notebook, 'Paste raw PTM message (RP 1718)',
                                    _extract_ptm)
        notebook.add(self.ptm_tab.frame, text='PTM')

        self.assist_tab = ExtractorTab(notebook,
                                       'Paste raw PSM / PAL / CAL message (RP 1715 / 1708a)',
                                       _extract_assist)
        notebook.add(self.assist_tab.frame, text='PSM / PAL / CAL')

        self.asm_tab = ExtractorTab(notebook, 'Paste raw ASM message (IATA SSM)',
                                    _extract_asm)
        notebook.add(self.asm_tab.frame, text='ASM')

        self.status_var = tk.StringVar(value='Paste a message and click Extract.')
        ttk.Label(root, textvariable=self.status_var, padding=8).pack(fill='x')


def main(argv=None):
    root = tk.Tk()
    MessageExtractor(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
