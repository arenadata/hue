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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import MagicMock, patch

import pytest

from desktop.lib.rest.http_client import RestException
from zookeeper.rest import ZooKeeper, ZooKeeperHttpClient


def _rest_exception(code):
  error = MagicMock()
  error.response.status_code = code
  error.response.headers = {}
  error.response.text = 'error %d' % code
  return RestException(error)


def _make_zk(**kwargs):
  with patch('zookeeper.rest.ZooKeeperHttpClient') as client_class:
    zk = ZooKeeper('http://zk.example:9998', **kwargs)
    return zk, client_class


class TestAuthWiring(object):

  def test_no_kerberos_by_default(self):
    with patch('zookeeper.rest.ZooKeeperHttpClient') as client_class:
      ZooKeeper('http://zk.example:9998')
      client_class.return_value.set_kerberos_auth.assert_not_called()

  def test_kerberos_enabled_sets_spnego_auth(self):
    with patch('zookeeper.rest.ZooKeeperHttpClient') as client_class:
      ZooKeeper('http://zk.example:9998', security_enabled=True)
      client_class.return_value.set_kerberos_auth.assert_called_once_with()

  def test_ssl_verify_passed_through(self):
    with patch('zookeeper.rest.ZooKeeperHttpClient') as client_class:
      ZooKeeper('http://zk.example:9998', ssl_cert_ca_verify=True)
      client_class.return_value.set_verify.assert_called_once_with(True)
      client_class.return_value.set_kerberos_auth.assert_not_called()


class TestUrlBuilding(object):

  def test_root_znode_keeps_trailing_slash(self):
    zk, client_class = _make_zk()
    zk.get('/')
    client_class.return_value.execute.assert_called_once_with(
        'GET', 'znodes/v1/', params=None, headers={'Accept': 'application/json'})

  def test_get_quotes_path(self):
    zk, client_class = _make_zk()
    zk.get('/parent/child name')
    assert client_class.return_value.execute.call_args[0][1] == 'znodes/v1/parent/child name'

  def test_children_view(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {
        'children': ['a', 'b'],
        'child_uri_template': 'http://zk.example:9998/znodes/v1/parent/{child}',
    }
    assert list(zk.get_children_paths('/parent')) == ['a', 'b']
    client_class.return_value.execute.assert_called_once_with(
        'GET', 'znodes/v1/parent', params={'view': 'children'},
        headers={'Accept': 'application/json'})

  def test_create_session_url(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {'id': '123'}
    assert zk.start_session(expire=5) == '123'
    client_class.return_value.execute.assert_called_once_with(
        'POST', 'sessions/v1/', params={'op': 'create', 'expire': 5}, data=None,
        headers={'Accept': 'application/json', 'Content-Type': 'application/octet-stream'})

  def test_create_flags(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {'Path': '/parent/node'}
    zk.create('/parent/node', data='hello')
    client_class.return_value.execute.assert_called_once_with(
        'POST', 'znodes/v1/parent', params={
            'op': 'create', 'name': 'node', 'null': 'false',
            'ephemeral': 'false', 'sequence': 'false'},
        data='hello',
        headers={'Accept': 'application/json', 'Content-Type': 'application/octet-stream'})

  def test_create_root_level_keeps_trailing_slash(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {'Path': '/node'}
    zk.create('/node')
    client_class.return_value.execute.assert_called_once_with(
        'POST', 'znodes/v1/', params={
            'op': 'create', 'name': 'node', 'null': 'true',
            'ephemeral': 'false', 'sequence': 'false'},
        data=None,
        headers={'Accept': 'application/json', 'Content-Type': 'application/octet-stream'})

  def test_create_ephemeral_requires_session(self):
    zk, _client_class = _make_zk()
    with pytest.raises(ZooKeeper.Error):
      zk.create('/parent/node', ephemeral=True)


class TestErrorMapping(object):

  def test_get_404_raises_not_found(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(404)
    with pytest.raises(ZooKeeper.NotFound):
      zk.get('/missing')

  def test_create_409_raises_znode_exists(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(409)
    with pytest.raises(ZooKeeper.ZNodeExists):
      zk.create('/parent/exists')

  def test_set_412_raises_wrong_version(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(412)
    with pytest.raises(ZooKeeper.WrongVersion):
      zk.set('/parent/node', 'x', version=1)

  def test_delete_412_raises_wrong_version(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(412)
    with pytest.raises(ZooKeeper.WrongVersion):
      zk.delete('/parent/node', version=1)

  def test_post_401_raises_invalid_session(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(401)
    with pytest.raises(ZooKeeper.InvalidSession):
      zk.create('/parent/node')

  def test_get_500_reraises_rest_exception(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.side_effect = _rest_exception(500)
    with pytest.raises(RestException):
      zk.get('/parent/node')


class TestResponseParsing(object):

  def test_get_returns_json_dict(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {'path': '/parent'}
    assert zk.get('/parent') == {'path': '/parent'}

  def test_error_body_raises_zookeeper_error(self):
    zk, client_class = _make_zk()
    client_class.return_value.execute.return_value.json.return_value = {'Error': 'bad node'}
    with pytest.raises(ZooKeeper.Error):
      zk.get('/parent')


class TestClientMakeUrl(object):

  def test_preserves_trailing_slash(self):
    client = ZooKeeperHttpClient('http://zk.example:9998')
    assert client._make_url('znodes/v1/', None) == 'http://zk.example:9998/znodes/v1/'

  def test_appends_params(self):
    client = ZooKeeperHttpClient('http://zk.example:9998')
    assert client._make_url('znodes/v1/', {'view': 'children'}) == \
        'http://zk.example:9998/znodes/v1/?view=children'
