"""Public-source retrieval is finite, authenticated, and never follows private URLs."""
import hashlib
import socket
import unittest
from unittest.mock import Mock, patch

import xexternal_source as source


def response(data=b'module sample\nend module\n', status=200, headers=None):
    reply = Mock(status=status)
    headers = headers or {}
    reply.getheader.side_effect = lambda name, default=None: headers.get(name, default)
    reply.read1.side_effect = [data, b'']
    return reply


class SourceFetchTests(unittest.TestCase):
    def test_https_connect_uses_pinned_ip_and_original_tls_hostname(self):
        context = Mock()
        with patch.object(source.ssl, 'create_default_context', return_value=context), \
                patch.object(source.socket, 'create_connection') as connect:
            connection = source.PublicHTTPSConnection('example.org', '93.184.216.34', 5)
            connection.connect()
        connect.assert_called_once_with(('93.184.216.34', 443), 5)
        context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname='example.org')

    def test_fetch_normalizes_utf8_pins_address_and_preserves_provenance(self):
        reply = response(b'\xef\xbb\xbfmodule sample\r\nend module\r\n')
        connection = Mock()
        connection.getresponse.return_value = reply
        with patch.object(source, 'public_addresses', return_value=['93.184.216.34']), \
                patch.object(source, 'PublicHTTPSConnection', return_value=connection) as opened:
            result = source.fetch_source('https://example.org/sample.f90')
        self.assertEqual(result['source'], 'module sample\nend module\n')
        self.assertEqual(result['filename'], 'sample.f90')
        self.assertEqual(result['sha256'], hashlib.sha256(result['source'].encode()).hexdigest())
        self.assertEqual(opened.call_args.args[:2], ('example.org', '93.184.216.34'))
        self.assertNotIn('Authorization', connection.request.call_args.kwargs['headers'])
        connection.close.assert_called_once()

    def test_urls_and_dns_cannot_target_private_networks(self):
        for url in ('http://example.org/x', 'https://user:secret@example.org/x',
                    'https://example.org:8000/x', 'https://example.org/x#fragment',
                    'https://example.org/\r\nX-Header: value', 'file:///tmp/x', 'https:///x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                source.source_url(url)
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', 'ff02::1', '::ffff:127.0.0.1'):
            answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
            with patch.object(source.socket, 'getaddrinfo', return_value=answer), self.assertRaises(ValueError):
                source.public_addresses('example.org')

    def test_redirects_are_revalidated_and_bounded(self):
        connection = Mock()
        connection.getresponse.side_effect = [response(status=302, headers={'Location': 'https://127.0.0.1/x'})]
        def addresses(host):
            if host == '127.0.0.1':
                raise ValueError('private address')
            return ['93.184.216.34']
        with patch.object(source, 'public_addresses', side_effect=addresses), \
                patch.object(source, 'PublicHTTPSConnection', return_value=connection) as opened:
            with self.assertRaisesRegex(ValueError, 'private'):
                source.fetch_source('https://example.org/x')
        self.assertEqual(opened.call_count, 1)
        connection.getresponse.side_effect = None
        connection.getresponse.return_value = response(status=302, headers={'Location': '/again'})
        with patch.object(source, 'public_addresses', return_value=['93.184.216.34']), \
                patch.object(source, 'PublicHTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'too many redirects'):
                source.fetch_source('https://example.org/x')

    def test_rejects_oversize_html_binary_and_empty_content(self):
        for reply in (response(b'x' * 100001), response(b'\xff'), response(b'\0'), response(b''),
                      response(b'<!doctype html>'), response(headers={'Content-Type': 'text/html'}),
                      response(headers={'Content-Encoding': 'gzip'}), response(status=404),
                      response(headers={'Content-Length': '100001'}), response(headers={'Content-Length': '999'})):
            connection = Mock()
            connection.getresponse.return_value = reply
            with patch.object(source, 'public_addresses', return_value=['93.184.216.34']), \
                    patch.object(source, 'PublicHTTPSConnection', return_value=connection), self.assertRaises(ValueError):
                source.fetch_source('https://example.org/source.f90')


if __name__ == '__main__':
    unittest.main()
