#!/usr/bin/env python
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
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

from django.test import TestCase

from desktop.lib.django_test_util import make_logged_in_client
from notebook.connectors.jdbc_starrocks import JdbcApiStarrocks, StarrocksAssist
from useradmin.models import User


class TestJdbcApiStarrocks(TestCase):

  @classmethod
  def setup_class(cls):
    cls.client = make_logged_in_client(username='hue_test', groupname='default', recreate=True, is_superuser=False)
    cls.user = User.objects.get(username='hue_test')

  def _make_api(self, show_catalogs=None):
    options = {'url': 'jdbc:mysql://starrocks:9030/', 'driver': 'com.mysql.cj.jdbc.Driver', 'user': 'root', 'password': ''}
    if show_catalogs is not None:
      options['show_catalogs'] = str(show_catalogs).lower()
    api = JdbcApiStarrocks(self.user, interpreter={'options': options, 'name': 'starrocks'})
    api.db = MagicMock()
    return api

  def test_show_catalogs_default(self):
    assert self._make_api().show_catalogs is True

  def test_show_catalogs_true(self):
    assert self._make_api(show_catalogs=True).show_catalogs is True

  def test_show_catalogs_false(self):
    assert self._make_api(show_catalogs=False).show_catalogs is False

  def test_get_browse_query_with_catalogs(self):
    result = self._make_api().get_browse_query({}, 'default_catalog.my_db', 'my_table')
    assert result == 'SELECT * FROM `default_catalog`.`my_db`.`my_table` LIMIT 1000'

  def test_get_browse_query_without_catalogs(self):
    result = self._make_api(show_catalogs=False).get_browse_query({}, 'my_db', 'my_table')
    assert result == 'SELECT * FROM `my_db`.`my_table` LIMIT 1000'

  def test_autocomplete_databases_with_catalogs(self):
    api = self._make_api()
    with patch.object(StarrocksAssist, 'get_all_databases', return_value=['default_catalog.db1', 'default_catalog.db2']):
      response = api.autocomplete({})
      assert response['status'] == 0
      assert response['databases'] == ['default_catalog.db1', 'default_catalog.db2']

  def test_autocomplete_databases_without_catalogs(self):
    api = self._make_api(show_catalogs=False)
    with patch.object(StarrocksAssist, 'get_databases', return_value=['db1', 'db2']):
      response = api.autocomplete({})
      assert response['status'] == 0
      assert response['databases'] == ['db1', 'db2']

  def test_autocomplete_tables_with_catalogs(self):
    api = self._make_api()
    tables = [{'name': 'table1', 'type': 'Table', 'comment': ''}, {'name': 'table2', 'type': 'Table', 'comment': ''}]
    with patch.object(StarrocksAssist, 'get_tables_full', return_value=tables) as mock_tables:
      response = api.autocomplete({}, database='default_catalog.my_db')
      mock_tables.assert_called_once_with('default_catalog', 'my_db')
      assert response['status'] == 0
      assert response['tables'] == ['table1', 'table2']

  def test_autocomplete_tables_without_catalogs(self):
    api = self._make_api(show_catalogs=False)
    tables = [{'name': 'table1', 'type': 'Table', 'comment': ''}]
    with patch.object(StarrocksAssist, 'get_tables_full', return_value=tables) as mock_tables:
      response = api.autocomplete({}, database='my_db')
      mock_tables.assert_called_once_with(None, 'my_db')
      assert response['status'] == 0

  def test_autocomplete_columns_with_catalogs(self):
    api = self._make_api()
    columns = [
      {'name': 'id', 'type': 'int', 'comment': ''},
      {'name': 'name', 'type': 'varchar', 'comment': 'user name'},
    ]
    with patch.object(StarrocksAssist, 'get_columns_full', return_value=columns) as mock_cols:
      response = api.autocomplete({}, database='default_catalog.my_db', table='my_table')
      mock_cols.assert_called_once_with('default_catalog', 'my_db', 'my_table')
      assert response['status'] == 0
      assert response['columns'] == ['id', 'name']
      assert response['extended_columns'] == columns

  def test_autocomplete_columns_without_catalogs(self):
    api = self._make_api(show_catalogs=False)
    columns = [{'name': 'id', 'type': 'int', 'comment': ''}]
    with patch.object(StarrocksAssist, 'get_columns_full', return_value=columns) as mock_cols:
      response = api.autocomplete({}, database='my_db', table='my_table')
      mock_cols.assert_called_once_with(None, 'my_db', 'my_table')
      assert response['status'] == 0

  def test_get_sample_data_success(self):
    rows = [['1', 'Alice'], ['2', 'Bob']]
    description = [('id', 'int'), ('name', 'varchar')]
    with patch.object(StarrocksAssist, 'get_sample_data', return_value=(rows, description)):
      response = self._make_api().get_sample_data({}, database='default_catalog.my_db', table='my_table')
      assert response['status'] == 0
      assert response['rows'] == rows
      assert response['headers'] == ['id', 'name']
      assert response['full_headers'] == [
        {'name': 'id', 'type': 'int', 'comment': ''},
        {'name': 'name', 'type': 'varchar', 'comment': ''},
      ]

  def test_get_sample_data_empty(self):
    with patch.object(StarrocksAssist, 'get_sample_data', return_value=([], [])):
      response = self._make_api().get_sample_data({}, database='default_catalog.my_db', table='my_table')
      assert response['status'] == -1
      assert response['message'] == 'Failed to get sample data.'


