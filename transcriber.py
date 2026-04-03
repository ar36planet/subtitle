# -*- coding: utf-8 -*-
"""
本地語音辨識字幕工具 (Apple Silicon)
依賴: mlx-whisper, pysubs2, transformers, sentencepiece
      ffmpeg (brew install ffmpeg)
"""

import re
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import os
import subprocess

AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'}
VIDEO_EXT = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}

LANGUAGES = {
    '自動判斷':      None,
    '中文 (zh)':     'zh',
    '英語 (en)':     'en',
    '日語 (ja)':     'ja',
    '韓語 (ko)':     'ko',
    '法語 (fr)':     'fr',
    '德語 (de)':     'de',
    '西班牙語 (es)': 'es',
}

WHISPER_MODELS = {
    'large-v3 (最準確)': 'mlx-community/whisper-large-v3-mlx',
    'turbo (快+準)':     'mlx-community/whisper-large-v3-turbo',
    'large-v2':          'mlx-community/whisper-large-v2-mlx',
    'medium':            'mlx-community/whisper-medium-mlx',
    'small (快)':        'mlx-community/whisper-small-mlx',
    'base (最快)':       'mlx-community/whisper-base-mlx',
}

TRANS_MODELS = {
    '中→英 (Helsinki)':   {'type': 'helsinki', 'model': 'Helsinki-NLP/opus-mt-zh-en'},
    '英→中 (Helsinki)':   {'type': 'helsinki', 'model': 'Helsinki-NLP/opus-mt-en-zh'},
    '日→英 (Helsinki)':   {'type': 'helsinki', 'model': 'Helsinki-NLP/opus-mt-ja-en'},
    '中→英 (qwen2.5:7b)': {'type': 'ollama',   'model': 'qwen2.5:7b'},
    '中→英 (gemma4)':     {'type': 'ollama',   'model': 'gemma4:e4b'},
}

OUTPUT_FORMATS = ['srt', 'txt']


