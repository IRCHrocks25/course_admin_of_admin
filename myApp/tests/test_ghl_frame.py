from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from myApp.middleware import GhlEmbedFrameMiddleware


class FrameMiddlewareTests(TestCase):
    def _run(self, path, session=None):
        rf = RequestFactory()
        req = rf.get(path)
        req.session = session or {}
        mw = GhlEmbedFrameMiddleware(lambda r: HttpResponse("ok", headers={"X-Frame-Options": "DENY"}))
        return mw(req)

    def test_embed_path_sets_csp_and_drops_xfo(self):
        resp = self._run("/ghl/embed")
        self.assertIn("frame-ancestors", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("X-Frame-Options", resp.headers)

    def test_embed_session_dashboard_allows_frame(self):
        resp = self._run("/dashboard/", session={"ghl_embed": True})
        self.assertIn("leadconnectorhq.com", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("X-Frame-Options", resp.headers)

    def test_non_embed_keeps_deny(self):
        resp = self._run("/dashboard/")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
