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

from desktop.lib import runtime_utils
from desktop.lib.runtime_utils import _parse_java_home, resolve_java_home


@pytest.fixture(autouse=True)
def _clear_java_home_cache():
  runtime_utils._JAVA_HOME_CACHE.clear()
  yield
  runtime_utils._JAVA_HOME_CACHE.clear()


def _completed(returncode=0, stdout='', stderr=''):
  proc = MagicMock()
  proc.returncode = returncode
  proc.stdout = stdout
  proc.stderr = stderr
  return proc


def test_parse_java_home_basic():
  assert _parse_java_home('export JAVA_HOME=/opt/jdk-17\n') == '/opt/jdk-17'


def test_parse_java_home_strips_quotes_and_extra_lines():
  stdout = 'some noise\nexport JAVA_HOME="/opt/jdk-17"\n'
  assert _parse_java_home(stdout) == '/opt/jdk-17'


def test_parse_java_home_missing_line():
  assert _parse_java_home('JAVA_HOME is somewhere\n') is None
  assert _parse_java_home('') is None
  assert _parse_java_home(None) is None


def test_resolve_java_home_success():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run',
             return_value=_completed(stdout='export JAVA_HOME=/opt/jdk-17\n')) as run:
    assert resolve_java_home(service='TRINO') == '/opt/jdk-17'

    cmd = run.call_args[0][0]
    assert cmd[0] == runtime_utils.DEFAULT_RUNTIME_UTILS_BIN
    assert '--service' in cmd and cmd[cmd.index('--service') + 1] == 'TRINO'
    assert '--runtime' in cmd and cmd[cmd.index('--runtime') + 1] == 'java'


def test_resolve_java_home_default_service_is_empty():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run',
             return_value=_completed(stdout='export JAVA_HOME=/opt/jdk-17\n')) as run:
    assert resolve_java_home() == '/opt/jdk-17'
    cmd = run.call_args[0][0]
    assert cmd[cmd.index('--service') + 1] == ''


def test_resolve_java_home_missing_binary():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=False):
    assert resolve_java_home(service='TRINO') is None


def test_resolve_java_home_nonzero_exit():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run',
             return_value=_completed(returncode=1, stderr='boom')):
    assert resolve_java_home(service='TRINO') is None


def test_resolve_java_home_subprocess_raises():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run', side_effect=OSError('nope')):
    assert resolve_java_home(service='TRINO') is None


def test_resolve_java_home_success_is_cached():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run',
             return_value=_completed(stdout='export JAVA_HOME=/opt/jdk-17\n')) as run:
    assert resolve_java_home(service='TRINO') == '/opt/jdk-17'
    assert resolve_java_home(service='TRINO') == '/opt/jdk-17'
    assert run.call_count == 1


def test_resolve_java_home_failure_is_not_cached():
  with patch('desktop.lib.runtime_utils.os.path.isfile', return_value=True), \
       patch('desktop.lib.runtime_utils.subprocess.run',
             return_value=_completed(returncode=1, stderr='boom')) as run:
    assert resolve_java_home(service='TRINO') is None
    assert resolve_java_home(service='TRINO') is None
    assert run.call_count == 2
