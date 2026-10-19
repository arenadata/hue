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

import logging
import urllib.parse
from builtins import map, object

from django.utils.encoding import iri_to_uri

from desktop.lib.rest.http_client import HttpClient, RestException

LOG = logging.getLogger()


class ZooKeeperHttpClient(HttpClient):
  """HttpClient variant that keeps the request path verbatim.

  The REST gateway routes are trailing-slash sensitive (znodes/v1{path: /.*},
  sessions/v1/{session: .*}) and HttpClient._make_url would normalize
  /znodes/v1/ into /znodes/v1, which the gateway rejects with a 404.
  """

  def _make_url(self, path, params, do_urlencode=True):
    res = self._base_url
    if path:
      res += '/' + path.lstrip('/')
    if params:
      if do_urlencode:
        param_str = urllib.parse.urlencode(params)
      else:
        param_str = '&'.join(['%s=%s' % (k, v) for k, v in params.items()])
      res += '?' + param_str
    return iri_to_uri(res)


class ZooKeeper(object):

  class Error(Exception):
    pass

  class NotFound(Error):
    pass

  class ZNodeExists(Error):
    pass

  class InvalidSession(Error):
    pass

  class WrongVersion(Error):
    pass

  def __init__(self, uri='http://localhost:9998', security_enabled=False, ssl_cert_ca_verify=False):
    self._base = uri
    self._session = None
    self._client = ZooKeeperHttpClient(uri, logger=LOG)
    if security_enabled:
      self._client.set_kerberos_auth()
    self._client.set_verify(ssl_cert_ca_verify)

  def start_session(self, expire=5, id=None):
    """ Create a session and return the ID """
    if id is None:
      resp = self._do_post('sessions/v1/', params={'op': 'create', 'expire': expire})
      self._session = resp['id']
    else:
      self._session = id
    return self._session

  def close_session(self):
    """ Close the session on the server """
    if self._session is not None:
      self._do_delete('sessions/v1/%s' % self._session)
      self._session = None

  def heartbeat(self):
    """ Send a heartbeat request. This is needed in order to keep a session alive """
    if self._session is not None:
      self._do_put('sessions/v1/%s' % self._session, None)

  def get(self, path):
    """ Get a node """
    return self._do_get('znodes/v1%s' % path)

  def get_children(self, path):
    """ Get all the children for a given path. This function creates a generator """
    for child_path in self.get_children_paths(path, uris=True):
      try:
        yield self._do_get(child_path)
      except ZooKeeper.NotFound:
        continue

  def get_children_paths(self, path, uris=False):
    """ Get the paths for children nodes """
    resp = self._do_get('znodes/v1%s' % path, params={'view': 'children'})
    for child in resp.get('children', []):
      yield child if not uris else 'znodes/v1%s/%s' % (path.rstrip('/'), child)

  def create(self, path, data=None, sequence=False, ephemeral=False):
    """ Create a new node. By default this call creates a persistent znode.

    You can also create an ephemeral or a sequential znode.
    """
    ri = path.rindex('/')
    head, name = path[:ri] or '/', path[ri + 1:]

    flags = {
        'op': 'create',
        'name': name,
        'null': 'true' if data is None else 'false',
        'ephemeral': 'true' if ephemeral else 'false',
        'sequence': 'true' if sequence else 'false'
    }
    if ephemeral:
      if self._session:
        flags['session'] = self._session
      else:
        raise ZooKeeper.Error('You need a session to create an ephemeral node')

    return self._do_post('znodes/v1%s' % head, params=flags, data=data)

  def set(self, path, data=None, version=-1, null=False):
    """ Set the value of node """
    return self._do_put('znodes/v1%s' % path, data, params={
        'version': version,
        'null': 'true' if null else 'false'
    })

  def delete(self, path, version=-1):
    """ Delete a znode """
    if type(path) is list:
      list(map(lambda el: self.delete(el, version), path))
      return

    return self._do_delete('znodes/v1%s' % path, params={'version': version})

  def recursive_delete(self, path):
    """ Delete all the nodes from the tree """
    for child in self.get_children_paths(path):
      fp = ("%s/%s" % (path, child)).replace('//', '/')
      self.recursive_delete(fp)
    self.delete(path)

  def exists(self, path):
    """ Do a znode exists """
    try:
      self.get(path)
      return True
    except ZooKeeper.NotFound:
      return False

  def _do_get(self, path, params=None):
    """ Send a GET request and convert errors to exceptions """
    try:
      resp = self._client.execute('GET', path, params=params,
                                  headers={'Accept': 'application/json'})
      return self._parse(resp)
    except RestException as e:
      if e.code == 404:
        raise ZooKeeper.NotFound(path)
      raise

  def _do_post(self, path, params=None, data=None):
    """ Send a POST request and convert errors to exceptions """
    try:
      resp = self._client.execute('POST', path, params=params, data=data,
                                  headers={'Accept': 'application/json',
                                           'Content-Type': 'application/octet-stream'})
      return self._parse(resp)
    except RestException as e:
      if e.code == 409:
        raise ZooKeeper.ZNodeExists(path)
      elif e.code == 401:
        raise ZooKeeper.InvalidSession(path)
      raise

  def _do_delete(self, path, params=None):
    """ Send a DELETE request """
    try:
      return self._client.execute('DELETE', path, params=params)
    except RestException as e:
      if e.code == 412:
        raise ZooKeeper.WrongVersion(path)
      elif e.code == 404:
        raise ZooKeeper.NotFound(path)
      raise

  def _do_put(self, path, data, params=None):
    """ Send a PUT request """
    try:
      return self._client.execute('PUT', path, params=params, data=data,
                                  headers={'Content-Type': 'application/octet-stream'})
    except RestException as e:
      if e.code == 412:  # precondition failed
        raise ZooKeeper.WrongVersion(path)
      raise

  def _parse(self, resp):
    body = resp.json()
    if 'Error' in body:
      raise ZooKeeper.Error(body['Error'])
    return body
