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

from builtins import object
import os
import pytest
import shutil
import tempfile
from unittest.mock import Mock, patch

from desktop.lib.django_test_util import make_logged_in_client
from desktop.lib.test_utils import add_to_group, grant_access
from hadoop.pseudo_hdfs4 import is_live_cluster
from useradmin.models import User

from libzookeeper import conf as libzookeeper_conf
from libzookeeper.models import ZookeeperClient
from libzookeeper.conf import zkensemble, ENSEMBLE


class UnitTests(object):

  def test_get_ensemble(self):
    clear = ENSEMBLE.set_for_testing('zoo:2181')
    try:
      assert 'zoo:2181' == ENSEMBLE.get()
    finally:
      clear()

    clear = ENSEMBLE.set_for_testing('zoo:2181,zoo2:2181')
    try:
      assert 'zoo:2181,zoo2:2181' == ENSEMBLE.get()
    finally:
      clear()

    clear = ENSEMBLE.set_for_testing(['zoo:2181', 'zoo2:2181'])
    try:
      assert 'zoo:2181,zoo2:2181' == ENSEMBLE.get()
    finally:
      clear()

  def test_get_kazoo_client_kwargs_uses_sasl_options_for_secure_hdfs(self):
    from libzookeeper import models

    reset = libzookeeper_conf.PRINCIPAL_NAME.set_for_testing('zookeeper')
    try:
      with patch('libzookeeper.models.cluster.get_hdfs', return_value=Mock(security_enabled=True)):
        kwargs = models.get_kazoo_client_kwargs(hosts='zk1.example.com:2181', read_only=True)
    finally:
      reset()

    assert kwargs['hosts'] == 'zk1.example.com:2181'
    assert kwargs['read_only'] is True
    assert kwargs['sasl_options'] == {'mechanism': 'GSSAPI', 'service': 'zookeeper'}
    assert 'sasl_server_principal' not in kwargs

  def test_get_kazoo_client_kwargs_uses_sasl_options_for_kerberized_hue_without_hdfs(self):
    from libzookeeper import models

    reset = libzookeeper_conf.PRINCIPAL_NAME.set_for_testing('zookeeper')
    try:
      with patch('libzookeeper.models.cluster.get_hdfs', return_value=None):
        with patch('desktop.conf.KERBEROS.HUE_KEYTAB.get', return_value='/etc/security/keytabs/hue.service.keytab'):
          kwargs = models.get_kazoo_client_kwargs(hosts='zk1.example.com:2181', read_only=True)
    finally:
      reset()

    assert kwargs['sasl_options'] == {'mechanism': 'GSSAPI', 'service': 'zookeeper'}

  def test_get_kazoo_client_kwargs_does_not_use_sasl_without_kerberos_or_hdfs(self):
    from libzookeeper import models

    with patch('libzookeeper.models.cluster.get_hdfs', return_value=None):
      with patch('desktop.conf.KERBEROS.HUE_KEYTAB.get', return_value=''):
        kwargs = models.get_kazoo_client_kwargs(hosts='zk1.example.com:2181', read_only=True)

    assert kwargs['sasl_options'] is None

  def test_get_kazoo_client_kwargs_does_not_use_sasl_without_zookeeper_principal(self):
    from libzookeeper import models

    reset = libzookeeper_conf.PRINCIPAL_NAME.set_for_testing('')
    try:
      with patch('libzookeeper.models.cluster.get_hdfs', return_value=None):
        with patch('desktop.conf.KERBEROS.HUE_KEYTAB.get', return_value='/etc/security/keytabs/hue.service.keytab'):
          kwargs = models.get_kazoo_client_kwargs(hosts='zk1.example.com:2181', read_only=True)
    finally:
      reset()

    assert kwargs['sasl_options'] is None

  def test_zookeeper_client_still_requires_hdfs_configuration(self):
    from libzookeeper import models

    with patch('libzookeeper.models.cluster.get_hdfs', return_value=None):
      with patch('libzookeeper.models.KazooClient') as KazooClient:
        with pytest.raises(models.ZookeeperConfigurationException, match=r'No \[hdfs\] configured in hue.ini.'):
          models.ZookeeperClient()

    KazooClient.assert_not_called()

  def test_get_kazoo_client_kwargs_adds_ssl_options(self):
    from libzookeeper import models

    resets = [
      libzookeeper_conf.SSL_ENABLED.set_for_testing(True),
      libzookeeper_conf.SSL_CACERTS.set_for_testing('/etc/hue/ca.pem'),
      libzookeeper_conf.SSL_CERT.set_for_testing('/etc/hue/client.pem'),
      libzookeeper_conf.SSL_KEY.set_for_testing('/etc/hue/client.key'),
      libzookeeper_conf.SSL_VALIDATE.set_for_testing(False),
    ]
    try:
      with patch('libzookeeper.models.cluster.get_hdfs', return_value=Mock(security_enabled=False)):
        with patch('desktop.conf.KERBEROS.HUE_KEYTAB.get', return_value=''):
          kwargs = models.get_kazoo_client_kwargs(hosts='zk1.example.com:2281', read_only=False)
    finally:
      for reset in resets:
        reset()

    assert kwargs['hosts'] == 'zk1.example.com:2281'
    assert kwargs['read_only'] is False
    assert kwargs['sasl_options'] is None
    assert kwargs['use_ssl'] is True
    assert kwargs['ca'] == '/etc/hue/ca.pem'
    assert kwargs['certfile'] == '/etc/hue/client.pem'
    assert kwargs['keyfile'] == '/etc/hue/client.key'
    assert kwargs['verify_certs'] is False


