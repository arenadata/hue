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

from unittest.mock import Mock, patch

import pytest
from django.test import TestCase

from desktop.lib.exceptions_renderable import PopupException
from notebook.connectors.jdbc_kyuubi import JdbcApiKyuubi


class TestJdbcApiKyuubi(TestCase):

  def _make_api(self, perms, interpreter_type='kyuubi'):
    api = JdbcApiKyuubi.__new__(JdbcApiKyuubi)
    api.user = Mock()
    api.user.has_hue_permission.side_effect = lambda action, app: (app, action) in perms
    api.interpreter = {'type': interpreter_type, 'options': {}}
    return api

  def test_create_session_blocked_without_base_access(self):
    api = self._make_api(perms=set())

    with pytest.raises(PopupException) as exc:
      api.create_session()
    assert exc.value.error_code == 401

  def test_create_session_blocked_without_engine_access(self):
    api = self._make_api(perms={('kyuubi', 'access')}, interpreter_type='kyuubi_spark3')

    with pytest.raises(PopupException) as exc:
      api.create_session()
    assert exc.value.error_code == 401

  def test_create_session_passes_with_engine_access(self):
    api = self._make_api(
      perms={('kyuubi', 'access'), ('kyuubi', 'access_spark3')},
      interpreter_type='kyuubi_spark3',
    )

    with patch('notebook.connectors.jdbc.JdbcApi.create_session', return_value={'id': 'ok'}) as parent_mock:
      result = api.create_session()

    assert result == {'id': 'ok'}
    parent_mock.assert_called_once()

  def test_create_session_base_type_skips_engine_check(self):
    api = self._make_api(perms={('kyuubi', 'access')}, interpreter_type='kyuubi')

    with patch('notebook.connectors.jdbc.JdbcApi.create_session', return_value={'id': 'ok'}):
      result = api.create_session()

    assert result == {'id': 'ok'}
