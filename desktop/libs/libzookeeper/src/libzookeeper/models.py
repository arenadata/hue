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
import logging
import os

from kazoo.client import KazooClient

from hadoop import cluster
from libzookeeper.conf import ENSEMBLE, PRINCIPAL_NAME, SSL_CACERTS, SSL_CERT, SSL_ENABLED, SSL_KEY, SSL_VALIDATE


LOG = logging.getLogger()


class ReadOnlyClientException(Exception):
  pass


class ZookeeperConfigurationException(Exception):
  pass


def _get_zookeeper_sasl_options(require_hdfs=False):
  hdfs = cluster.get_hdfs()

  if hdfs is None and require_hdfs:
    raise ZookeeperConfigurationException('No [hdfs] configured in hue.ini.')

  principal_name = PRINCIPAL_NAME.get()
  security_enabled = hdfs is not None and hdfs.security_enabled
  if not require_hdfs:
    from desktop.conf import KERBEROS
    security_enabled = security_enabled or bool(principal_name and KERBEROS.HUE_KEYTAB.get())

  if security_enabled:
    return {'mechanism': 'GSSAPI', 'service': principal_name or 'zookeeper'}

  return None


def _get_zookeeper_ssl_options():
  if not SSL_ENABLED.get():
    return {}

  options = {
    'use_ssl': True,
    'verify_certs': SSL_VALIDATE.get(),
  }

  if SSL_CACERTS.get():
    options['ca'] = SSL_CACERTS.get()
  if SSL_CERT.get():
    options['certfile'] = SSL_CERT.get()
  if SSL_KEY.get():
    options['keyfile'] = SSL_KEY.get()

  return options


def get_kazoo_client_kwargs(hosts=None, read_only=True, require_hdfs=False):
  options = {
    'hosts': hosts if hosts else ENSEMBLE.get(),
    'read_only': read_only,
    'sasl_options': _get_zookeeper_sasl_options(require_hdfs=require_hdfs),
  }
  options.update(_get_zookeeper_ssl_options())
  return options


class ZookeeperClient(object):

  def __init__(self, hosts=None, read_only=True):
    self.hosts = hosts if hosts else ENSEMBLE.get()
    self.read_only = read_only

    self.zk = KazooClient(**get_kazoo_client_kwargs(hosts=self.hosts, read_only=self.read_only, require_hdfs=True))


  def start(self):
    """Start the zookeeper session."""
    self.zk.start()


  def stop(self):
    """Stop the zookeeper session, but leaves the socket open."""
    self.zk.stop()


  def close(self):
    """Closes a stopped zookeeper socket."""
    self.zk.close()


  def get_children_data(self, namespace):
    children = self.zk.get_children(namespace)

    children_data = []

    for node in children:
      data, stat = self.zk.get("%s/%s" % (namespace, node))
      children_data.append(data)

    return children_data


  def path_exists(self, namespace):
    return self.zk.exists(namespace) is not None


  def set(self, path, value, version=-1):
    return self.zk.set(path, value, version)


  def copy_path(self, namespace, filepath):
    if self.read_only:
      raise ReadOnlyClientException('Cannot execute copy_path when read_only is set to True.')

    self.zk.ensure_path(namespace)
    for dir, subdirs, files in os.walk(filepath):
      path = dir.replace(filepath, '').strip('/')
      if path:
        node_path = '%s/%s' % (namespace, path)
        self.zk.create(path=node_path, value='', makepath=True)
      for filename in files:
        node_path = '%s/%s/%s' % (namespace, path, filename)
        with open(os.path.join(dir, filename), 'r') as f:
          file_content = f.read()
          self.zk.create(path=node_path, value=file_content, makepath=True)


  def delete_path(self, namespace):
    if self.read_only:
      raise ReadOnlyClientException('Cannot execute delete_path when read_only is set to True.')

    self.zk.delete(namespace, recursive=True)


  def __enter__(self):
    """Start a zookeeper session and return a `with` context."""
    self.zk.start()
    return self


  def __exit__(self, exc_type, exc_value, traceback):
    """Stops and closes zookeeper session at the end of the `with` context."""
    try:
      self.stop()
    finally:
      self.close()
