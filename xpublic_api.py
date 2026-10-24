"""Public API with per-session job ownership and persistent workload limits.

The backend must launch isolated sandboxes. This module never executes source.
The deployment uses one API container so its lock serializes state changes.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from compiler_options import OPTIONS, user_flags
from translation_options import validate_options
from xexternal_source import fetch_source, source_url

MAX_REQUEST = 1_900_000  # Two sources and stdin, including JSON escaping.
MAX_SOURCE = 100_000
MAX_STDIN = 100_000
MAX_RESULT = 8_000_000  # Includes the private, bounded executable export.
MAX_EXECUTABLE = 4 * 1024 * 1024
ARTIFACT_TTL = 300
MAX_ARTIFACTS = 32
MAX_ACTIVE = 2
MAX_DAILY = 100
MAX_PER_ADDRESS = 30  # over a ten-minute window; sessions share this allowance
ORIGINS = ['https://beliavsky.github.io', 'http://127.0.0.1:8766', 'http://localhost:8766']
EDIT_MODES = {'fortran-edit', 'both-edit', 'compare-edit', 'fortran-compile'}
MODES = {'translate', 'annotate', 'format', 'check', 'python', 'fortran', 'both', 'compare', 'fortran-run'} | EDIT_MODES
COMPILERS = {'gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran', 'ofort'}


class PublicService:
    def __init__(self, store, runner, commit, clock=time.time, compilers=('gfortran',), runtime_namespace=None,
                 compiler_versions=None, compiler_standards=None, owner_key='', compiler_coarrays=None):
        self.store, self.runner, self.commit, self.clock = store, runner, commit, clock
        self.lock = asyncio.Lock()
        self.compilers = tuple(compilers)
        self.compiler_versions = dict(compiler_versions or {})
        self.compiler_standards = dict(compiler_standards or {})
        self.compiler_coarrays = dict(compiler_coarrays or {})
        self.runtime_namespace = runtime_namespace or commit
        self.owner_key = owner_key
        self.external_loads = 0
        if owner_key and not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', owner_key):
            raise ValueError('P2F_OWNER_KEY must contain 32 to 256 URL-safe letters, digits, underscores, or hyphens.')

    def compiler_catalog(self):
        return {name: {**spec, 'coarray_images': {count: flags for count, flags in spec.get('coarray_images', {}).items()
                    if self.compiler_coarrays.get(name, {}).get(count) == flags},
                    'standards': {year: flags for year, flags in spec['standards'].items()
                    if self.compiler_standards.get(name, {}).get(year) == flags}}
                for name, spec in OPTIONS.items()}

    async def board(self):
        board = await self.store.get('board', None)
        if board is None:
            board = {'secret': secrets.token_hex(32), 'sessions': {}, 'jobs': {}, 'rates': {}, 'day': '', 'daily': 0}
        now = self.clock()
        board['sessions'] = {k: v for k, v in board['sessions'].items() if v['expires'] > now}
        artifacts = board.setdefault('artifacts', {})
        for identifier, artifact in list(artifacts.items()):
            if (artifact['expires'] <= now or artifact['owner'] not in board['sessions']
                    or artifact['runtime'] != self.runtime_namespace):
                await self.store.pop('artifact:' + identifier)
                del artifacts[identifier]
        for field in ('rates', 'source_loads'):
            board[field] = {k: [t for t in times if t > now - 600] for k, times in board.get(field, {}).items() if times and times[-1] > now - 600}
        for identifier, job in list(board['jobs'].items()):
            if job['expires'] < now:
                await self.store.pop('result:' + identifier)
                del board['jobs'][identifier]
        day = time.strftime('%Y-%m-%d', time.gmtime(now))
        if board['day'] != day:
            board['day'], board['daily'], board['owner_daily'] = day, 0, 0
        return board

    def owner(self, board, token):
        key = hashlib.sha256(token.encode()).hexdigest()
        if key not in board['sessions']:
            raise HTTPException(403, 'Session expired. Click Reconnect.')
        return key, board['sessions'][key]

    async def session(self, address):
        async with self.lock:
            board = await self.board()
            if len(board['sessions']) >= 256:
                raise HTTPException(429, 'Too many sessions. Please try later.')
            token = secrets.token_urlsafe(32)
            key = hashlib.sha256(token.encode()).hexdigest()
            address_key = hmac.new(bytes.fromhex(board['secret']), address.encode(), hashlib.sha256).hexdigest()
            board['sessions'][key] = {'expires': self.clock() + 3600, 'address': address_key}
            await self.store.put('board', board)
            return {'token': token, 'commit': self.commit, 'timeout': 30, 'compiler': 'gfortran',
                    'compilers': list(self.compilers), 'hosted': True, 'compiler_options': self.compiler_catalog(), 'source_tools': True,
                    'compiler_versions': {name: self.compiler_versions.get(name) for name in self.compilers},
                    'features': {'compile_only': True, 'run_again': True, 'format': True, 'check': True,
                                 'stdin': True, 'max_stdin_bytes': MAX_STDIN,
                                 'external_source': True,
                                 'owner_access': bool(self.owner_key), 'artifact_ttl': ARTIFACT_TTL}}

    async def external_source(self, token, url):
        try:
            source_url(url)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        async with self.lock:
            board = await self.board()
            _, session = self.owner(board, token)
            recent = board['source_loads'].setdefault(session['address'], [])
            if self.external_loads >= 2 or len(recent) >= 30:
                raise HTTPException(429, 'Source downloads are busy or this address has reached 30 loads in ten minutes.')
            recent.append(self.clock())
            await self.store.put('board', board)
            self.external_loads += 1
        task = asyncio.create_task(asyncio.to_thread(fetch_source, url))
        def finished(task):
            self.external_loads -= 1
            if not task.cancelled():
                task.exception()  # Retrieve exceptions even after a request times out.
        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), 20)
        except asyncio.TimeoutError:
            raise HTTPException(504, 'External source download timed out.') from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    async def retain(self, board, job, result):
        blob = result.pop('_artifact', None)  # Never return executable bytes to browsers.
        if (not job.get('retain_executable') or job.get('mode') not in {'fortran-compile', 'fortran-edit'}
                or job.get('runtime') != self.runtime_namespace
                or not result.get('build', {}).get('ok') or not isinstance(blob, str)):
            return
        if len(blob) > (MAX_EXECUTABLE + 2) // 3 * 4:
            return
        try:
            binary = base64.b64decode(blob, validate=True)
        except ValueError:
            return
        if not binary or len(binary) > MAX_EXECUTABLE or job['owner'] not in board['sessions']:
            return
        artifacts = board['artifacts']
        # At most one retained executable per session, with a global size bound.
        for identifier, artifact in list(artifacts.items()):
            if artifact['owner'] == job['owner']:
                await self.store.pop('artifact:' + identifier)
                del artifacts[identifier]
        if len(artifacts) >= MAX_ARTIFACTS:
            result['artifact_note'] = 'The retained-build allowance is full. Compile again later to enable Run Again.'
            return
        identifier = secrets.token_urlsafe(24)
        expires = min(self.clock() + ARTIFACT_TTL, board['sessions'][job['owner']]['expires'])
        artifacts[identifier] = {'owner': job['owner'], 'expires': expires, 'compiler': job['compiler'],
                                'compiler_options': job.get('compiler_options'), 'runtime': self.runtime_namespace}
        await self.store.put('artifact:' + identifier, blob)
        result['artifact'] = {'id': identifier, 'expires_at': expires, 'compiler': job['compiler']}

    async def reap(self, board):
        for identifier, job in board['jobs'].items():
            if job['state'] != 'running':
                continue
            try:
                result = await self.runner.poll(job['sandbox'])
            except Exception:
                result = {'ok': False, 'error': 'Execution environment stopped. Try again.'}
            if result is not None:
                await self.retain(board, job, result)
                result['commit'] = self.commit
                await self.store.put('result:' + identifier, result)
                job['state'] = 'done'
                job['expires'] = self.clock() + 300

    async def submit(self, token, payload, owner_key=''):
        exempt = False
        if owner_key:
            if (not self.owner_key or len(owner_key) > 256 or
                    not hmac.compare_digest(self.owner_key.encode(), owner_key.encode())):
                raise HTTPException(403, 'Invalid owner key. No job was submitted.')
            exempt = True
        async with self.lock:
            board = await self.board()
            owner, session = self.owner(board, token)
            await self.reap(board)
            # Persist completed jobs/expiry cleanup even if this submission is
            # rejected (for example, an expired retained-build identifier).
            await self.store.put('board', board)
            if payload.get('mode') == 'fortran-run':
                artifact = board['artifacts'].get(payload.get('artifact_id'))
                if not artifact or artifact['owner'] != owner:
                    raise HTTPException(404, 'Retained build expired or not found. Compile again.')
                blob = await self.store.get('artifact:' + payload['artifact_id'], None)
                if blob is None:
                    raise HTTPException(404, 'Retained build expired or not found. Compile again.')
                payload = {**payload, 'executable': blob, 'compiler': artifact['compiler'],
                           'compiler_options': artifact['compiler_options']}
            if (payload.get('mode') in {'fortran', 'both', 'compare', 'fortran-run'} | EDIT_MODES
                    and payload.get('compiler', 'gfortran') not in self.compilers):
                raise HTTPException(503, 'Selected compiler is unavailable. Choose GNU Fortran; no automatic fallback was used.')
            try:
                name = payload.get('compiler', 'gfortran')
                if name == 'ofort' and (payload.get('mode') not in {'fortran-edit', 'fortran-compile', 'format', 'check'}
                        or payload.get('retain_executable', False) or payload.get('automatic', False)):
                    raise ValueError('ofort supports standalone Fortran checks/runs only, without retained executables.')
                catalog = self.compiler_catalog()[name]
                user_flags(name, payload.get('compiler_options'), standards=catalog['standards'], coarrays=catalog['coarray_images'])
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            if sum(job['state'] in {'running', 'starting'} for job in board['jobs'].values()) >= MAX_ACTIVE:
                await self.store.put('board', board)
                raise HTTPException(429, 'Two jobs are already running. Wait briefly and try again.')
            recent = board['rates'].setdefault(session['address'], [])
            if not exempt and len(recent) >= MAX_PER_ADDRESS:
                raise HTTPException(429, 'Too many jobs from this address. Try again in ten minutes.')
            if not exempt and board['daily'] >= MAX_DAILY:
                raise HTTPException(429, 'The daily execution allowance has been reached. Try tomorrow (UTC).')
            if exempt:
                board['owner_daily'] = board.get('owner_daily', 0) + 1
            else:
                recent.append(self.clock())
                board['daily'] += 1
            identifier = secrets.token_urlsafe(24)
            metadata = {key: payload.get(key) for key in ('mode', 'compiler', 'compiler_options', 'retain_executable')}
            metadata['compiler'] = payload.get('compiler', 'gfortran')
            metadata['runtime'] = self.runtime_namespace
            # Reserve a slot and charge the allowance before provisioning.
            # A crashed provisioner cannot reset usage or bypass concurrency.
            board['jobs'][identifier] = {**metadata, 'owner': owner, 'sandbox': None, 'state': 'starting', 'expires': self.clock() + 600}
            await self.store.put('board', board)
            try:
                sandbox = await self.runner.start(payload)
            except Exception:
                logging.getLogger(__name__).exception('Sandbox provisioning failed')
                board['jobs'][identifier]['state'] = 'done'
                await self.store.put('board', board)
                raise HTTPException(503, 'Could not start an execution environment. The service owner should check the Modal logs.')
            board['jobs'][identifier] = {**metadata, 'owner': owner, 'sandbox': sandbox, 'state': 'running', 'expires': self.clock() + 600}
            await self.store.put('board', board)
            return {'id': identifier}

    async def job(self, token, identifier, cancel=False):
        async with self.lock:
            board = await self.board()
            owner, _ = self.owner(board, token)
            job = board['jobs'].get(identifier)
            if not job or job['owner'] != owner:
                raise HTTPException(404, 'Job expired or not found.')
            if cancel and job['state'] == 'running':
                await self.runner.cancel(job['sandbox'])
                job['state'], job['expires'] = 'done', self.clock() + 300
                await self.store.put('result:' + identifier, {'ok': False, 'error': 'Cancelled.', 'commit': self.commit})
            elif not cancel:
                await self.reap(board)
            await self.store.put('board', board)
            if cancel:
                return {'cancelled': True}
            if job['state'] == 'running':
                return {'state': 'running'}
            return {'state': 'done', 'result': await self.store.get('result:' + identifier, None)}


def create_api(service):
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.exception_handler(HTTPException)
    async def error(_request, exception):
        return JSONResponse({'error': exception.detail}, status_code=exception.status_code)

    @api.middleware('http')
    async def origin_and_headers(request, call_next):
        if request.url.path != '/api/health' and request.headers.get('origin') not in ORIGINS:
            return JSONResponse({'error': 'Open the p2f playground to use this service.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    # Add last so CORS wraps error responses from the Origin middleware too.
    api.add_middleware(CORSMiddleware, allow_origins=ORIGINS,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-P2F-Token', 'X-P2F-Owner-Key'])

    @api.get('/api/health')
    async def health():
        return {'ok': True, 'commit': service.commit, 'sandbox': 'gvisor', 'network': False,
                'compilers': list(service.compilers)}

    @api.get('/api/session')
    async def session(request: Request):
        # Use the ASGI peer supplied by the hosting platform; do not trust an
        # arbitrary user-supplied X-Forwarded-For header for rate limiting.
        return await service.session(request.client.host if request.client else 'unknown')

    @api.post('/api/external-source')
    async def external_source(request: Request):
        token = request.headers.get('x-p2f-token', '')
        if not token or len(token) > 100:
            raise HTTPException(403, 'Click Reconnect before loading external source.')
        if request.headers.get('content-type') != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 8192:
                raise HTTPException(413, 'Source URL request is too large.')
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict) or set(payload) != {'url'}:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Supply one external source URL.') from None
        return await service.external_source(token, payload['url'])

    @api.post('/api/jobs', status_code=202)
    async def submit(request: Request):
        token = request.headers.get('x-p2f-token', '')
        if not token or len(token) > 100:
            raise HTTPException(403, 'Click Reconnect before running a program.')
        if request.headers.get('content-type') != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_REQUEST:
                raise HTTPException(413, 'Request exceeds the input limit.')
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError()
            source, mode = payload.get('source', ''), payload.get('mode')
            compiler = payload.get('compiler', 'gfortran')
            ft_source = payload.get('fortran_source')
            stdin = payload.get('stdin', '')
            if (not isinstance(stdin, str) or len(stdin.encode('utf-8')) > MAX_STDIN
                    or (stdin and mode in ('translate', 'annotate', 'format', 'check', 'fortran-compile'))):
                raise HTTPException(400, 'Program input must be UTF-8 text up to 100 KB, for an execution operation.')
            if (not isinstance(mode, str) or mode not in MODES
                    or not isinstance(source, str) or (not source.strip() and mode not in {'fortran-edit', 'fortran-compile', 'fortran-run'}) or len(source.encode()) > MAX_SOURCE
                    or (mode in EDIT_MODES and (not isinstance(ft_source, str) or not ft_source.strip()
                        or len(ft_source.encode()) > MAX_SOURCE or payload.get('automatic', False)))
                    or not isinstance(payload.get('automatic', False), bool)
                    or (mode in {'format', 'check'} and payload.get('automatic', False))
                    or not isinstance(payload.get('retain_executable', False), bool)
                    or (payload.get('retain_executable', False) and mode not in {'fortran-edit', 'fortran-compile'})
                    or (mode == 'fortran-run' and (payload.get('automatic', False)
                        or not isinstance(payload.get('artifact_id'), str) or not 1 <= len(payload['artifact_id']) <= 100))
                    or not isinstance(compiler, str) or compiler not in COMPILERS):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Enter valid source (up to 100 KB per language) and a valid operation.')
        payload['source'] = source
        try:
            user_flags(compiler, payload.get('compiler_options'))
            validate_options(payload.get('translation_options'))
        except ValueError as error:
            raise HTTPException(400, str(error))
        return await service.submit(token, {key: payload[key] for key in
            ('source', 'mode', 'automatic', 'compiler', 'fortran_source', 'compiler_options', 'translation_options',
             'retain_executable', 'artifact_id', 'stdin') if key in payload
            and (key != 'fortran_source' or mode in EDIT_MODES)},
            owner_key=request.headers.get('x-p2f-owner-key', ''))

    @api.get('/api/jobs/{identifier}')
    async def job(identifier: str, request: Request):
        return await service.job(request.headers.get('x-p2f-token', ''), identifier)

    @api.post('/api/jobs/{identifier}/cancel')
    async def cancel(identifier: str, request: Request):
        return await service.job(request.headers.get('x-p2f-token', ''), identifier, cancel=True)

    return api
