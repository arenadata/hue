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

import re
import socket
import logging
from builtins import map, object
from io import StringIO as string_io

from desktop.lib.rest.http_client import RestException
from zookeeper.rest import ZooKeeperHttpClient

LOG = logging.getLogger()


class Session(object):

  class BrokenLine(Exception):
    pass

  def __init__(self, host, port, interest_ops=0, **params):
    self.host = host
    self.port = port
    self.interest_ops = interest_ops
    for k, v in params.items():
      self.__dict__[k] = v

  @classmethod
  def parse(cls, line):
    m = re.search(r'/(\d+\.\d+\.\d+\.\d+):(\d+)\[(\d+)\]\((.*)\)', line)
    if not m:
      raise Session.BrokenLine()
    params = {}
    for d in m.group(4).split(","):
      k, v = d.split("=")
      params[k] = v
    return Session(m.group(1), m.group(2), m.group(3), **params)


class AdminServerStats(object):
  """Stats and clients via the admin server /commands endpoints (JSON)."""

  ENVELOPE_KEYS = ('command', 'error')

  def __init__(self, url, security_enabled=False, ssl_cert_ca_verify=False, timeout=5):
    self._url = url
    self._timeout = timeout
    # The auth and verify flags mutate the requests session cached per netloc,
    # so the admin server must not share its host:port with the REST gateway.
    self._client = ZooKeeperHttpClient(url, logger=LOG)
    if security_enabled:
      self._client.set_kerberos_auth()
    self._client.set_verify(ssl_cert_ca_verify)

  def get_stats(self):
    body = self._run_command('mntr')
    if body is not None and not body.get('error'):
      # The admin server serves mntr keys unprefixed; the 4lw text output
      # (and everything in Hue that reads it) carries the zk_ prefix.
      return {'zk_' + k: v for k, v in body.items() if k not in AdminServerStats.ENVELOPE_KEYS}
    body = self._run_command('stat')
    if body is None or body.get('error'):
      return {}
    return self._parse_stat(body)

  def get_clients(self):
    body = self._run_command('stat')
    if body is None or body.get('error'):
      return []
    return [self._to_session(info) for info in body.get('connections') or []]

  def _run_command(self, command):
    """Run a 4lw command over HTTP and return the JSON body, or None on error."""
    try:
      resp = self._client.execute('GET', 'commands/%s' % command,
                                  headers={'Accept': 'application/json'},
                                  timeout=self._timeout)
      return resp.json()
    except RestException as e:
      self._log_command_error(command, e)
      return None
    except ValueError as e:
      LOG.error('Problem parsing the %s response of admin server %s : %s'
                % (command, self._url, e))
      return None

  def _log_command_error(self, command, e):
    if e.code == 401:
      LOG.error('Admin server %s rejected command %s: Kerberos (SPNEGO) authentication failed, '
                'check the security_enabled cluster option and the Hue Kerberos ticket'
                % (self._url, command))
    elif e.code == 403:
      LOG.error('Admin server %s does not allow command %s, enable it via the '
                'admin.spnego.commands server property' % (self._url, command))
    else:
      LOG.error('Problem fetching %s from admin server %s, exception raised : %s'
                % (command, self._url, e))

  def _to_session(self, info):
    host, _, port = str(info.get('remote_socket_address', '')).rpartition(':')
    return Session(host.lstrip('/'), port,
                   interest_ops=info.get('interest_ops'),
                   queued=info.get('outstanding_requests'),
                   recved=info.get('packets_received'),
                   sent=info.get('packets_sent'))

  @staticmethod
  def _parse_stat(body):
    server = body.get('server_stats') or {}
    result = {
        'zk_version': body.get('version'),
        'zk_min_latency': server.get('min_latency'),
        'zk_avg_latency': server.get('avg_latency'),
        'zk_max_latency': server.get('max_latency'),
        'zk_packets_received': server.get('packets_received'),
        'zk_packets_sent': server.get('packets_sent'),
        'zk_outstanding_requests': server.get('outstanding_requests'),
        'zk_server_state': server.get('server_state'),
        'zk_znode_count': body.get('node_count'),
    }
    return {k: v for k, v in result.items() if v is not None}


