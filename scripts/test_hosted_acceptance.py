"""Acceptance fetches must not follow redirects or leak the bearer token or login body.

Servers bind to ephemeral loopback ports and serve synthetic routes only.
"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import hosted_acceptance

JSON = {'Content-Type': 'application/json'}


def start_server(routes):
    """Serve `routes` ({path: (status, headers, body)}) and record every request it receives."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b''
            hits.append({'method': self.command, 'path': self.path, 'authorization': self.headers.get('Authorization'), 'body': body})
            status, headers, payload = routes.get(self.path, (404, JSON, b'{"code": "NOT_FOUND"}'))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = handle_request

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}', hits


class NoRedirectFetch(unittest.TestCase):
    def setUp(self):
        self.destination_routes = {
            '/landing': (200, JSON, b'{"landed": true}'),
            '/auth/login-moved': (200, JSON, b'{"token": "dummy-session-token"}'),
        }
        self.destination, self.destination_url, self.destination_hits = start_server(self.destination_routes)
        self.addCleanup(self.destination.server_close)
        self.addCleanup(self.destination.shutdown)
        self.origin_routes = {
            '/ok': (200, JSON, b'{"status": "ready"}'),
            '/denied': (401, JSON, b'{"code": "UNAUTHORIZED"}'),
            '/same-redirect': (302, {'Location': '/landing'}, b''),
            '/cross-redirect': (302, {'Location': self.destination_url + '/landing'}, b''),
            '/html-redirect': (302, {'Location': self.destination_url + '/landing'}, b'<html>Moved</html>'),
            '/auth/login': (200, JSON, b'{"token": "dummy-session-token"}'),
            '/auth/login-307': (307, {'Location': '/auth/login-moved'}, b''),
            '/auth/login-cross': (302, {'Location': self.destination_url + '/auth/login-moved'}, b''),
        }
        self.origin, self.origin_url, self.origin_hits = start_server(self.origin_routes)
        self.addCleanup(self.origin.server_close)
        self.addCleanup(self.origin.shutdown)
        self.checks = []
        self.fetch = hosted_acceptance.make_fetch(self.origin_url, self.checks)

    def test_direct_request_succeeds_with_bearer(self):
        result = self.fetch('direct', self.origin_url + '/ok', token='dummy-token')
        self.assertEqual(result, {'status': 'ready'})
        self.assertTrue(self.checks[-1]['passed'])
        self.assertEqual(self.checks[-1]['status'], 200)
        self.assertEqual(self.origin_hits[-1]['authorization'], 'Bearer dummy-token')

    def test_html_redirect_keeps_refused_status_without_parsing_body(self):
        result = self.fetch('html_redirect', self.origin_url + '/html-redirect', (302,), token='dummy-token')
        self.assertIsNone(result)
        self.assertFalse(self.checks[-1]['passed'])
        self.assertEqual(self.checks[-1]['status'], 302)
        self.assertEqual(self.checks[-1]['failure_category'], 'REDIRECT_REFUSED')
        self.assertEqual(self.destination_hits, [])

    def test_http_error_status_is_still_reported(self):
        result = self.fetch('denied', self.origin_url + '/denied', (200,), token='dummy-token')
        self.assertEqual(result, {'code': 'UNAUTHORIZED'})
        self.assertFalse(self.checks[-1]['passed'])
        self.assertEqual(self.checks[-1]['status'], 401)
        self.assertEqual(self.checks[-1]['failure_category'], 'UNAUTHORIZED')

    def test_same_origin_redirect_is_refused_and_not_followed(self):
        result = self.fetch('same', self.origin_url + '/same-redirect', token='dummy-token')
        self.assertIsNone(result)
        self.assertFalse(self.checks[-1]['passed'])
        self.assertEqual(self.checks[-1]['status'], 302)
        self.assertEqual([hit['path'] for hit in self.origin_hits], ['/same-redirect'])

    def test_cross_origin_redirect_is_refused_and_destination_gets_no_call(self):
        result = self.fetch('cross', self.origin_url + '/cross-redirect', token='dummy-token')
        self.assertIsNone(result)
        self.assertFalse(self.checks[-1]['passed'])
        self.assertEqual(self.checks[-1]['status'], 302)
        self.assertEqual(self.destination_hits, [])
        self.assertEqual([hit['path'] for hit in self.origin_hits], ['/cross-redirect'])

    def test_no_dummy_bearer_is_forwarded_to_a_redirect_target(self):
        for path in ('/same-redirect', '/cross-redirect'):
            self.fetch('bearer', self.origin_url + path, token='dummy-token')
        self.assertEqual(self.destination_hits, [])
        self.assertTrue(all(hit['authorization'] == 'Bearer dummy-token' for hit in self.origin_hits))

    def test_login_body_is_not_replayed_to_a_redirect_target(self):
        body = {'username': 'dummy-user', 'password': 'dummy-password'}
        for path in ('/auth/login-307', '/auth/login-cross'):
            with self.subTest(path=path):
                self.assertIsNone(self.fetch('login', self.origin_url + path, body=body))
                self.assertFalse(self.checks[-1]['passed'])
                self.assertIn(self.checks[-1]['status'], (302, 307))
        self.assertEqual(self.destination_hits, [])
        self.assertTrue(all(b'dummy-password' in hit['body'] for hit in self.origin_hits))

    def test_report_never_contains_login_credentials_or_session_token(self):
        environment = {
            'FLOORREPLAY_ACCEPTANCE_OWNER': 'dummy-owner',
            'FLOORREPLAY_ACCEPTANCE_OWNER_PASSWORD': 'dummy-owner-secret',
        }
        with patch.dict(os.environ, environment):
            token = hosted_acceptance.sign_in(self.fetch, self.origin_url, 'owner')
        self.assertEqual(token, 'dummy-session-token')
        report = json.dumps(self.checks)
        self.assertNotIn('dummy-owner-secret', report)
        self.assertNotIn('dummy-session-token', report)


if __name__ == '__main__':
    unittest.main()
