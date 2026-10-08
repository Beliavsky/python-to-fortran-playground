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
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from compiler_options import OPTIONS, user_flags
from translation_options import validate_options

MAX_REQUEST = 1_300_000
MAX_SOURCE = 100_000
MAX_RESULT = 8_000_000  # Includes the private, bounded executable export.
MAX_EXECUTABLE = 4 * 1024 * 1024
ARTIFACT_TTL = 300
MAX_ARTIFACTS = 32
MAX_ACTIVE = 2
MAX_DAILY = 100
MAX_PER_ADDRESS = 30  # over a ten-minute window; sessions share this allowance
ORIGINS = ['https://beliavsky.github.io', 'http://127.0.0.1:8766', 'http://localhost:8766']
EDIT_MODES = {'fortran-edit', 'both-edit', 'compare-edit', 'fortran-compile'}
MODES = {'translate', 'annotate', 'python', 'fortran', 'both', 'compare', 'fortran-run'} | EDIT_MODES
COMPILERS = {'gfortran', 'ifx', 'flang', 'lfortran'}


class PublicService:
    def __init__(self, store, runner, commit, clock=time.time, compilers=('gfortran',), runtime_namespace=None):
        self.store, self.runner, self.commit, self.clock = store, runner, commit, clock
        self.lock = asyncio.Lock()
        self.compilers = tuple(compilers)
        self.runtime_namespace = runtime_namespace or commit

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
        board['rates'] = {k: [t for t in times if t > now - 600] for k, times in board['rates'].items() if times and times[-1] > now - 600}
        for identifier, job in list(board['jobs'].items()):
            if job['expires'] < now:
                await self.store.pop('result:' + identifier)
                del board['jobs'][identifier]
        day = time.strftime('%Y-%m-%d', time.gmtime(now))
        if board['day'] != day:
            board['day'], board['daily'] = day, 0
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
                    'compilers': list(self.compilers), 'hosted': True, 'compiler_options': OPTIONS, 'source_tools': True,
                    'features': {'compile_only': True, 'run_again': True, 'artifact_ttl': ARTIFACT_TTL}}

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

    async def submit(self, token, payload):
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
            if sum(job['state'] in {'running', 'starting'} for job in board['jobs'].values()) >= MAX_ACTIVE:
                await self.store.put('board', board)
                raise HTTPException(429, 'Two jobs are already running. Wait briefly and try again.')
            recent = board['rates'].setdefault(session['address'], [])
            if len(recent) >= MAX_PER_ADDRESS:
                raise HTTPException(429, 'Too many jobs from this address. Try again in ten minutes.')
            if board['daily'] >= MAX_DAILY:
                raise HTTPException(429, 'The daily execution allowance has been reached. Try tomorrow (UTC).')
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
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-P2F-Token'])

    @api.get('/api/health')
    async def health():
        return {'ok': True, 'commit': service.commit, 'sandbox': 'gvisor', 'network': False,
                'compilers': list(service.compilers)}

    @api.get('/api/session')
    async def session(request: Request):
        # Use the ASGI peer supplied by the hosting platform; do not trust an
        # arbitrary user-supplied X-Forwarded-For header for rate limiting.
        return await service.session(request.client.host if request.client else 'unknown')

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
            if (not isinstance(mode, str) or mode not in MODES
                    or not isinstance(source, str) or (not source.strip() and mode not in {'fortran-edit', 'fortran-compile', 'fortran-run'}) or len(source.encode()) > MAX_SOURCE
                    or (mode in EDIT_MODES and (not isinstance(ft_source, str) or not ft_source.strip()
                        or len(ft_source.encode()) > MAX_SOURCE or payload.get('automatic', False)))
                    or not isinstance(payload.get('automatic', False), bool)
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
             'retain_executable', 'artifact_id') if key in payload
            and (key != 'fortran_source' or mode in EDIT_MODES)})

    @api.get('/api/jobs/{identifier}')
    async def job(identifier: str, request: Request):
        return await service.job(request.headers.get('x-p2f-token', ''), identifier)

    @api.post('/api/jobs/{identifier}/cancel')
    async def cancel(identifier: str, request: Request):
        return await service.job(request.headers.get('x-p2f-token', ''), identifier, cancel=True)

    return api