def ms_to_ts(ms):
    s, ms = divmod(ms, 1000)
    m, s  = divmod(s, 60)
    h, m  = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('語音辨識字幕工具')
        self.geometry('820x620')
        self._is_running    = False
        self._translator    = None
        self._last_model_id = ''
        self._trans_rows    = []   # list of (SSAEvent, tk.StringVar)
        self._srt_data      = None
        self._build_ui()

    # ── 主框架 ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=8, pady=8)

        t1 = tk.Frame(nb)
        nb.add(t1, text='  語音辨識  ')
        self._build_transcribe_tab(t1)

        t2 = tk.Frame(nb)
        nb.add(t2, text='  字幕翻譯  ')
        self._build_translate_tab(t2)

    # ── Tab 1：辨識 ───────────────────────────────────────────────────────────

    def _build_transcribe_tab(self, p):
        pad = dict(padx=12, pady=4)

        r0 = tk.Frame(p); r0.pack(fill='x', **pad)
        tk.Label(r0, text='輸入檔案:', width=10, anchor='w').pack(side='left')
        self.input_var = tk.StringVar()
        tk.Entry(r0, textvariable=self.input_var, width=54).pack(side='left', padx=4)
        tk.Button(r0, text='瀏覽', command=self._browse_input).pack(side='left')

        r1 = tk.Frame(p); r1.pack(fill='x', **pad)
        tk.Label(r1, text='輸出目錄:', width=10, anchor='w').pack(side='left')
        self.output_var = tk.StringVar()
        tk.Entry(r1, textvariable=self.output_var, width=54).pack(side='left', padx=4)
        tk.Button(r1, text='瀏覽', command=self._browse_output).pack(side='left')

        r2 = tk.Frame(p); r2.pack(fill='x', **pad)
        tk.Label(r2, text='語言:').pack(side='left')
        self.lang_var = tk.StringVar(value='中文 (zh)')
        ttk.Combobox(r2, textvariable=self.lang_var, values=list(LANGUAGES.keys()),
                     width=14, state='readonly').pack(side='left', padx=4)
        tk.Label(r2, text='模型:').pack(side='left', padx=(10, 0))
        self.model_var = tk.StringVar(value='large-v3 (最準確)')
        ttk.Combobox(r2, textvariable=self.model_var, values=list(WHISPER_MODELS.keys()),
                     width=20, state='readonly').pack(side='left', padx=4)
        tk.Label(r2, text='格式:').pack(side='left')
        self.fmt_var = tk.StringVar(value='srt')
        ttk.Combobox(r2, textvariable=self.fmt_var, values=OUTPUT_FORMATS,
                     width=5, state='readonly').pack(side='left', padx=4)

        r3 = tk.Frame(p); r3.pack(fill='x', **pad)
        tk.Label(r3, text='提示語:', width=10, anchor='w').pack(side='left')
        self.prompt_var = tk.StringVar(value='')
        tk.Entry(r3, textvariable=self.prompt_var, width=54).pack(side='left', padx=4)

        self.progress = ttk.Progressbar(p, mode='indeterminate')
        self.progress.pack(fill='x', padx=12, pady=2)

        self.log = scrolledtext.ScrolledText(
            p, height=14, width=74, state='disabled',
            font=('Menlo', 11), bg='#1e1e1e', fg='#d4d4d4'
        )
        self.log.pack(padx=12, pady=6, fill='both', expand=True)

        self.start_btn = tk.Button(
            p, text='開始辨識', command=self._start,
            bg='#007AFF', fg='white', font=('', 13, 'bold'),
            padx=24, pady=8, relief='flat', cursor='hand2'
        )
        self.start_btn.pack(pady=10)

    # ── Tab 2：翻譯 ───────────────────────────────────────────────────────────

    def _build_translate_tab(self, p):
        # 工具列
        bar = tk.Frame(p); bar.pack(fill='x', padx=8, pady=6)
        tk.Button(bar, text='匯入 SRT', command=self._import_srt,
                  padx=10, pady=4).pack(side='left', padx=4)
        self.trans_model_var = tk.StringVar(value='中→英 (gemma4)')
        ttk.Combobox(bar, textvariable=self.trans_model_var,
                     values=list(TRANS_MODELS.keys()), width=10,
                     state='readonly').pack(side='left', padx=4)
        self.trans_btn = tk.Button(bar, text='翻譯全部', command=self._translate_all,
                                   padx=10, pady=4, state='disabled')
        self.trans_btn.pack(side='left', padx=4)
        tk.Button(bar, text='匯出 SRT', command=self._export_srt,
                  padx=10, pady=4).pack(side='right', padx=4)

        # 狀態列
        self.trans_status = tk.StringVar(value='請匯入 SRT 檔案')
        tk.Label(p, textvariable=self.trans_status, anchor='w',
                 fg='#666').pack(fill='x', padx=12)

        # 表頭
        hdr = tk.Frame(p, bg='#c8c8c8')
        hdr.pack(fill='x', padx=8, pady=(4, 0))
        hdr.columnconfigure(1, weight=1)
        hdr.columnconfigure(2, weight=2)
        tk.Label(hdr, text='時間', anchor='w', bg='#c8c8c8',
                 font=('', 10, 'bold'), width=16).grid(row=0, column=0, padx=4, pady=3, sticky='w')
        tk.Label(hdr, text='原文', anchor='w', bg='#c8c8c8',
                 font=('', 10, 'bold')).grid(row=0, column=1, padx=4, sticky='ew')
        tk.Label(hdr, text='翻譯（可編輯）', anchor='w', bg='#c8c8c8',
                 font=('', 10, 'bold')).grid(row=0, column=2, padx=4, sticky='ew')

        # 捲動表格
        wrap = tk.Frame(p); wrap.pack(fill='both', expand=True, padx=8, pady=4)
        self._canvas = tk.Canvas(wrap, bg='white', highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg='white')
        self._inner.bind('<Configure>',
                         lambda e: self._canvas.configure(
                             scrollregion=self._canvas.bbox('all')))
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor='nw')
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.bind('<Configure>',
                          lambda e: self._canvas.itemconfig(self._win_id, width=e.width))
        vsb.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)
        self._canvas.bind('<MouseWheel>',
                          lambda e: self._canvas.yview_scroll(
                              -1 * (e.delta // 120), 'units'))

    # ── 辨識邏輯 ──────────────────────────────────────────────────────────────

    def _browse_input(self):
        exts = ' '.join('*' + e for e in AUDIO_EXT | VIDEO_EXT)
        path = filedialog.askopenfilename(
            title='選擇音訊或影片檔案',
            filetypes=[('音訊/影片', exts), ('所有檔案', '*.*')])
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(os.path.dirname(path))

    def _browse_output(self):
        path = filedialog.askdirectory(title='選擇輸出目錄')
        if path:
            self.output_var.set(path)

    def _log(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', msg + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def _start(self):
        if self._is_running:
            return
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp:
            messagebox.showwarning('提示', '請選擇輸入檔案'); return
        if not os.path.exists(inp):
            messagebox.showerror('錯誤', f'找不到檔案：\n{inp}'); return
        if not out:
            messagebox.showwarning('提示', '請選擇輸出目錄'); return
        os.makedirs(out, exist_ok=True)
        self._is_running = True
        self.start_btn.configure(state='disabled', text='辨識中...')
        self.progress.start(10)
        threading.Thread(target=self._run, args=(inp, out), daemon=True).start()

    def _run(self, input_path, output_dir):
        try:
            import mlx_whisper, pysubs2
        except ImportError as e:
            self.after(0, lambda: messagebox.showerror(
                '缺少套件', f'{e}\n\npip install mlx-whisper pysubs2'))
            self._finish(); return

        lang   = LANGUAGES[self.lang_var.get()]
        model  = WHISPER_MODELS[self.model_var.get()]
        fmt    = self.fmt_var.get()
        prompt = self.prompt_var.get().strip() or None

        # ffmpeg 預處理
        self.after(0, lambda: self._log('>> 預處理音訊...'))
        temp_wav = os.path.join(output_dir, '_temp_audio.wav')
        args = ['ffmpeg', '-y', '-i', input_path, '-ar', '16000', '-ac', '1']
        if os.path.splitext(input_path)[1].lower() in VIDEO_EXT:
            args += ['-vn']
        args.append(temp_wav)
        ret = subprocess.run(args, capture_output=True)
        if ret.returncode != 0:
            self.after(0, lambda: self._log('ERROR: ffmpeg 失敗'))
            self.after(0, lambda: messagebox.showerror(
                '錯誤', 'ffmpeg 失敗，請確認：brew install ffmpeg'))
            self._finish(); return
        self.after(0, lambda: self._log('>> 預處理完成'))

        self.after(0, lambda: self._log(f'>> 模型：{model}'))
        self.after(0, lambda: self._log('>> 辨識中...(首次會下載模型)'))
        try:
            result = mlx_whisper.transcribe(
                temp_wav, path_or_hf_repo=model,
                language=lang, initial_prompt=prompt, verbose=False)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._log(f'ERROR: {err}'))
            self._finish(temp_wav); return

        base = os.path.splitext(os.path.basename(input_path))[0]
        out  = os.path.join(output_dir, base + '.' + fmt)
        if fmt == 'txt':
            with open(out, 'w', encoding='utf-8') as f:
                for s in result['segments']:
                    f.write(s['text'].strip() + '\n')
        else:
            subs = pysubs2.load_from_whisper([
                {'start': s['start'], 'end': s['end'], 'text': s['text']}
                for s in result['segments']
            ])
            subs.save(out)

        self.after(0, lambda: self._log(f'\n>> 完成！\n   {out}'))
        self._finish(temp_wav)

    def _finish(self, temp_wav=None):
        if temp_wav and os.path.exists(temp_wav):
            os.remove(temp_wav)
        self._is_running = False
        self.after(0, self.progress.stop)
        self.after(0, lambda: self.start_btn.configure(state='normal', text='開始辨識'))

    # ── 翻譯邏輯 ──────────────────────────────────────────────────────────────

    def _import_srt(self):
        path = filedialog.askopenfilename(
            title='選擇 SRT 字幕檔',
            filetypes=[('SRT 字幕', '*.srt'), ('所有檔案', '*.*')])
        if not path:
            return
        try:
            import pysubs2
            self._srt_data = pysubs2.load(path, encoding='utf-8')
        except Exception as e:
            messagebox.showerror('錯誤', f'無法讀取 SRT：{e}'); return

        self._populate_table(self._srt_data)
        self.trans_btn.configure(state='normal')
        self.trans_status.set(
            f'已載入 {len(self._srt_data)} 句  ←  {os.path.basename(path)}')

    def _populate_table(self, subs):
        for w in self._inner.winfo_children():
            w.destroy()
        self._trans_rows = []

        self._inner.columnconfigure(0, minsize=130)
        self._inner.columnconfigure(1, weight=1)
        self._inner.columnconfigure(2, weight=2)

        for i, line in enumerate(subs):
            bg = '#ffffff' if i % 2 == 0 else '#f5f5f5'

            ts = f"{ms_to_ts(line.start)} → {ms_to_ts(line.end)}"
            tk.Label(self._inner, text=ts, anchor='w', bg=bg,
                     font=('Menlo', 9), fg='#888').grid(
                         row=i, column=0, padx=6, pady=3, sticky='nsew')

            orig = tk.Label(self._inner, text=line.text, anchor='nw',
                            bg=bg, justify='left')
            orig.grid(row=i, column=1, padx=4, pady=3, sticky='nsew')
            orig.bind('<Configure>',
                      lambda e, l=orig: l.configure(wraplength=max(e.width - 8, 1)))

            var = tk.StringVar()
            entry = tk.Entry(self._inner, textvariable=var, relief='flat',
                             bg=bg, fg='#1a6bb5', insertbackground='#1a6bb5')
            entry.grid(row=i, column=2, padx=4, pady=2, sticky='ew')

            self._trans_rows.append((line, var))

    def _translate_all(self):
        if not self._trans_rows:
            return
        self.trans_btn.configure(state='disabled', text='翻譯中...')
        threading.Thread(target=self._do_translate, daemon=True).start()

    def _do_translate(self):
        cfg   = TRANS_MODELS[self.trans_model_var.get()]
        total = len(self._trans_rows)

        if cfg['type'] == 'ollama':
            self._do_translate_ollama(cfg['model'], total)
        else:
            self._do_translate_helsinki(cfg['model'], total)

    def _do_translate_ollama(self, model_id, total):
        try:
            import ollama
        except ImportError:
            self.after(0, lambda: messagebox.showerror(
                '缺少套件', 'pip install ollama'))
            self.after(0, lambda: self.trans_btn.configure(
                state='normal', text='翻譯全部'))
            return

        SYSTEM = ('You are a subtitle translator. '
                  'Translate Chinese subtitles to natural, conversational English. '
                  'Preserve the meaning across lines even if a sentence is split. '
                  'Output only the numbered translations, one per line, '
                  'in the format "N: translation". No extra text.')

        BATCH = 50  # 每批送幾句

        translated = [''] * total

        for start in range(0, total, BATCH):
            end   = min(start + BATCH, total)
            chunk = self._trans_rows[start:end]

            numbered = '\n'.join(
                f"{start + j + 1}: {line.text.strip()}"
                for j, (line, _) in enumerate(chunk)
            )

            self.after(0, lambda s=start, e=end:
                       self.trans_status.set(f'翻譯中... {s+1}–{e}/{total}'))
            try:
                resp = ollama.chat(model=model_id, messages=[
                    {'role': 'system', 'content': SYSTEM},
                    {'role': 'user',   'content': numbered}
                ])
                raw = resp['message']['content'].strip()
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror('錯誤', f'Ollama 失敗：{err}'))
                self.after(0, lambda: self.trans_btn.configure(
                    state='normal', text='翻譯全部'))
                return

            # 解析 "N: 翻譯文字"
            for line_str in raw.splitlines():
                m = re.match(r'^(\d+)\s*[:：]\s*(.+)', line_str.strip())
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < total:
                        translated[idx] = m.group(2).strip()

            # 即時填入已完成的那批
            for j, (_, var) in enumerate(chunk):
                t = translated[start + j]
                if t:
                    self.after(0, lambda v=var, txt=t: v.set(txt))

        self.after(0, lambda: self.trans_status.set(
            f'完成（{model_id}），共 {total} 句，請確認後點「匯出 SRT」'))
        self.after(0, lambda: self.trans_btn.configure(state='normal', text='翻譯全部'))

    def _do_translate_helsinki(self, model_id, total):
        try:
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError:
            self.after(0, lambda: messagebox.showerror(
                '缺少套件', 'pip install transformers sentencepiece'))
            self.after(0, lambda: self.trans_btn.configure(
                state='normal', text='翻譯全部'))
            return

        self.after(0, lambda: self.trans_status.set('載入翻譯模型...'))
        try:
            if self._last_model_id != model_id:
                tokenizer        = MarianTokenizer.from_pretrained(model_id)
                model            = MarianMTModel.from_pretrained(model_id)
                self._translator = (tokenizer, model)
                self._last_model_id = model_id
            tokenizer, model = self._translator
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror('錯誤', f'無法載入模型：{err}'))
            self.after(0, lambda: self.trans_btn.configure(
                state='normal', text='翻譯全部'))
            return

        texts = [line.text.strip() for line, _ in self._trans_rows]
        self.after(0, lambda: self.trans_status.set('翻譯中...'))
        try:
            batch_size = 16
            translated = []
            for i in range(0, total, batch_size):
                batch   = texts[i:i + batch_size]
                inputs  = tokenizer(batch, return_tensors='pt',
                                    padding=True, truncation=True, max_length=512)
                outputs = model.generate(**inputs)
                translated += [tokenizer.decode(t, skip_special_tokens=True)
                               for t in outputs]
                self.after(0, lambda n=min(i+batch_size, total):
                           self.trans_status.set(f'翻譯中... {n}/{total}'))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror('錯誤', f'翻譯失敗：{err}'))
            self.after(0, lambda: self.trans_btn.configure(
                state='normal', text='翻譯全部'))
            return

        for (_, var), t in zip(self._trans_rows, translated):
            self.after(0, lambda v=var, txt=t: v.set(txt))

        self.after(0, lambda: self.trans_status.set(
            f'完成，共 {total} 句，請確認後點「匯出 SRT」'))
        self.after(0, lambda: self.trans_btn.configure(state='normal', text='翻譯全部'))

    def _export_srt(self):
        if not self._trans_rows:
            messagebox.showwarning('提示', '尚未有翻譯內容'); return

        path = filedialog.asksaveasfilename(
            defaultextension='.srt',
            filetypes=[('SRT 字幕', '*.srt')],
            title='儲存翻譯字幕')
        if not path:
            return

        try:
            import pysubs2
            subs = pysubs2.SSAFile()
            for line, var in self._trans_rows:
                txt = var.get().strip()
                if txt:
                    subs.append(pysubs2.SSAEvent(
                        start=line.start, end=line.end, text=txt))
            subs.save(path, encoding='utf-8')
            messagebox.showinfo('完成', f'已儲存至：\n{path}')
        except Exception as e:
            messagebox.showerror('錯誤', f'匯出失敗：{e}')


if __name__ == '__main__':
    app = App()
    app.mainloop()
