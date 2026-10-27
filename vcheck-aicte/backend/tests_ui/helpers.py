"""Browser test harness: the real WSGI app on a real socket + headless Chromium via Playwright."""
import os
import re
import threading
import unittest
from wsgiref.simple_server import WSGIRequestHandler, make_server

from playwright.sync_api import sync_playwright

from tests_api.helpers import make_app
from vcheck_api.server import ThreadingWSGIServer

SHOTS = os.environ.get("VCHECK_SHOTS")          # set to a directory to also save screenshots


class _Quiet(WSGIRequestHandler):
    def log_message(self, *a):
        pass


class UiCase(unittest.TestCase):
    """One server + one browser per class; a fresh browser context (clean storage) per test."""
    sync_processing = False

    @classmethod
    def setUpClass(cls):
        cls.app = make_app(sync_processing=cls.sync_processing)
        cls.srv = make_server("127.0.0.1", 0, cls.app, server_class=ThreadingWSGIServer, handler_class=_Quiet)
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.srv.shutdown()
        cls.app.ctx.executor.shutdown(wait=True)

    def setUp(self):
        self.errors = []
        self.contexts = []

    def tearDown(self):
        for c in self.contexts:
            c.close()
        real = [e for e in self.errors if "ERR_ABORTED" not in e and "Failed to load resource" not in e]
        self.assertEqual(real, [], "browser console/page errors")

    def page(self, width=1440, height=900):
        ctx = self.browser.new_context(viewport={"width": width, "height": height})
        self.contexts.append(ctx)
        ctx.set_default_timeout(15000)
        pg = ctx.new_page()
        pg.on("console", lambda m: self.errors.append("console: " + m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: self.errors.append("pageerror: " + str(e)))
        return pg

    ACCOUNTS = {"applicant": ("applicant@demo.vcheck", "Applicant@Demo2026"), "applicant2": ("applicant2@demo.vcheck", "Applicant@Demo2026"),
                "reviewer": ("reviewer@demo.vcheck", "Reviewer@Demo2026"), "administrator": ("admin@demo.vcheck", "Admin@Demo2026")}

    def login(self, pg, role):
        """Sign in through the real form (one-click demo buttons exist for 3 roles; others are typed)."""
        pg.goto(self.base + "/login")
        email, pw = self.ACCOUNTS[role]
        pg.fill("input[name=email]", email)
        pg.fill("input[name=password]", pw)
        pg.click("button[type=submit]")
        pg.wait_for_selector(".shell")
        return pg

    def until(self, pg, expr, timeout=15.0, step=0.1):
        """Poll a JS expression from the isolated world. (page.wait_for_function uses eval, which the app's strict CSP refuses.)"""
        import time
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = pg.evaluate(expr)
            if last:
                return last
            time.sleep(step)
        raise AssertionError(f"timed out waiting for: {expr[:140]} (last={last!r})")

    def shot(self, pg, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            pg.screenshot(path=os.path.join(SHOTS, re.sub(r"[^a-z0-9_]+", "_", name.lower()) + ".png"))

    def nav_texts(self, pg):
        return [" ".join(t.split()) for t in pg.locator(".nav a").all_inner_texts()]

    def toast_text(self, pg):
        pg.wait_for_selector("#toasts .toast")
        return pg.locator("#toasts .toast").last.inner_text()