class ZooKeeperStats(object):

    def __init__(self, host='localhost', port='2181', timeout=1,
                 admin_port=None, security_enabled=False, ssl_cert_ca_verify=False):
      self._address = (host, int(port))
      self._timeout = timeout
      self._host = host
      if admin_port:
        self._admin = AdminServerStats('http://%s:%s' % (host, admin_port),
                                       security_enabled=security_enabled,
                                       ssl_cert_ca_verify=ssl_cert_ca_verify)
      else:
        self._admin = None

    def get_stats(self):
      """ Get ZooKeeper server stats as a map """
      if self._admin is not None:
        return self._admin.get_stats()
      data = self._send_cmd('mntr')
      if data:
        return self._parse(data)
      else:
        data = self._send_cmd('stat')
        return self._parse_stat(data)

    def get_clients(self):
      """ Get ZooKeeper server clients """
      if self._admin is not None:
        return self._admin.get_clients()

      clients = []

      stat = self._send_cmd('stat')
      if not stat:
        return clients

      sio = string_io(stat)

      # skip two lines
      sio.readline()
      sio.readline()

      for line in sio:
        if not line.strip():
          break
        try:
          clients.append(Session.parse(line.strip()))
        except Session.BrokenLine:
          continue

      return clients

    def _create_socket(self):
      return socket.socket()

    def _send_cmd(self, cmd):
      """ Send a 4letter word command to the server """
      s = self._create_socket()
      s.settimeout(self._timeout)
      data = ""
      try:
        s.connect(self._address)
        s.send(cmd.encode('utf-8') if isinstance(cmd, str) else cmd)
        data = s.recv(2048)
        if isinstance(data, bytes):
          data = data.decode('utf-8')
        s.close()
      except Exception as e:
        LOG.error('Problem connecting to host %s, exception raised : %s' % (self._host, e))
      return data

    def _parse(self, data):
      """ Parse the output from the 'mntr' 4letter word command """
      h = string_io(data)

      result = {}
      for line in h.readlines():
        try:
          key, value = self._parse_line(line)
          result[key] = value
        except ValueError:
          pass  # ignore broken lines

      return result

    def _parse_stat(self, data):
      """ Parse the output from the 'stat' 4letter word command """

      result = {}
      if not data:
        return result
      h = string_io(data)

      version = h.readline()
      if version:
        result['zk_version'] = version[version.index(':') + 1:].strip()

      # skip all lines until we find the empty one
      while h.readline().strip():
        pass

      for line in h.readlines():
        m = re.match(r'Latency min/avg/max: (\d+)/(\d+)/(\d+)', line)
        if m is not None:
          result['zk_min_latency'] = int(m.group(1))
          result['zk_avg_latency'] = int(m.group(2))
          result['zk_max_latency'] = int(m.group(3))
          continue

        m = re.match(r'Received: (\d+)', line)
        if m is not None:
          result['zk_packets_received'] = int(m.group(1))
          continue

        m = re.match(r'Sent: (\d+)', line)
        if m is not None:
          result['zk_packets_sent'] = int(m.group(1))
          continue

        m = re.match(r'Outstanding: (\d+)', line)
        if m is not None:
          result['zk_outstanding_requests'] = int(m.group(1))
          continue

        m = re.match('Mode: (.*)', line)
        if m is not None:
          result['zk_server_state'] = m.group(1)
          continue

        m = re.match(r'Node count: (\d+)', line)
        if m is not None:
          result['zk_znode_count'] = int(m.group(1))
          continue

      return result

    def _parse_line(self, line):
      try:
        key, value = list(map(str.strip, line.split('\t')))
      except ValueError:
        raise ValueError('Found invalid line: %s' % line)

      if not key:
        raise ValueError('The key is mandatory and should not be empty')

      try:
        value = int(value)
      except (TypeError, ValueError):
        pass

      return key, value
