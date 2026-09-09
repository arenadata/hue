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

import logging

from librdbms.jdbc import query_and_fetch

from notebook.connectors.jdbc import Assist, JdbcApi
from notebook.connectors.base import AuthenticationRequired

LOG = logging.getLogger()


class JdbcApiStarrocks(JdbcApi):

  def _createAssist(self, db):
    return StarrocksAssist(db)

  @property
  def show_catalogs(self):
    return str(self.options.get('show_catalogs', 'true')).lower() != 'false'

  def get_browse_query(self, snippet, database, table, partition_spec=None):
    if self.show_catalogs:
      catalog, db = database.split('.', 1)
      return 'SELECT * FROM `%s`.`%s`.`%s` LIMIT 1000' % (catalog, db, table)
    return 'SELECT * FROM `%s`.`%s` LIMIT 1000' % (database, table)

  def autocomplete(self, snippet, database=None, table=None, column=None, nested=None, operation=None):
    if self.db is None:
      raise AuthenticationRequired()

    assist = self._createAssist(self.db)
    response = {'status': -1}

    if database is None:
      response['databases'] = assist.get_all_databases() if self.show_catalogs else assist.get_databases()
    elif table is None:
      if self.show_catalogs:
        catalog, db = database.split('.', 1)
        tables = assist.get_tables_full(catalog, db)
      else:
        tables = assist.get_tables_full(None, database)
      response['tables'] = [t['name'] for t in tables]
      response['tables_meta'] = tables
    else:
      if self.show_catalogs:
        catalog, db = database.split('.', 1)
        columns = assist.get_columns_full(catalog, db, table)
      else:
        columns = assist.get_columns_full(None, database, table)
      response['columns'] = [col['name'] for col in columns]
      response['extended_columns'] = columns

    response['status'] = 0
    return response

  def get_sample_data(self, snippet, database=None, table=None, column=None, is_async=False, operation=None):
    if self.db is None:
      raise AuthenticationRequired()

    assist = self._createAssist(self.db)
    response = {'status': -1, 'result': {}}

    if self.show_catalogs and database and '.' in database:
      catalog, db = database.split('.', 1)
    else:
      catalog, db = None, database

    sample_data, description = assist.get_sample_data(catalog, db, table, column)

    if sample_data or description:
      response['status'] = 0
      response['headers'] = [col[0] for col in description] if description else []
      response['full_headers'] = [{'name': col[0], 'type': col[1], 'comment': ''} for col in description]
      response['rows'] = sample_data if sample_data else []
    else:
      response['message'] = 'Failed to get sample data.'

    return response


class StarrocksAssist(Assist):

  def get_all_databases(self):
    catalogs = self.get_catalogs()
    result = []
    for catalog in catalogs:
      try:
        for db in self.get_databases(catalog):
          result.append('%s.%s' % (catalog, db))
      except Exception as e:
        LOG.error('Failed to fetch databases from catalog %s: %s' % (catalog, str(e)))
        continue
    return result

  def get_catalogs(self):
    rows, _ = query_and_fetch(self.db, 'SHOW CATALOGS')
    return [row[0].strip() for row in rows if row[0].strip() != 'information_schema']

  def get_databases(self, catalog=None):
    if catalog:
      rows, _ = query_and_fetch(self.db, 'SHOW DATABASES FROM `%s`' % catalog)
      return [row[0].strip() for row in rows]
    rows, _ = query_and_fetch(self.db, 'SHOW DATABASES')
    return [row[0].strip() for row in rows]

  def get_tables_full(self, catalog, database, table_names=[]):
    if catalog:
      rows, _ = query_and_fetch(self.db, "SHOW TABLES FROM `%s`.`%s`" % (catalog, database))
    else:
      rows, _ = query_and_fetch(self.db, "SHOW TABLES FROM `%s`" % database)
    return [{'name': row[0].strip(), 'type': 'Table', 'comment': ''} for row in rows]

  def get_columns_full(self, catalog, database, table):
    rows, _ = query_and_fetch(
      self.db,
      "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT FROM information_schema.columns "
      "WHERE TABLE_SCHEMA='%s' AND TABLE_NAME='%s'" % (database, table)
    )
    return [{'name': row[0].strip(), 'type': row[1], 'comment': row[2] and row[2].strip() or ''} for row in rows]

  def get_sample_data(self, catalog, database, table, column=None):
    column = column or '*'
    if catalog:
      return query_and_fetch(self.db, 'SELECT %s FROM `%s`.`%s`.`%s` LIMIT 100' % (column, catalog, database, table))
    return query_and_fetch(self.db, 'SELECT %s FROM `%s`.`%s` LIMIT 100' % (column, database, table))
