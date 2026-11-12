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


import json
from builtins import object
from unittest.mock import patch

from django.test import RequestFactory

from zookeeper import stats, views
from zookeeper.conf import CLUSTERS
from zookeeper.rest import ZooKeeper
from zookeeper.views import _get_global_overview, _group_stats_by_role


class MockZooKeeperStats(object):

  calls = []

  def __init__(self, host, port, **kwargs):
    MockZooKeeperStats.calls.append(kwargs)

  def get_stats(self):
    return {}


class ZooKeeperMockBase(object):

  def setup_method(self):
    # Beware: Monkey patch ZooKeeper with Mock API
    if not hasattr(stats, 'OriginalZooKeeperApi'):
      stats.OriginalZooKeeperApi = stats.ZooKeeperStats

    stats.ZooKeeperStats = MockZooKeeperStats
    MockZooKeeperStats.calls = []

  def teardown_method(self):
    stats.ZooKeeperStats = stats.OriginalZooKeeperApi


class TestMockedZooKeeper(ZooKeeperMockBase):

  def test_get_global_overview(self):
    """Beware: this test is not testing, need to better mock the config."""
    finish = CLUSTERS.set_for_testing({'default': {'localhost:2181': {}}})

    try:
      _get_global_overview()

    finally:
      finish()

    finish = CLUSTERS.set_for_testing({'default': {'localhost:2181,localhost:2182': {}}})
    try:
      _get_global_overview()
    finally:
      finish()

  def test_cluster_options_reach_stats_client(self):
    finish = CLUSTERS.set_for_testing({'default': {
        'host_ports': 'zk1.example:2181,zk2.example:2181',
        'admin_port': 8080,
        'security_enabled': True,
    }})

    try:
      _get_global_overview()

    finally:
      finish()

    assert MockZooKeeperStats.calls == [
        {'admin_port': 8080, 'security_enabled': True, 'ssl_cert_ca_verify': False},
        {'admin_port': 8080, 'security_enabled': True, 'ssl_cert_ca_verify': False},
    ]

  def test_group_stats_by_role_reads_prefixed_admin_keys(self):
    overview = {
        'zk1.example:2181': {'zk_server_state': 'leader'},
        'zk2.example:2181': {'zk_server_state': 'follower'},
    }
    leader, followers = _group_stats_by_role(overview)
    assert leader['host'] == 'zk1.example:2181'
    assert [follower['host'] for follower in followers] == ['zk2.example:2181']


class TestCreateZNode(object):

  def _create(self, data):
    request = RequestFactory().post(
        '/zookeeper/create/default//',
        data=data,
        HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    )
    request.user = type('User', (), {'username': 'admin'})()

    with patch.object(views, 'is_admin', return_value=True), \
         patch.object(views, 'get_cluster_or_404', return_value={}), \
         patch.object(views, 'get_client') as get_client:
      response = views.create(request, 'default', '/')

    return response, get_client.return_value

  def test_create_ajax_returns_redirect_to_parent_tree(self):
    response, zk = self._create({'name': 'testnode', 'data': 'hello'})

    assert response.status_code == 200
    assert json.loads(response.content) == {'redirect': '/zookeeper/tree/default//'}
    zk.create.assert_called_once_with('/testnode', 'hello', sequence=False)

  def test_create_ajax_returns_form_errors(self):
    response, zk = self._create({'name': '', 'data': ''})

    assert response.status_code == 400
    assert 'error' in json.loads(response.content)
    zk.create.assert_not_called()

  def test_create_ajax_returns_conflict_for_existing_znode(self):
    request = RequestFactory().post(
        '/zookeeper/create/default//',
        data={'name': 'testnode', 'data': 'hello'},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    )
    request.user = type('User', (), {'username': 'admin'})()

    with patch.object(views, 'is_admin', return_value=True), \
         patch.object(views, 'get_cluster_or_404', return_value={}), \
         patch.object(views, 'get_client') as get_client:
      get_client.return_value.create.side_effect = ZooKeeper.ZNodeExists('/testnode')
      response = views.create(request, 'default', '/')

    assert response.status_code == 409
    assert 'error' in json.loads(response.content)


class TestDeleteZNode(object):

  def _delete(self, path):
    request = RequestFactory().post('/zookeeper/delete/default/%s' % path)
    request.user = None

    with patch.object(views, 'is_admin', return_value=True), \
         patch.object(views, 'get_cluster_or_404', return_value={}), \
         patch.object(views, 'get_client') as get_client:
      response = views.delete(request, 'default', path)

    get_client.return_value.recursive_delete.assert_called_once_with(path)
    return json.loads(response.content)

  def test_delete_top_level_znode_without_leading_slash_redirects_to_root(self):
    assert self._delete('hue') == {'redirect': '/zookeeper/tree/default//'}

  def test_delete_nested_znode_redirects_to_parent(self):
    assert self._delete('hue/services/zookeeper') == {'redirect': '/zookeeper/tree/default/hue/services'}
