import difflib
import json
import os
import queue
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


APP_TITLE = "CodeRouter"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CONFIG_PATH = Path(__file__).with_name("local_config.json")
EXTERNAL_CONTEXT_PREFIX = "__external_context__"

MODEL_FALLBACKS = [
    "qwen/qwen3-coder:free",
    "deepseek/deepseek-chat-v3.1:free",
    "z-ai/glm-4.5-air:free",
    "moonshotai/kimi-k2:free",
    "openrouter/free",
]

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    ".gradle",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "env",
}

DEFAULT_IGNORE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".pyc",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".sqlite",
    ".db",
}

DEFAULT_IGNORE_FILE_NAMES = {
    ".env",
    "local_config.json",
}

DEFAULT_IGNORE_SECRET_EXTENSIONS = {
    ".key",
    ".pem",
}


@dataclass
class SourceFile:
    path: Path
    relative_path: str
    content: str


class CodeAgentApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1380x860")
        self.minsize(1060, 680)
        self.configure(bg="#edf0f6")

        self.config_data = load_local_config()
        self.api_key = os.environ.get("OPENROUTER_API_KEY") or self.config_data.get("openrouter_api_key", "")
        self.selected_folder = tk.StringVar(value=self.config_data.get("last_folder", ""))
        self.extra_context_paths = list(self.config_data.get("extra_context_files", []))
        self.status = tk.StringVar(value="Ready")
        self.file_count = tk.StringVar(value="0 files")
        self.extra_context_count = tk.StringVar(value=self._extra_context_label())
        self.char_count = tk.StringVar(value="0 chars")
        self.pending_count = tk.StringVar(value="0 pending")
        self.model_status = tk.StringVar(value="Auto free fallback")
        self.auto_apply = tk.BooleanVar(value=True)

        self.work_queue = queue.Queue()
        self.pending_edits = []
        self.diff_by_path = {}
        self.session_messages = []
        self.last_summary = ""
        self.pulse_step = 0
        self.animated_buttons = []

        self._build_styles()
        self._build_ui()
        self._animate_status()
        self.after(100, self._poll_queue)
        if self.selected_folder.get():
            self.scan_folder(silent=True)

    def _build_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#edf0f6")
        style.configure("Shell.TFrame", background="#edf0f6")
        style.configure("Sidebar.TFrame", background="#e8ebf2")
        style.configure("Panel.TFrame", background="#fbfbfd", relief="flat")
        style.configure("Glow.TFrame", background="#dff7e7")
        style.configure("Title.TLabel", background="#edf0f6", foreground="#17171a", font=("Segoe UI", 20, "bold"))
        style.configure("Muted.TLabel", background="#edf0f6", foreground="#686a70", font=("Segoe UI", 9))
        style.configure("SideTitle.TLabel", background="#e8ebf2", foreground="#202124", font=("Segoe UI", 9, "bold"))
        style.configure("Side.TLabel", background="#e8ebf2", foreground="#54575f", font=("Segoe UI", 9))
        style.configure("PanelTitle.TLabel", background="#fbfbfd", foreground="#202124", font=("Segoe UI", 12, "bold"))
        style.configure("PanelMuted.TLabel", background="#fbfbfd", foreground="#71747c", font=("Segoe UI", 9))
        style.configure("Stat.TLabel", background="#fbfbfd", foreground="#202124", font=("Segoe UI", 12, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 12, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#dff7e7")])
        style.configure("Ghost.TButton", padding=(13, 9), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#f7f8fb")])
        style.configure("Icon.TButton", font=("Segoe UI", 10, "bold"), padding=(4, 5), borderwidth=0)
        style.map("Icon.TButton", background=[("active", "#eef6f0")])
        style.configure("Danger.TButton", padding=(12, 8))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9), background="#fbfbfd", fieldbackground="#fbfbfd")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, style="App.TFrame", padding=(18, 14, 18, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        self.status_pulse = tk.Canvas(toolbar, width=15, height=15, bg="#edf0f6", highlightthickness=0)
        self.status_pulse.grid(row=0, column=0, padx=(0, 10))
        ttk.Label(toolbar, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(toolbar, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=2, sticky="e")

        shell = ttk.Frame(self, style="Shell.TFrame", padding=(16, 0, 16, 16))
        shell.grid(row=1, column=0, sticky="nsew")
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        sidebar = self._soft_panel(shell, "#e8ebf2", "#d3dbea")
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        sidebar.columnconfigure(0, weight=1)

        ttk.Label(sidebar, text="Project", style="SideTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(4, 0))
        self._button(sidebar, "Open project folder", self.choose_folder, "Ghost.TButton", "Choose the folder the agent can edit").grid(row=1, column=0, sticky="ew", pady=(9, 7))
        ttk.Label(sidebar, textvariable=self.selected_folder, style="Side.TLabel", wraplength=235).grid(row=2, column=0, sticky="ew", pady=(0, 9))
        self._button(sidebar, "Add context files", self.add_context_files, "Ghost.TButton", "Add extra files from another folder as read-only model context").grid(row=3, column=0, sticky="ew", pady=(0, 7))
        self._button(sidebar, "Clear context files", self.clear_context_files, "Ghost.TButton", "Remove extra read-only context files").grid(row=4, column=0, sticky="ew", pady=(0, 7))
        ttk.Label(sidebar, textvariable=self.extra_context_count, style="Side.TLabel", wraplength=235).grid(row=5, column=0, sticky="ew", pady=(0, 16))

        ttk.Label(sidebar, text="Main actions", style="SideTitle.TLabel").grid(row=6, column=0, sticky="w")
        actions = self._card(sidebar, "#fbfbfd", "#cfd7e6")
        actions.grid(row=7, column=0, sticky="ew", pady=(9, 16))
        actions.columnconfigure(0, weight=1)
        self._button(actions, "Run / continue chat", self.run_agent, "Accent.TButton", "Send the prompt and continue this session").grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.apply_button = self._button(actions, "Accept changes", self.apply_pending, "Accent.TButton", "Apply pending edits to disk")
        self.apply_button.configure(state=tk.DISABLED)
        self.apply_button.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        self.reject_button = self._button(actions, "Reject changes", self.reject_pending, "Ghost.TButton", "Discard pending edits")
        self.reject_button.configure(state=tk.DISABLED)
        self.reject_button.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        self._button(actions, "Start new chat", self.reset_session, "Ghost.TButton", "Clear conversation memory").grid(row=3, column=0, sticky="ew")

        ttk.Label(sidebar, text="Snapshot", style="SideTitle.TLabel").grid(row=8, column=0, sticky="w")
        stats = self._card(sidebar, "#fbfbfd", "#cfd7e6")
        stats.grid(row=9, column=0, sticky="ew", pady=(9, 16))
        stats.columnconfigure(0, weight=1)
        ttk.Label(stats, textvariable=self.file_count, style="Stat.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.char_count, background="#fbfbfd", foreground="#71747c").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(stats, textvariable=self.pending_count, background="#fbfbfd", foreground="#146b31").grid(row=2, column=0, sticky="w", pady=(9, 0))

        ttk.Label(sidebar, text="Quick buttons", style="SideTitle.TLabel").grid(row=10, column=0, sticky="w")
        quick = self._card(sidebar, "#fbfbfd", "#d9deea")
        quick.grid(row=11, column=0, sticky="ew", pady=(9, 0))
        for col in range(5):
            quick.columnconfigure(col, weight=1, uniform="quick", minsize=46)
        self._icon_button(quick, "↻", self.scan_folder, "Rescan project files").grid(row=0, column=0, padx=(0, 4))
        self._icon_button(quick, "▶", self.run_agent, "Run agent").grid(row=0, column=1, padx=4)
        self._icon_button(quick, "+", self.reset_session, "New chat").grid(row=0, column=2, padx=4)
        self._icon_button(quick, "✓", self.apply_pending, "Accept changes").grid(row=0, column=3, padx=4)
        self._icon_button(quick, "×", self.reject_pending, "Reject changes").grid(row=0, column=4, padx=(4, 0))

        main = ttk.PanedWindow(shell, orient=tk.HORIZONTAL)
        main.grid(row=0, column=1, sticky="nsew")

        center = self._card(main, "#fbfbfd", "#d9deea", padding=14)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=3)
        center.rowconfigure(3, weight=1)
        center.rowconfigure(5, weight=1)
        ttk.Label(center, text="Prompt", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.instructions = scrolledtext.ScrolledText(center, height=7, wrap=tk.WORD, relief="flat", font=("Consolas", 10), bg="#f4f6fa", fg="#202124", insertbackground="#202124")
        self.instructions.grid(row=1, column=0, sticky="nsew", pady=(8, 12))
        self.instructions.insert("1.0", "Ask for the next change. This chat keeps context until New Chat.")

        ttk.Label(center, text="Now", style="PanelTitle.TLabel").grid(row=2, column=0, sticky="w")
        self.summary = scrolledtext.ScrolledText(center, height=6, wrap=tk.WORD, relief="flat", font=("Segoe UI", 10), bg="#f7fbf8", fg="#1f3d2a")
        self.summary.grid(row=3, column=0, sticky="nsew", pady=(8, 12))
        self.summary.insert("1.0", "No active change yet.")
        self.summary.configure(state=tk.DISABLED)

        ttk.Label(center, text="Log", style="PanelTitle.TLabel").grid(row=4, column=0, sticky="w")
        self.activity = scrolledtext.ScrolledText(center, height=8, wrap=tk.WORD, relief="flat", font=("Consolas", 10), bg="#121316", fg="#eef0f4", insertbackground="#eef0f4")
        self.activity.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        main.add(center, weight=5)

        right = self._card(main, "#fbfbfd", "#d9deea", padding=14)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text="Files", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        diff_pane = ttk.PanedWindow(right, orient=tk.VERTICAL)
        diff_pane.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        list_panel = ttk.Frame(diff_pane, style="Panel.TFrame")
        list_panel.columnconfigure(0, weight=1)
        list_panel.rowconfigure(0, weight=1)
        self.edited_files = ttk.Treeview(list_panel, columns=("status", "lines"), show="headings", selectmode="browse")
        self.edited_files.heading("status", text="")
        self.edited_files.heading("lines", text="+/-")
        self.edited_files.column("status", width=360, anchor="w")
        self.edited_files.column("lines", width=70, anchor="e")
        self.edited_files.grid(row=0, column=0, sticky="nsew")
        self.edited_files.bind("<<TreeviewSelect>>", self.on_file_selected)
        diff_pane.add(list_panel, weight=1)

        diff_panel = ttk.Frame(diff_pane, style="Panel.TFrame")
        diff_panel.columnconfigure(0, weight=1)
        diff_panel.rowconfigure(0, weight=1)
        self.diff = scrolledtext.ScrolledText(diff_panel, wrap=tk.NONE, relief="flat", font=("Consolas", 10), bg="#f7f8fb", fg="#202124")
        self.diff.grid(row=0, column=0, sticky="nsew")
        self.diff.tag_configure("add", foreground="#087b2f", background="#e5f7eb")
        self.diff.tag_configure("del", foreground="#bd1e24", background="#fde8e8")
        self.diff.tag_configure("file", foreground="#0b5dd7", font=("Consolas", 10, "bold"))
        self.diff.tag_configure("meta", foreground="#72757d")
        diff_pane.add(diff_panel, weight=2)
        main.add(right, weight=6)

        self.log("CodeRouter started. API key is hidden and loaded from local config or environment.")

    def _soft_panel(self, parent, bg, border):
        frame = tk.Frame(parent, bg=bg, padx=16, pady=16, highlightthickness=1, highlightbackground=border)
        return frame

    def _card(self, parent, bg, border, padding=12):
        frame = tk.Frame(parent, bg=bg, padx=padding + 2, pady=padding + 2, highlightthickness=1, highlightbackground=border)
        return frame

    def _button(self, parent, text, command, style_name, hint=None):
        button = ttk.Button(parent, text=text, command=command, style=style_name)
        button.bind("<Enter>", lambda _event, b=button, h=hint: self._button_hover(b, True, h))
        button.bind("<Leave>", lambda _event, b=button: self._button_hover(b, False, None))
        self.animated_buttons.append(button)
        return button

    def _icon_button(self, parent, text, command, hint):
        button = self._button(parent, text, command, "Icon.TButton", hint)
        button.configure(width=4)
        return button

    def _button_hover(self, button, active, hint=None):
        if str(button.cget("state")) == tk.DISABLED:
            return
        button.configure(cursor="hand2" if active else "")
        if hint:
            self.status.set(hint)

    def _animate_status(self):
        colors = ["#28c840", "#31d158", "#63e07b", "#31d158"]
        color = colors[self.pulse_step % len(colors)]
        self.status_pulse.delete("all")
        self.status_pulse.create_oval(1, 1, 14, 14, fill="#d9f9e2", outline="#d9f9e2")
        self.status_pulse.create_oval(4, 4, 11, 11, fill=color, outline=color)
        self.pulse_step += 1
        self.after(520, self._animate_status)

    def _window_dot(self, parent, color):
        canvas = tk.Canvas(parent, width=13, height=13, bg="#eef0f4", highlightthickness=0)
        canvas.create_oval(2, 2, 12, 12, fill=color, outline=color)
        return canvas

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Choose project folder")
        if folder:
            self.selected_folder.set(folder)
            self.config_data["last_folder"] = folder
            save_local_config(self.config_data)
            self.scan_folder()

    def add_context_files(self):
        paths = filedialog.askopenfilenames(title="Add read-only context files")
        if not paths:
            return
        existing = set(self.extra_context_paths)
        added = 0
        skipped = 0
        for path_text in paths:
            path = Path(path_text)
            if is_context_file_allowed(path) and str(path) not in existing:
                self.extra_context_paths.append(str(path))
                existing.add(str(path))
                added += 1
            else:
                skipped += 1
        self.config_data["extra_context_files"] = self.extra_context_paths
        save_local_config(self.config_data)
        self.extra_context_count.set(self._extra_context_label())
        self.scan_folder(silent=True)
        self.log(f"> added {added} context files" + (f", skipped {skipped}" if skipped else ""))

    def clear_context_files(self):
        if not self.extra_context_paths:
            return
        count = len(self.extra_context_paths)
        self.extra_context_paths = []
        self.config_data["extra_context_files"] = []
        save_local_config(self.config_data)
        self.extra_context_count.set(self._extra_context_label())
        self.scan_folder(silent=True)
        self.log(f"> cleared {count} context files")

    def _extra_context_label(self):
        count = len(self.extra_context_paths)
        if count == 1:
            return "1 extra context file"
        return f"{count} extra context files"

    def log(self, text):
        self.activity.insert(tk.END, text + "\n")
        self.activity.see(tk.END)

    def set_summary(self, text):
        self.summary.configure(state=tk.NORMAL)
        self.summary.delete("1.0", tk.END)
        self.summary.insert("1.0", text.strip() or "No summary returned.")
        self.summary.configure(state=tk.DISABLED)
        self._flash_summary(0)

    def _flash_summary(self, step):
        colors = ["#e9faef", "#edf9f1", "#f2faf5", "#f7fbf8"]
        if step >= len(colors):
            return
        self.summary.configure(bg=colors[step])
        self.after(130, lambda: self._flash_summary(step + 1))

    def reset_session(self):
        self.session_messages = []
        self.last_summary = ""
        self.pending_edits = []
        self.diff_by_path = {}
        self.pending_count.set("0 pending")
        self.apply_button.configure(state=tk.DISABLED)
        self.reject_button.configure(state=tk.DISABLED)
        self.clear_changed_files()
        self.write_diff("")
        self.set_summary("New chat started. Previous model context cleared.")
        self.log("> session reset")

    def scan_folder(self, silent=False):
        folder = self._validate_folder(show_error=not silent)
        if not folder:
            return
        try:
            max_files, max_file_kb = choose_context_limits(folder)
            files = collect_files(folder, max_files=max_files, max_file_kb=max_file_kb)
            files.extend(collect_extra_context_files(self.extra_context_paths, max_file_kb=max_file_kb))
        except Exception as exc:
            if not silent:
                messagebox.showerror(APP_TITLE, str(exc))
            return
        total_chars = sum(len(item.content) for item in files)
        self.file_count.set(f"{len(files)} files")
        self.char_count.set(f"{total_chars:,} chars")
        self.status.set("Snapshot ready")
        if not silent:
            self.log(f"> scanned {len(files)} files, {total_chars:,} chars")

    def run_agent(self):
        folder = self._validate_folder()
        if not folder:
            return
        if not self.api_key:
            messagebox.showerror(APP_TITLE, "OpenRouter API key is missing from local_config.json or OPENROUTER_API_KEY.")
            return
        instructions = self.instructions.get("1.0", tk.END).strip()
        if not instructions:
            messagebox.showerror(APP_TITLE, "Write an instruction first.")
            return

        self.pending_edits = []
        self.diff_by_path = {}
        self.apply_button.configure(state=tk.DISABLED)
        self.reject_button.configure(state=tk.DISABLED)
        self.pending_count.set("0 pending")
        self.clear_changed_files()
        self.write_diff("")
        self.set_summary("Reading project, preparing context, and asking the free coding model.")
        self.status.set("Running agent...")
        self.log("")
        self.log("> user: " + one_line(instructions))

        worker = threading.Thread(target=self._run_agent_worker, args=(folder, instructions), daemon=True)
        worker.start()

    def _run_agent_worker(self, folder, instructions):
        try:
            max_files, max_file_kb = choose_context_limits(folder)
            files = collect_files(folder, max_files=max_files, max_file_kb=max_file_kb)
            files.extend(collect_extra_context_files(self.extra_context_paths, max_file_kb=max_file_kb))
            self.work_queue.put(("log", f"> context: {len(files)} files, max {max_file_kb} KB/file"))
            self.work_queue.put(("summary", "Snapshot collected. Trying free coding models in fallback order."))
            result, model_used = call_openrouter_with_fallback(
                api_key=self.api_key,
                instructions=instructions,
                files=files,
                session_messages=self.session_messages,
                log_queue=self.work_queue,
            )
            edits = result["files"]
            summary = result["summary"] or f"Prepared {len(edits)} file changes."
            self.session_messages.append({"role": "user", "content": instructions})
            self.session_messages.append({"role": "assistant", "content": summary})
            self.last_summary = summary
            self.work_queue.put(("model_status", f"Used {model_used}"))
            self.work_queue.put(("summary", summary))

            if not edits:
                self.work_queue.put(("log", "> no file changes returned"))
                self.work_queue.put(("status", "No changes"))
                return

            diff_by_path = render_diff_by_path(folder, edits)
            file_rows = build_file_rows(diff_by_path)
            self.work_queue.put(("pending", edits))
            self.work_queue.put(("diffs", diff_by_path))
            self.work_queue.put(("files", file_rows))
            self.work_queue.put(("log", f"> prepared {len(edits)} changed files"))

            if self.auto_apply.get():
                changed = apply_edits(folder, edits)
                self.session_messages.append({"role": "system", "content": f"User accepted and applied {changed} files."})
                self.work_queue.put(("log", f"> auto-applied {changed} files"))
                self.work_queue.put(("status", f"Applied {changed} files"))
                self.work_queue.put(("applied", changed))
                self.work_queue.put(("scan", None))
            else:
                self.work_queue.put(("status", f"Review {len(edits)} pending files"))
        except Exception as exc:
            self.work_queue.put(("log", f"! error: {exc}"))
            self.work_queue.put(("summary", f"Stopped because of an error: {exc}"))
            self.work_queue.put(("status", "Error"))

    def apply_pending(self):
        folder = self._validate_folder()
        if not folder or not self.pending_edits:
            return
        try:
            changed = apply_edits(folder, self.pending_edits)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.session_messages.append({"role": "system", "content": f"User accepted and applied {changed} files."})
        self.log(f"> accepted and applied {changed} files")
        self.pending_edits = []
        self.apply_button.configure(state=tk.DISABLED)
        self.reject_button.configure(state=tk.DISABLED)
        self.pending_count.set("0 pending")
        self.status.set(f"Applied {changed} files")
        self.set_summary("Changes accepted. You can ask for another change and the chat will continue with this context.")
        self.scan_folder(silent=True)

    def reject_pending(self):
        if not self.pending_edits:
            return
        count = len(self.pending_edits)
        self.session_messages.append({"role": "system", "content": f"User rejected {count} proposed files. Do not assume they were applied."})
        self.pending_edits = []
        self.diff_by_path = {}
        self.pending_count.set("0 pending")
        self.apply_button.configure(state=tk.DISABLED)
        self.reject_button.configure(state=tk.DISABLED)
        self.clear_changed_files()
        self.write_diff("")
        self.set_summary("Changes rejected. Add a correction in Instructions and run again to continue the same chat.")
        self.status.set("Changes rejected")
        self.log(f"> rejected {count} pending files")

    def clear_changed_files(self):
        for item in self.edited_files.get_children():
            self.edited_files.delete(item)

    def populate_changed_files(self, rows):
        self.clear_changed_files()
        for row in rows:
            self.edited_files.insert("", tk.END, iid=row["path"], values=(row["path"], row["stats"]))
        if rows:
            self.edited_files.selection_set(rows[0]["path"])
            self.edited_files.focus(rows[0]["path"])
            self.write_diff(self.diff_by_path.get(rows[0]["path"], ""))

    def on_file_selected(self, _event):
        selection = self.edited_files.selection()
        if not selection:
            return
        path = selection[0]
        self.write_diff(self.diff_by_path.get(path, ""))

    def write_diff(self, text):
        self.diff.configure(state=tk.NORMAL)
        self.diff.delete("1.0", tk.END)
        for line in text.splitlines(True):
            tag = None
            if line.startswith("+++ ") or line.startswith("--- FILE"):
                tag = "file"
            elif line.startswith("+") and not line.startswith("+++"):
                tag = "add"
            elif line.startswith("-") and not line.startswith("---"):
                tag = "del"
            elif line.startswith("@@") or line.startswith("--- "):
                tag = "meta"
            self.diff.insert(tk.END, line, tag)
        self.diff.configure(state=tk.DISABLED)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.work_queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "summary":
                    self.set_summary(payload)
                elif kind == "model_status":
                    self.model_status.set(payload)
                elif kind == "pending":
                    self.pending_edits = payload
                    self.pending_count.set(f"{len(payload)} pending")
                    if payload and not self.auto_apply.get():
                        self.apply_button.configure(state=tk.NORMAL)
                        self.reject_button.configure(state=tk.NORMAL)
                elif kind == "diffs":
                    self.diff_by_path = payload
                elif kind == "files":
                    self.populate_changed_files(payload)
                elif kind == "applied":
                    self.pending_edits = []
                    self.pending_count.set("0 pending")
                    self.apply_button.configure(state=tk.DISABLED)
                    self.reject_button.configure(state=tk.DISABLED)
                    self.set_summary(f"Applied {payload} files automatically. Continue with the next prompt.")
                elif kind == "scan":
                    self.scan_folder(silent=True)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _validate_folder(self, show_error=True):
        folder_text = self.selected_folder.get().strip()
        if not folder_text:
            if show_error:
                messagebox.showerror(APP_TITLE, "Choose a folder first.")
            return None
        folder = Path(folder_text).resolve()
        if not folder.exists() or not folder.is_dir():
            if show_error:
                messagebox.showerror(APP_TITLE, "Selected path is not a folder.")
            return None
        return folder


def load_local_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_local_config(config_data):
    CONFIG_PATH.write_text(json.dumps(config_data, indent=2), encoding="utf-8")


def choose_context_limits(root):
    root = Path(root)
    text_like_count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in DEFAULT_IGNORE_DIRS for part in parts[:-1]):
            continue
        if path.suffix.lower() in DEFAULT_IGNORE_EXTENSIONS:
            continue
        text_like_count += 1
    if text_like_count <= 80:
        return 220, 220
    if text_like_count <= 220:
        return 180, 180
    return 130, 140


def collect_files(root, max_files, max_file_kb):
    root = Path(root).resolve()
    files = []
    max_bytes = max_file_kb * 1024

    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in DEFAULT_IGNORE_DIRS for part in relative_parts[:-1]):
            continue
        if not is_context_file_allowed(path):
            continue
        if path.suffix.lower() in DEFAULT_IGNORE_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="cp1250")
            except UnicodeDecodeError:
                continue
        except OSError:
            continue
        files.append(SourceFile(path=path, relative_path=path.relative_to(root).as_posix(), content=content))
    return files


def collect_extra_context_files(paths, max_file_kb):
    files = []
    max_bytes = max_file_kb * 1024
    used_names = set()
    for path_text in paths:
        path = Path(path_text)
        if not is_context_file_allowed(path):
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_file() or resolved.stat().st_size > max_bytes:
                continue
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = resolved.read_text(encoding="cp1250")
            except UnicodeDecodeError:
                continue
        except OSError:
            continue
        context_name = unique_context_name(resolved, used_names)
        files.append(SourceFile(path=resolved, relative_path=f"{EXTERNAL_CONTEXT_PREFIX}/{context_name}", content=content))
    return files


def unique_context_name(path, used_names):
    base_name = path.name
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = f"{stem}-{index}{suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        index += 1


def is_context_file_allowed(path):
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in DEFAULT_IGNORE_FILE_NAMES:
        return False
    if suffix in DEFAULT_IGNORE_EXTENSIONS or suffix in DEFAULT_IGNORE_SECRET_EXTENSIONS:
        return False
    return True


def call_openrouter_with_fallback(api_key, instructions, files, session_messages, log_queue):
    errors = []
    for model in MODEL_FALLBACKS:
        log_queue.put(("log", f"> trying model: {model}"))
        try:
            response_text = call_openrouter(api_key, model, instructions, files, session_messages)
            result = parse_model_response(response_text)
            return result, model
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            log_queue.put(("log", f"> fallback after {model}: {short_error(exc)}"))
    raise RuntimeError("All free model fallbacks failed. " + " | ".join(errors))


def call_openrouter(api_key, model, instructions, files, session_messages):
    system_prompt = (
        "You are a senior coding agent inside a desktop app similar to Claude Code. "
        "You receive a project snapshot, a continuing chat history, and the latest request. "
        "Return only JSON with this exact shape: "
        "{\"summary\":\"short user-facing summary of what will change\","
        "\"files\":[{\"path\":\"relative/path.ext\",\"content\":\"complete new file content\"}]}. "
        "Include only files that must be created or replaced. Do not include markdown fences. "
        f"Never use absolute paths. Files under {EXTERNAL_CONTEXT_PREFIX}/ are read-only context; never return edits for them. "
        "Preserve unrelated code and formatting. "
        "If the request is conversational and needs no file edits, return an empty files array."
    )
    project = "\n\n".join(f"--- FILE: {source.relative_path} ---\n{source.content}" for source in files)
    history = "\n".join(f"{item['role']}: {item['content']}" for item in session_messages[-12:])
    user_prompt = (
        f"Continuing chat history:\n{history or '(none)'}\n\n"
        f"Latest user request:\n{instructions}\n\n"
        f"Project files:\n{project}\n\n"
        "Return the JSON now."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    request = Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local.coderouter",
            "X-Title": APP_TITLE,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenRouter connection failed: {exc}") from exc

    parsed = json.loads(body)
    return parsed["choices"][0]["message"]["content"]


def parse_model_response(response_text):
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    data = json.loads(cleaned)
    edits = []
    for item in data.get("files", []):
        path = item.get("path", "").strip().replace("\\", "/")
        content = item.get("content")
        if not path or content is None:
            continue
        if path == EXTERNAL_CONTEXT_PREFIX or path.startswith(f"{EXTERNAL_CONTEXT_PREFIX}/"):
            continue
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError(f"Unsafe path returned by model: {path}")
        edits.append({"path": path, "content": content})
    return {"summary": data.get("summary", "").strip(), "files": edits}


def render_diff_by_path(root, edits):
    root = Path(root).resolve()
    result = {}
    for edit in edits:
        target = root / edit["path"]
        if target.exists():
            try:
                old_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                old_content = target.read_text(encoding="cp1250")
        else:
            old_content = ""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = edit["content"].splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{edit['path']}",
            tofile=f"b/{edit['path']}",
            lineterm="",
        )
        lines = [f"--- FILE {edit['path']} ---\n"]
        for line in diff:
            lines.append(line if line.endswith("\n") else line + "\n")
        result[edit["path"]] = "".join(lines)
    return result


def build_file_rows(diff_by_path):
    rows = []
    for path, diff_text in diff_by_path.items():
        additions = 0
        deletions = 0
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
        rows.append({"path": path, "stats": f"+{additions} / -{deletions}"})
    return rows


def apply_edits(root, edits):
    root = Path(root).resolve()
    changed = 0
    for edit in edits:
        target = (root / edit["path"]).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Model tried to write outside selected folder: {edit['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        if existing != edit["content"]:
            target.write_text(edit["content"], encoding="utf-8", newline="")
            changed += 1
    return changed


def short_error(exc):
    text = str(exc).replace("\n", " ")
    return text[:180] + ("..." if len(text) > 180 else "")


def one_line(text):
    compact = " ".join(text.split())
    return compact[:160] + ("..." if len(compact) > 160 else "")


def main():
    app = CodeAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
