"""Explicit proxy routing preserves SEC-only targets and ordinary TLS transport."""
from copy import deepcopy
from argparse import Namespace
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request

from uteki.infrastructure.document_sources.company_acquisition import (
    AcquisitionError, _ExplicitProxy, _Redirect, _transport, _url, prepare_sources,
)
from tests.unit.test_acquisition_transport import AcquisitionTransportTests, Response
from uteki.infrastructure.research_data.agent_cli import run_agent_command


PROXY = {'mode': 'trusted_local_http_proxy', 'proxy_url': 'http://127.0.0.1:7897',
         'destination_hosts': ['data.sec.gov', 'www.sec.gov']}
MODULE = 'uteki.infrastructure.document_sources.company_acquisition'


class ExplicitProxyTests(unittest.TestCase):
    def test_proxy_requires_explicit_loopback_and_sec_only_destinations(self):
        self.assertEqual(_transport({'transport': PROXY}), PROXY)
        for url in ('http://localhost:7897', 'http://192.168.1.1:7897', 'http://198.18.0.1:7897',
                    'https://127.0.0.1:7897', 'http://user:pass@127.0.0.1:7897',
                    'http://127.0.0.1:7897/path', 'http://127.0.0.1', 'http://127.0.0.1:7897#x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _transport({'transport': {**PROXY, 'proxy_url': url}})
        for hosts in (['localhost'], ['198.18.0.1'], ['www.sec.gov.evil.test'], ['*.sec.gov'], []):
            with self.subTest(hosts=hosts), self.assertRaises(ValueError):
                _transport({'transport': {**PROXY, 'destination_hosts': hosts}})

    def test_default_transport_still_rejects_fake_or_private_dns(self):
        with patch(MODULE+'.socket.getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('198.18.0.10', 443))]):
            with self.assertRaisesRegex(AcquisitionError, 'non-public DNS'):
                _url('https://data.sec.gov/submissions/a.json', {'data.sec.gov'}, resolve=True)

    def test_proxy_redirect_cannot_escape_allowed_hostname_or_https(self):
        redirect = _Redirect({'data.sec.gov', 'www.sec.gov'}, resolve=False)
        request = urllib.request.Request('https://data.sec.gov/submissions/a.json')
        with patch(MODULE+'.socket.getaddrinfo', side_effect=AssertionError('proxy owns DNS')):
            accepted = redirect.redirect_request(request, None, 302, '', {}, 'https://www.sec.gov/a')
            self.assertEqual(accepted.full_url, 'https://www.sec.gov/a')
            for target in ('http://www.sec.gov/a', 'https://127.0.0.1/a', 'https://198.18.0.10/a',
                           'https://www.sec.gov.evil.test/a', 'https://user@www.sec.gov/a'):
                with self.subTest(target=target), self.assertRaises(AcquisitionError):
                    redirect.redirect_request(request, None, 302, '', {}, target)

    def test_no_proxy_environment_does_not_disable_explicit_connect(self):
        request = urllib.request.Request('https://data.sec.gov/submissions/a.json')
        handler = _ExplicitProxy({'https': PROXY['proxy_url']})
        with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*'}):
            handler.proxy_open(request, PROXY['proxy_url'], 'https')
        self.assertEqual(request.host, '127.0.0.1:7897')
        self.assertEqual(request.type, 'https')
        self.assertEqual(request._tunnel_host, 'data.sec.gov')

    def test_redirect_cannot_add_another_sec_host_outside_explicit_subset(self):
        redirect = _Redirect({'data.sec.gov'}, resolve=False)
        request = urllib.request.Request('https://data.sec.gov/submissions/a.json')
        with self.assertRaises(AcquisitionError):
            redirect.redirect_request(request, None, 302, '', {}, 'https://www.sec.gov/a')

    def test_real_acquisition_path_selects_both_sec_requests_through_proxy(self):
        fixture = AcquisitionTransportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        config = deepcopy(fixture.config)
        config['transport'] = PROXY
        config_path = fixture.directory/'proxy-source-config.json'
        config_path.write_text(json.dumps(config))
        args = Namespace(agent_action='acquire', config=config_path, workspace=fixture.workspace,
                         sec_user_agent=config['sec_user_agent'])
        opener = Mock()
        opener.open.side_effect = [Response(fixture.metadata, fixture.submission_url),
                                   Response(fixture.raw, fixture.filing_url)]
        with patch(MODULE+'.urllib.request.build_opener', return_value=opener) as build, \
                patch(MODULE+'.socket.getaddrinfo', side_effect=AssertionError('proxy owns DNS')), \
                patch(MODULE+'.time.sleep'):
            result = run_agent_command(args)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['documents'][0]['transport']['transport'], 'trusted_local_http_proxy')
        self.assertEqual(result['scope']['transport'], PROXY)
        for invocation in build.call_args_list:
            self.assertIsInstance(invocation.args[0], _ExplicitProxy)
            self.assertIsInstance(invocation.args[1], _Redirect)
            self.assertFalse(invocation.args[1].resolve)

    def test_invalid_proxy_fails_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)/'must-not-exist'
            with self.assertRaises(ValueError):
                prepare_sources({'transport': {**PROXY, 'destination_hosts': ['example.test']}}, workspace)
            self.assertFalse(workspace.exists())


if __name__ == '__main__':
    unittest.main()
