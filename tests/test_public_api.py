"""Exercise the public API with a fake sandbox provider; never run user code."""
import copy
import base64
import json
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xpublic_api as public


class MemoryStore:
    def __init__(self):
        self.data = {}

    async def get(self, key, default):
        return copy.deepcopy(self.data.get(key, default))

    async def put(self, key, value):
        self.data[key] = copy.deepcopy(value)

    async def pop(self, key):
        self.data.pop(key, None)


class Sandboxes:
    def __init__(self):
        self.jobs = {}
        self.cancelled = []

    async def start(self, payload):
        identifier = str(len(self.jobs))
        self.jobs[identifier] = {'payload': payload, 'result': None}
        return identifier

    async def poll(self, identifier):
        return copy.deepcopy(self.jobs[identifier]['result'])

    async def cancel(self, identifier):
        self.cancelled.append(identifier)


class PublicTests(unittest.TestCase):
    def test_formatting_is_explicit_bounded_and_has_no_retained_binary(self):
        features = self.client.get('/api/session', headers=self.origin).json()['features']
        self.assertTrue(features['format'])
        for extras in ({'automatic': True}, {'retain_executable': True}, {'source': ''}):
            response = self.client.post('/api/jobs', json={
                'source': 'program main\nend', 'mode': 'format', **extras}, headers=self.headers)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.runner.jobs)
        response = self.client.post('/api/jobs', json={
            'source': 'program main\nend', 'mode': 'format'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        payload = self.runner.jobs['0']['payload']
        self.assertEqual(payload['mode'], 'format')
        self.assertNotIn('retain_executable', payload)

    def retained_build(self):
        payload = {'source': '', 'mode': 'fortran-compile', 'fortran_source': 'program main\nend',
                   'retain_executable': True, 'compiler_options': {'preset': 'debug'}}
        response = self.client.post('/api/jobs', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        sandbox = str(len(self.runner.jobs) - 1)
        self.runner.jobs[sandbox]['result'] = {'ok': True, 'build': {'ok': True},
            '_artifact': base64.b64encode(b'private executable').decode()}
        result = self.client.get('/api/jobs/' + response.json()['id'], headers=self.headers).json()['result']
        self.assertNotIn('_artifact', result)
        self.assertNotIn('private executable', json.dumps(result))
        return result['artifact']

    def test_compile_and_retained_run_ownership_expiry_and_payload(self):
        features = self.client.get('/api/session', headers=self.origin).json()['features']
        self.assertTrue(features['compile_only'])
        artifact = self.retained_build()
        payload = {'mode': 'fortran-run', 'artifact_id': artifact['id'], 'executable': 'forged', 'compiler': 'ifx'}
        other = self.session()
        self.assertEqual(self.client.post('/api/jobs', json=payload, headers=other).status_code, 404)
        response = self.client.post('/api/jobs', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        sent = self.runner.jobs['1']['payload']
        self.assertEqual(base64.b64decode(sent['executable']), b'private executable')
        self.assertEqual(sent['compiler'], 'gfortran')
        self.assertEqual(sent['compiler_options'], {'preset': 'debug'})
        self.assertEqual(self.store.data['board']['daily'], 2)
        self.now += public.ARTIFACT_TTL + 1
        self.assertEqual(self.client.post('/api/jobs', json=payload, headers=self.headers).status_code, 404)
        self.assertNotIn('artifact:' + artifact['id'], self.store.data)

    def test_retained_build_replacement_and_runtime_invalidation(self):
        first = self.retained_build()
        second = self.retained_build()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(self.store.data['board']['artifacts']), 1)
        self.assertNotIn('artifact:' + first['id'], self.store.data)
        self.service.runtime_namespace = 'new-image'
        response = self.client.post('/api/jobs', json={'mode': 'fortran-run', 'artifact_id': second['id']}, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_retained_request_validation_and_private_blob_stripping(self):
        for payload in ({'mode': []}, {'mode': {}}, {'mode': 'fortran-run'}, {'mode': 'fortran-run', 'artifact_id': []},
                        {'mode': 'python', 'source': 'print(1)', 'retain_executable': True},
                        {'mode': 'fortran-compile', 'fortran_source': 'end', 'retain_executable': 'yes'}):
            self.assertEqual(self.client.post('/api/jobs', json=payload, headers=self.headers).status_code, 400)
        response = self.submit()
        self.runner.jobs['0']['result'] = {'ok': True, '_artifact': 'not for the browser'}
        result = self.client.get('/api/jobs/' + response.json()['id'], headers=self.headers).json()['result']
        self.assertNotIn('_artifact', result)
        self.assertNotIn('artifact', result)

    def test_invalid_and_failed_builds_are_not_retained(self):
        for blob, build_ok in (('invalid base64', True), ('', True),
                               (base64.b64encode(b'exe').decode(), False)):
            response = self.client.post('/api/jobs', json={'mode': 'fortran-compile',
                'fortran_source': 'end', 'retain_executable': True}, headers=self.headers)
            self.assertEqual(response.status_code, 202, response.text)
            sandbox = str(len(self.runner.jobs) - 1)
            self.runner.jobs[sandbox]['result'] = {'ok': build_ok, 'build': {'ok': build_ok}, '_artifact': blob}
            result = self.client.get('/api/jobs/' + response.json()['id'], headers=self.headers).json()['result']
            self.assertNotIn('artifact', result)
            self.assertNotIn('_artifact', result)
        self.assertFalse(self.store.data['board']['artifacts'])

    def setUp(self):
        self.store, self.runner = MemoryStore(), Sandboxes()
        self.now = 1_700_000_000
        self.service = public.PublicService(self.store, self.runner, 'commit', lambda: self.now)
        self.client = TestClient(public.create_api(self.service))
        self.origin = {'Origin': 'https://beliavsky.github.io'}
        self.headers = self.session()

    def session(self):
        response = self.client.get('/api/session', headers=self.origin)
        self.assertEqual(response.status_code, 200, response.text)
        return {**self.origin, 'X-P2F-Token': response.json()['token']}

    def submit(self, headers=None):
        return self.client.post('/api/jobs', json={'source': 'print(1)', 'mode': 'python'}, headers=headers or self.headers)

    def test_origin_cors_and_payload_validation(self):
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertEqual(self.client.get('/api/session').status_code, 403)
        self.assertEqual(self.client.get('/api/session', headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        response = self.client.options('/api/jobs', headers={**self.origin,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-p2f-token'})
        self.assertEqual(response.headers['access-control-allow-origin'], self.origin['Origin'])
        self.assertEqual(self.client.post('/api/jobs', json={'source': 'x', 'mode': 'python'}, headers=self.origin).status_code, 403)
        for payload in ([], {'source': 'x', 'mode': []}, {'source': '\ud800', 'mode': 'python'}, {'source': 'x' * 100001, 'mode': 'python'}, {'source': 'x', 'mode': 'python', 'automatic': 'yes'}):
            self.assertEqual(self.client.post('/api/jobs', content=json.dumps(payload), headers={**self.headers, 'Content-Type': 'application/json'}).status_code, 400)
        self.assertEqual(self.client.post('/api/jobs', content='x' * (public.MAX_REQUEST + 1), headers={**self.headers, 'Content-Type': 'application/json'}).status_code, 413)
        self.assertFalse(self.runner.jobs)

    def test_session_versions_are_cached_metadata_and_filter_unavailable_compilers(self):
        self.service.compiler_versions = {'gfortran': 'GNU Fortran (GCC) 15.2.0', 'ifx': 'Intel test'}
        for _ in range(2):
            result = self.client.get('/api/session', headers=self.origin).json()
            self.assertEqual(result['compiler_versions'], {'gfortran': 'GNU Fortran (GCC) 15.2.0'})
        self.assertFalse(self.runner.jobs)
        self.service.compiler_versions = {}
        result = self.client.get('/api/session', headers=self.origin).json()
        self.assertEqual(result['compiler_versions'], {'gfortran': None})

    def test_compiler_allowlist_and_unavailable_intel_do_not_start_jobs(self):
        self.assertEqual(self.client.get('/api/health').json()['compilers'], ['gfortran'])
        for choice in ('gcc', 'ifx -O3', 'flang -O3', 'lfortran --fast', 'gfortran; echo bad', ['ifx'], None):
            response = self.client.post('/api/jobs', json={'source': 'print(1)',
                'mode': 'fortran', 'compiler': choice}, headers=self.headers)
            self.assertEqual(response.status_code, 400, response.text)
        for choice in ('ifx', 'flang', 'lfortran'):
            response = self.client.post('/api/jobs', json={'source': 'print(1)',
                'mode': 'fortran', 'compiler': choice}, headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertIn('no automatic fallback', response.json()['error'])
        self.assertFalse(self.runner.jobs)
        self.assertEqual(self.store.data['board']['daily'], 0)

    def test_intel_choice_forwarded_when_enabled(self):
        self.service.compilers = ('gfortran', 'ifx')
        session = self.client.get('/api/session', headers=self.origin).json()
        self.assertEqual(session['compilers'], ['gfortran', 'ifx'])
        response = self.client.post('/api/jobs', json={'source': 'print(1)',
            'mode': 'compare', 'compiler': 'ifx'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['compiler'], 'ifx')

    def test_options_advertised_validated_and_forwarded(self):
        catalog = self.client.get('/api/session', headers=self.origin).json()['compiler_options']
        self.assertIn('debug', catalog['gfortran']['presets'])
        self.assertNotIn('debug', catalog['lfortran']['presets'])
        for selection in ('-O3', [], {'preset': ['debug']}, {'flags': '-O3'},
                          {'preset': 'garbage'}, {'fast_math': 'yes'}):
            response = self.client.post('/api/jobs', json={'source': 'print(1)',
                'mode': 'compare', 'compiler_options': selection}, headers=self.headers)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.runner.jobs)
        self.assertEqual(self.store.data['board']['daily'], 0)
        selection = {'preset': 'debug', 'warnings': True, 'fast_math': False}
        response = self.client.post('/api/jobs', json={'source': 'print(1)',
            'mode': 'compare', 'compiler_options': selection}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['compiler_options'], selection)

    def test_standard_capabilities_are_verified_and_rejected_before_job_creation(self):
        self.service.compiler_standards = {'gfortran': {'2008': ['-std=f2008'], '2023': ['forged-flag']}}
        catalog = self.client.get('/api/session', headers=self.origin).json()['compiler_options']
        self.assertEqual(catalog['gfortran']['standards'], {'2008': ['-std=f2008']})
        for standard in ('2018', '2023', '2008 -O3', 2008, [], None):
            response = self.client.post('/api/jobs', json={'source': '', 'mode': 'fortran-compile',
                'fortran_source': 'program main\nend program main\n',
                'compiler_options': {'standard': standard}}, headers=self.headers)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.runner.jobs)
        self.assertEqual(self.store.data['board']['daily'], 0)
        response = self.client.post('/api/jobs', json={'source': '', 'mode': 'fortran-compile',
            'fortran_source': 'program main\nend program main\n',
            'compiler_options': {'standard': '2008', 'preset': 'strict'}}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['compiler_options']['standard'], '2008')

    def test_translation_settings_and_annotation_mode(self):
        self.assertTrue(self.client.get('/api/session', headers=self.origin).json()['source_tools'])
        for selection in ('--compile', [], {'int_kind': []}, {'int_kind': 'real64'},
                          {'preserve_comments': 'yes'}, {'flags': '--module'}):
            response = self.client.post('/api/jobs', json={'source': 'print(1)',
                'mode': 'translate', 'translation_options': selection}, headers=self.headers)
            self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.runner.jobs)
        selection = {'int_kind': 'int64', 'preserve_comments': False}
        response = self.client.post('/api/jobs', json={'source': 'print(1)',
            'mode': 'translate', 'translation_options': selection}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['translation_options'], selection)
        response = self.client.post('/api/jobs', json={'source': 'def f(x): return x\nf(2)',
            'mode': 'annotate'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['1']['payload']['mode'], 'annotate')

    def test_edited_fortran_validation_and_forwarding(self):
        ft = 'program demo\nprint *, 42\nend program demo\n'
        invalid = [
            {'mode': 'fortran-edit'},
            {'mode': 'compare-edit', 'fortran_source': ft},
            {'mode': 'fortran-edit', 'fortran_source': ft, 'automatic': True},
            {'mode': 'fortran-edit', 'fortran_source': 'x' * 100001},
            {'mode': 'fortran-edit', 'fortran_source': '\ud800'},
            {'mode': 'fortran-edit', 'fortran_source': None},
        ]
        for payload in invalid:
            response = self.client.post('/api/jobs', content=json.dumps(payload),
                headers={**self.headers, 'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 400, response.text)
        unavailable = self.client.post('/api/jobs', json={'mode': 'fortran-edit',
            'fortran_source': ft, 'compiler': 'ifx'}, headers=self.headers)
        self.assertEqual(unavailable.status_code, 503)
        self.assertFalse(self.runner.jobs)
        self.assertEqual(self.store.data['board']['daily'], 0)
        for mode, source in [('fortran-edit', ''), ('compare-edit', 'print(42)')]:
            response = self.client.post('/api/jobs', json={'source': source, 'mode': mode,
                'fortran_source': ft}, headers=self.headers)
            self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['fortran_source'], ft)
        self.assertEqual(self.runner.jobs['0']['payload']['source'], '')

    def test_python_and_translation_work_without_intel(self):
        for mode in ('python', 'translate'):
            response = self.client.post('/api/jobs', json={'source': 'print(1)',
                'mode': mode, 'compiler': 'ifx'}, headers=self.headers)
            self.assertEqual(response.status_code, 202, response.text)

    def test_flang_choice_forwarded_only_when_enabled(self):
        self.service.compilers = ('gfortran', 'flang')
        self.assertEqual(self.client.get('/api/session', headers=self.origin).json()['compilers'],
                         ['gfortran', 'flang'])
        response = self.client.post('/api/jobs', json={'source': 'print(1)',
            'mode': 'compare', 'compiler': 'flang'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['compiler'], 'flang')

    def test_lfortran_choice_forwarded_only_when_enabled(self):
        self.service.compilers = ('gfortran', 'lfortran')
        self.assertEqual(self.client.get('/api/session', headers=self.origin).json()['compilers'],
                         ['gfortran', 'lfortran'])
        response = self.client.post('/api/jobs', json={'source': 'print(1)',
            'mode': 'compare', 'compiler': 'lfortran'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.runner.jobs['0']['payload']['compiler'], 'lfortran')

    def test_ownership_completion_and_cancellation(self):
        identifier = self.submit().json()['id']
        other = self.session()
        for method, path in (('get', f'/api/jobs/{identifier}'), ('post', f'/api/jobs/{identifier}/cancel')):
            response = getattr(self.client, method)(path, headers=other)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f'/api/jobs/{identifier}', headers=self.headers).json()['state'], 'running')
        self.runner.jobs['0']['result'] = {'ok': True, 'seconds': 1}
        response = self.client.get(f'/api/jobs/{identifier}', headers=self.headers).json()
        self.assertEqual(response['result']['commit'], 'commit')
        second = self.submit().json()['id']
        self.assertEqual(self.client.post(f'/api/jobs/{second}/cancel', headers=self.headers).status_code, 200)
        self.assertEqual(self.runner.cancelled, ['1'])

    def test_concurrency_limits_survive_service_restart(self):
        self.assertEqual(self.submit().status_code, 202)
        self.assertEqual(self.submit().status_code, 202)
        restarted = public.PublicService(self.store, self.runner, 'commit', lambda: self.now)
        with TestClient(public.create_api(restarted)) as client:
            response = client.post('/api/jobs', json={'source': 'x', 'mode': 'python'}, headers=self.headers)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(len(self.runner.jobs), 2)

    def test_daily_allowance_cannot_be_bypassed_with_new_sessions(self):
        self.store.data['board']['day'] = '2023-11-14'
        self.store.data['board']['daily'] = public.MAX_DAILY
        self.assertEqual(self.submit(self.session()).status_code, 429)
        self.assertFalse(self.runner.jobs)
        self.now += 86400
        self.headers = self.session()
        self.assertEqual(self.submit().status_code, 202)

    def test_address_allowance_shared_between_sessions_and_expires(self):
        board = self.store.data['board']
        address = next(iter(board['sessions'].values()))['address']
        board['rates'][address] = [self.now] * public.MAX_PER_ADDRESS
        self.assertEqual(self.submit(self.session()).status_code, 429)
        self.now += 601
        self.assertEqual(self.submit().status_code, 202)

    def test_session_expiry(self):
        self.now += 3601
        self.assertEqual(self.submit().status_code, 403)

    def test_provisioning_failure_logged_and_slot_released(self):
        async def failure(_payload):
            raise FileNotFoundError('missing build source')
        self.runner.start = failure
        with self.assertLogs('xpublic_api', level='ERROR') as logs:
            response = self.submit()
        self.assertEqual(response.status_code, 503)
        self.assertIn('missing build source', '\n'.join(logs.output))
        self.assertNotIn('Try Reconnect', response.json()['error'])
        self.assertEqual(self.store.data['board']['daily'], 1)
        self.assertTrue(all(job['state'] == 'done' for job in self.store.data['board']['jobs'].values()))


if __name__ == '__main__':
    unittest.main()