@pytest.mark.requires_hadoop
@pytest.mark.integration
class TestWithZooKeeper(object):

  @classmethod
  def setup_class(cls):

    if not is_live_cluster():
      pytest.skip("Skipping Test")

    cls.client = make_logged_in_client(username='test', is_superuser=False)
    cls.user = User.objects.get(username='test')
    add_to_group('test')
    grant_access("test", "test", "libzookeeper")

    # Create a ZKNode namespace
    cls.namespace = 'TestWithZooKeeper'

    # Create temporary test directory and file with contents
    cls.local_directory = tempfile.mkdtemp()
    # Create subdirectory
    cls.subdir_name = 'subdir'
    subdir_path = '%s/%s' % (cls.local_directory, cls.subdir_name)
    os.mkdir(subdir_path, 0o755)
    # Create file
    cls.filename = 'test.txt'
    file_path = '%s/%s' % (subdir_path, cls.filename)
    cls.file_contents = "This is a test"
    file = open(file_path, 'w+')
    file.write(cls.file_contents)
    file.close()

  @classmethod
  def teardown_class(cls):
    # Don't want directories laying around
    shutil.rmtree(cls.local_directory)

  def teardown_method(self):
    with ZookeeperClient(hosts=zkensemble(), read_only=False) as client:
      if client.zk.exists(self.namespace):
        client.zk.delete(self.namespace, recursive=True)

  def test_get_children_data(self):
    root_node = '%s/%s' % (TestWithZooKeeper.namespace, 'test_path_exists')

    with ZookeeperClient(hosts=zkensemble(), read_only=False) as client:
      client.zk.create(root_node, value='test_path_exists', makepath=True)

      db = client.get_children_data(namespace=TestWithZooKeeper.namespace)
      assert len(db) > 0

  def test_path_exists(self):
    root_node = '%s/%s' % (TestWithZooKeeper.namespace, 'test_path_exists')

    with ZookeeperClient(hosts=zkensemble(), read_only=False) as client:
      client.zk.create(root_node, value='test_path_exists', makepath=True)

      try:
        assert client.path_exists(namespace=root_node)
        assert not client.path_exists(namespace='bogus_path')
      finally:
        client.delete_path(root_node)

  def test_copy_and_delete_path(self):
    root_node = '%s/%s' % (TestWithZooKeeper.namespace, 'test_copy_and_delete_path')

    with ZookeeperClient(hosts=zkensemble(), read_only=False) as client:
      # Test copy_path
      client.copy_path(root_node, TestWithZooKeeper.local_directory)

      assert client.zk.exists('%s' % root_node)
      assert client.zk.exists('%s/%s' % (root_node, TestWithZooKeeper.subdir_name))
      assert client.zk.exists('%s/%s/%s' % (root_node, TestWithZooKeeper.subdir_name, TestWithZooKeeper.filename))
      contents, stats = client.zk.get('%s/%s/%s' % (root_node, TestWithZooKeeper.subdir_name, TestWithZooKeeper.filename))
      assert contents == TestWithZooKeeper.file_contents

      # Test delete_path
      client.delete_path(root_node)

      assert client.zk.exists('%s' % root_node) == None
      assert client.zk.exists('%s/%s' % (root_node, TestWithZooKeeper.subdir_name)) == None
      assert client.zk.exists('%s/%s/%s' % (root_node, TestWithZooKeeper.subdir_name, TestWithZooKeeper.filename)) == None