class TestStarrocksAssist(TestCase):

  def setUp(self):
    self.db = MagicMock()
    self.assist = StarrocksAssist(self.db)

  def test_get_catalogs(self):
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=([['default_catalog'], ['hive_catalog'], ['information_schema']], None)):
      result = self.assist.get_catalogs()
      assert result == ['default_catalog', 'hive_catalog']

  def test_get_databases(self):
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=([['db1'], ['db2']], None)):
      result = self.assist.get_databases('default_catalog')
      assert result == ['db1', 'db2']

  def test_get_all_databases(self):
    with patch.object(StarrocksAssist, 'get_catalogs', return_value=['default_catalog', 'hive_catalog']):
      with patch.object(StarrocksAssist, 'get_databases', side_effect=[['db1', 'db2'], ['db3']]):
        result = self.assist.get_all_databases()
        assert result == ['default_catalog.db1', 'default_catalog.db2', 'hive_catalog.db3']

  def test_get_all_databases_skips_inaccessible_catalog(self):
    with patch.object(StarrocksAssist, 'get_catalogs', return_value=['default_catalog', 'restricted_catalog']):
      with patch.object(StarrocksAssist, 'get_databases', side_effect=[['db1'], Exception('Access denied')]):
        result = self.assist.get_all_databases()
        assert result == ['default_catalog.db1']

  def test_get_tables_full(self):
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=([['table1'], ['table2']], None)) as mock_qaf:
      result = self.assist.get_tables_full('default_catalog', 'my_db')
      mock_qaf.assert_called_once_with(self.db, 'SHOW TABLES FROM `default_catalog`.`my_db`')
      assert result == [
        {'name': 'table1', 'type': 'Table', 'comment': ''},
        {'name': 'table2', 'type': 'Table', 'comment': ''},
      ]

  def test_get_tables_full_without_catalog(self):
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=([['table1']], None)) as mock_qaf:
      result = self.assist.get_tables_full(None, 'my_db')
      mock_qaf.assert_called_once_with(self.db, 'SHOW TABLES FROM `my_db`')
      assert result == [{'name': 'table1', 'type': 'Table', 'comment': ''}]

  def test_get_columns_full(self):
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=([['id', 'int', 'primary key'], ['name', 'varchar', '']], None)):
      result = self.assist.get_columns_full('default_catalog', 'my_db', 'my_table')
      assert result == [
        {'name': 'id', 'type': 'int', 'comment': 'primary key'},
        {'name': 'name', 'type': 'varchar', 'comment': ''},
      ]

  def test_get_sample_data(self):
    rows = [['1', 'Alice'], ['2', 'Bob']]
    description = [('id', 'int'), ('name', 'varchar')]
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=(rows, description)):
      result_rows, result_desc = self.assist.get_sample_data('default_catalog', 'my_db', 'my_table')
      assert result_rows == rows
      assert result_desc == description

  def test_get_sample_data_with_column(self):
    rows = [['1'], ['2']]
    description = [('id', 'int')]
    with patch('notebook.connectors.jdbc_starrocks.query_and_fetch', return_value=(rows, description)) as mock_qaf:
      self.assist.get_sample_data('default_catalog', 'my_db', 'my_table', column='id')
      mock_qaf.assert_called_once_with(self.db, 'SELECT id FROM `default_catalog`.`my_db`.`my_table` LIMIT 100')
