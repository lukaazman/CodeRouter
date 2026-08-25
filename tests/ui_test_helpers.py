import unittest


def build_hidden_app(wrapper, *args, **kwargs):
    try:
        app = wrapper.CodeAgentApp(*args, **kwargs)
        app.withdraw()
        return app
    except wrapper.tk.TclError as exc:
        raise unittest.SkipTest(f"Tk app unavailable: {exc}") from exc
