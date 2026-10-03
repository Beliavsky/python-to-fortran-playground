import io
import json
from pathlib import Path
import tempfile
import unittest

from xupdate_upstream import REPOSITORY, select_revision


class UpdateUpstreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pin = Path(self.directory.name) / 'upstream.json'
        self.original = {'repository': REPOSITORY, 'commit': 'a' * 40, 'pyodide': '0.27.7'}
        self.pin.write_text(json.dumps(self.original), encoding='utf-8')

    def opener(self, sha):
        def open_request(request, timeout):
            self.request = request
            self.assertEqual(timeout, 60)
            return io.BytesIO(json.dumps({'sha': sha}).encode())
        return open_request

    def test_latest_pin_preserves_other_settings(self):
        sha, changed = select_revision(self.pin, token='test-token', opener=self.opener('b' * 40))
        self.assertTrue(changed)
        self.assertEqual(sha, 'b' * 40)
        self.assertTrue(self.request.full_url.endswith('/commits/main'))
        self.assertEqual(self.request.get_header('Authorization'), 'Bearer test-token')
        self.assertEqual(json.loads(self.pin.read_text()), {**self.original, 'commit': sha})

    def test_same_revision_does_not_rewrite(self):
        before = self.pin.read_bytes()
        self.assertEqual(select_revision(self.pin, opener=self.opener('a' * 40)), ('a' * 40, False))
        self.assertEqual(self.pin.read_bytes(), before)

    def test_explicit_published_revision(self):
        self.assertEqual(select_revision(self.pin, 'B' * 40, opener=self.opener('b' * 40)), ('b' * 40, True))
        self.assertTrue(self.request.full_url.endswith('/commits/' + 'B' * 40))
        self.assertIsNone(self.request.get_header('Authorization'))

    def test_invalid_input_never_requests_or_changes_pin(self):
        before = self.pin.read_bytes()
        for revision in ('main', '../main', 'abc', 'a' * 40 + '\n'):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                select_revision(self.pin, revision, opener=lambda *a, **kw: self.fail('network request'))
        self.assertEqual(self.pin.read_bytes(), before)

    def test_invalid_response_leaves_pin_unchanged(self):
        before = self.pin.read_bytes()
        for sha in ('abc', 'B' * 40, 'b' * 40 + '\n', None):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                select_revision(self.pin, opener=self.opener(sha))
        self.assertEqual(self.pin.read_bytes(), before)

    def test_mismatched_revision_leaves_pin_unchanged(self):
        before = self.pin.read_bytes()
        with self.assertRaises(ValueError):
            select_revision(self.pin, 'b' * 40, opener=self.opener('c' * 40))
        self.assertEqual(self.pin.read_bytes(), before)

    def test_unexpected_repository_is_rejected(self):
        self.pin.write_text(json.dumps({**self.original, 'repository': 'other/repo'}))
        with self.assertRaises(ValueError):
            select_revision(self.pin, opener=lambda *a, **kw: self.fail('network request'))
