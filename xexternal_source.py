"""Fetch bounded public HTTPS source text without executing downloaded content."""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit, urljoin, unquote

MAX_SOURCE = 100_000


def source_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or re.search(r'\s|[\x00-\x1f\x7f]', value):
        raise ValueError('Enter a public HTTPS URL of at most 2048 characters.')
    try:
        value.encode('ascii')
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('Use a public HTTPS URL without credentials, a fragment, or a custom port.') from None
    return parsed


def public_addresses(host):
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    except OSError:
        raise ValueError('Could not resolve the source server hostname.') from None
    if not addresses or any(not ipaddress.ip_address(address).is_global or
                            ipaddress.ip_address(address).is_multicast or
                            ipaddress.ip_address(address).is_reserved for address in addresses):
        raise ValueError('External sources must resolve only to public Internet addresses.')
    return addresses[:2]


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address
        self.connected_socket = None

    def connect(self):
        # Pin the connection to the validated address; DNS cannot change between
        # checking a hostname and opening the socket. Verify TLS against the host.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            self.connected_socket = self.sock
        except BaseException:
            sock.close()
            raise

    def abort(self):
        # Also interrupt slow response headers or trickling bodies. A read
        # timeout alone only limits the time between individual received bytes.
        if self.connected_socket is not None:
            try:
                self.connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.close()


def fetch_source(url):
    deadline = time.monotonic() + 15
    for redirect in range(5):
        parsed = source_url(url)
        addresses = public_addresses(parsed.hostname)
        last_error = None
        for address in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('External source download timed out.')
            connection = PublicHTTPSConnection(parsed.hostname, address, min(5, remaining))
            timer = threading.Timer(remaining, connection.abort)
            timer.daemon = True
            timer.start()
            response = None
            try:
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                connection.request('GET', path, headers={'Accept': 'text/plain', 'Accept-Encoding': 'identity',
                                                         'User-Agent': 'Fortran-Playground-Source-Loader/1'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location:
                        raise ValueError('Source server returned a redirect without a destination.')
                    url = urljoin(url, location)
                    source_url(url)  # Validate every redirect, including HTTPS downgrade.
                    break
                if response.status != 200:
                    raise ValueError(f'Source server returned HTTP {response.status}. Use a direct raw-source URL.')
                if 'html' in response.getheader('Content-Type', '').lower():
                    raise ValueError('That URL returned a web page. Use the raw Fortran source URL.')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Source server returned compressed content; use a direct uncompressed source URL.')
                declared = response.getheader('Content-Length')
                if declared is not None:
                    try:
                        declared = int(declared)
                    except ValueError:
                        raise ValueError('Source server returned an invalid content length.') from None
                    if not 0 <= declared <= MAX_SOURCE:
                        raise ValueError('External source exceeds the 100 KB limit.')
                data = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError('External source download timed out.')
                    if connection.connected_socket is not None:
                        connection.connected_socket.settimeout(min(5, remaining))
                    chunk = response.read1(min(8192, MAX_SOURCE + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_SOURCE:
                        raise ValueError('External source exceeds the 100 KB limit.')
                if time.monotonic() > deadline:
                    raise ValueError('External source download timed out.')
                if declared is not None and len(data) != declared:
                    raise ValueError('Source download was incomplete; load it again.')
                try:
                    source = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
                except UnicodeError:
                    raise ValueError('External source must be UTF-8 text.') from None
                if not source.strip() or '\0' in source or re.match(r'\s*<(?:!doctype|html)\b', source, re.I):
                    raise ValueError('The URL did not return nonempty Fortran source text.')
                filename = re.sub(r'[^A-Za-z0-9_.-]', '_', unquote(parsed.path.rsplit('/', 1)[-1]))[:100]
                return {'url': url, 'filename': filename or 'external.f90', 'source': source,
                        'sha256': hashlib.sha256(source.encode('utf-8')).hexdigest()}
            except (OSError, http.client.HTTPException) as error:
                last_error = error
            finally:
                timer.cancel()
                if response is not None:
                    response.close()
                connection.close()
        else:
            raise ValueError('Could not download the external source over verified HTTPS.') from last_error
    raise ValueError('External source has too many redirects.')
