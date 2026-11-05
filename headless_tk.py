"""Stand-ins for tkinter so `exec`, `ask` and `commands` run where Tk is missing.

Only import-time names need to exist: classes to subclass, constants and
exception types. Opening the window still requires a real Tk.
"""

import types


class TclError(Exception):
    pass


class _Stub:
    def __init__(self, *_args, **_kwargs):
        raise RuntimeError("Tkinter is not installed; only exec, ask and commands work headless.")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.isupper() or name[:1].islower():
            return name.lower()  # constants such as END, NORMAL, LEFT
        stub = type(name, (_Stub,), {})
        setattr(self, name, stub)
        return stub


def _module(name):
    module = _StubModule(name)
    module.TclError = TclError
    return module


tk = _module("tkinter")
tkfont = _module("tkinter.font")
filedialog = _module("tkinter.filedialog")
messagebox = _module("tkinter.messagebox")
scrolledtext = _module("tkinter.scrolledtext")
ttk = _module("tkinter.ttk")
tk.TkVersion = 0.0
