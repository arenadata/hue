#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS"
# BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.  See the License for the specific language governing
# permissions and limitations under the License.

import logging
from unittest.mock import MagicMock, patch

import pytest

from desktop.lib.rest.http_client import RestException
from zookeeper.stats import Session, ZooKeeperStats


def _rest_exception(code):
  error = MagicMock()
  error.response.status_code = code
  error.response.headers = {}
  error.response.text = 'error %d' % code
  return RestException(error)


def _response(body):
  response = MagicMock()
  response.json.return_value = body
  return response


MNTR_BODY = {
    'command': 'mntr',
    'error': None,
    'version': '3.9.5-abc, built on 2026-01-01',
    'server_state': 'leader',
    'znode_count': 5,
    'avg_latency': 12,
}

STAT_BODY = {
    'command': 'stat',
    'error': None,
    'version': '3.9.5-abc, built on 2026-01-01',
    'node_count': 5,
    'server_stats': {
        'min_latency': 0,
        'avg_latency': 12.5,
        'max_latency': 130,
        'packets_received': 100,
        'packets_sent': 101,
        'outstanding_requests': 0,
        'server_state': 'follower',
    },
    'connections': [
        {
            'remote_socket_address': '10.0.0.1:52972',
            'interest_ops': 0,
            'outstanding_requests': 2,
            'packets_received': 10,
            'packets_sent': 11,
        },
        {
            'remote_socket_address': '10.0.0.2:4096',
            'interest_ops': 1,
            'outstanding_requests': 0,
            'packets_received': 700,
            'packets_sent': 701,
        },
    ],
}


class TestAdminWiring(object):

  def test_no_http_client_without_admin_port(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      ZooKeeperStats('zk1.example', '2181')
      client_class.assert_not_called()

  def test_admin_port_builds_http_url(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      assert client_class.call_args[0][0] == 'http://zk1.example:8080'
      assert isinstance(client_class.call_args[1].get('logger'), logging.Logger)

  def test_admin_kerberos_enabled(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      ZooKeeperStats('zk1.example', '2181', admin_port=8080, security_enabled=True)
      client_class.return_value.set_kerberos_auth.assert_called_once_with()

  def test_admin_kerberos_disabled_by_default(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.set_kerberos_auth.assert_not_called()

  def test_admin_ssl_verify_passed_through(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      ZooKeeperStats('zk1.example', '2181', admin_port=8080, ssl_cert_ca_verify=True)
      client_class.return_value.set_verify.assert_called_once_with(True)


class TestAdminGetStats(object):

  def test_mntr_prefixes_keys_and_times_out(self):
    # The admin server serves mntr keys unprefixed (the 4lw writer adds zk_
    # only to its text output); Hue's UI reads the zk_* names.
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.return_value = _response(MNTR_BODY)
      assert zks.get_stats() == {
          'zk_version': '3.9.5-abc, built on 2026-01-01',
          'zk_server_state': 'leader',
          'zk_znode_count': 5,
          'zk_avg_latency': 12,
      }
      client_class.return_value.execute.assert_called_once_with(
          'GET', 'commands/mntr', headers={'Accept': 'application/json'}, timeout=5)

  def test_mntr_error_falls_back_to_stat(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = [
          _response({'command': 'mntr', 'error': 'This ZooKeeper instance is not currently serving requests'}),
          _response(STAT_BODY),
      ]
      stats = zks.get_stats()
      assert stats['zk_server_state'] == 'follower'
      assert stats['zk_version'] == '3.9.5-abc, built on 2026-01-01'
      assert [call[0][1] for call in client_class.return_value.execute.call_args_list] == \
          ['commands/mntr', 'commands/stat']

  def test_mntr_not_allowed_falls_back_to_stat(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = [_rest_exception(403), _response(STAT_BODY)]
      assert zks.get_stats()['zk_server_state'] == 'follower'

  def test_stat_json_maps_keys(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = [
          _response({'command': 'mntr', 'error': 'not serving'}),
          _response(STAT_BODY),
      ]
      assert zks.get_stats() == {
          'zk_version': '3.9.5-abc, built on 2026-01-01',
          'zk_min_latency': 0,
          'zk_avg_latency': 12.5,
          'zk_max_latency': 130,
          'zk_packets_received': 100,
          'zk_packets_sent': 101,
          'zk_outstanding_requests': 0,
          'zk_server_state': 'follower',
          'zk_znode_count': 5,
      }

  def test_all_commands_failed_returns_empty(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = _rest_exception(500)
      assert zks.get_stats() == {}

  def test_non_json_response_degrades_to_empty(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      response = MagicMock()
      response.json.side_effect = ValueError('not json')
      client_class.return_value.execute.return_value = response
      assert zks.get_stats() == {}
      assert zks.get_clients() == []


class TestAdminGetClients(object):

  def test_stat_connections_mapped_to_sessions(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.return_value = _response(STAT_BODY)
      clients = zks.get_clients()
      assert len(clients) == 2
      assert clients[0].host == '10.0.0.1'
      assert clients[0].port == '52972'
      assert clients[0].interest_ops == 0
      assert clients[0].queued == 2
      assert clients[0].recved == 10
      assert clients[0].sent == 11
      assert clients[1].host == '10.0.0.2'

  def test_stat_error_returns_no_clients(self):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = _rest_exception(401)
      assert zks.get_clients() == []


class TestAdminErrorLogging(object):

  def test_401_mentions_kerberos(self, caplog):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = _rest_exception(401)
      with caplog.at_level('ERROR'):
        zks.get_clients()
      assert 'Kerberos' in caplog.text

  def test_403_mentions_command_whitelist(self, caplog):
    with patch('zookeeper.stats.ZooKeeperHttpClient') as client_class:
      zks = ZooKeeperStats('zk1.example', '2181', admin_port=8080)
      client_class.return_value.execute.side_effect = _rest_exception(403)
      with caplog.at_level('ERROR'):
        zks.get_clients()
      assert 'admin.spnego.commands' in caplog.text


class TestSessionParsing(object):

  def test_parse_raw_stat_line(self):
    session = Session.parse('/10.0.0.1:52972[1](queued=0,recved=10,sent=11,sid=0x100,lop=NA,est=1,to=30000)')
    assert session.host == '10.0.0.1'
    assert session.port == '52972'
    assert session.interest_ops == '1'
    assert session.queued == '0'
    assert session.recved == '10'
    assert session.sent == '11'
    assert session.sid == '0x100'

  def test_parse_broken_line_raises(self):
    with pytest.raises(Session.BrokenLine):
      Session.parse('not a stat line')
