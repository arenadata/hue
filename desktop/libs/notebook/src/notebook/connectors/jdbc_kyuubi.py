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

from django.utils.translation import gettext as _

from desktop.conf import has_connectors
from desktop.lib.exceptions_renderable import PopupException
from librdbms.jdbc import query_and_fetch
from notebook.conf import kyuubi_engine_to_action
from notebook.connectors.jdbc import Assist, JdbcApi


class JdbcApiKyuubi(JdbcApi):

  def create_session(self, lang=None, properties=None):
    if not has_connectors():
      if not self.user.has_hue_permission(action='access', app='kyuubi'):
        raise PopupException(_('Missing permission to access the Kyuubi interpreter'), error_code=401)
      interpreter_type = self.interpreter.get('type', '')
      if interpreter_type.startswith('kyuubi_'):
        engine_action = kyuubi_engine_to_action(interpreter_type)
        if not self.user.has_hue_permission(action=engine_action, app='kyuubi'):
          engine_name = interpreter_type[len('kyuubi_'):]
          raise PopupException(
            _('Missing permission to access the Kyuubi %s engine') % engine_name,
            error_code=401
          )
    return super(JdbcApiKyuubi, self).create_session(lang, properties)

  def _createAssist(self, db):
    return KyuubiAssist(db)


class KyuubiAssist(Assist):

  def get_databases(self):
    dbs, description = query_and_fetch(self.db, 'SHOW DATABASES')
    return [db[0] and db[0].strip() for db in dbs]

  def get_tables_full(self, database, table_names=[]):
    tables, description = query_and_fetch(self.db, "SHOW TABLES IN %s" % database)
    return [{"comment": '', "type": "Table", "name": table[1] and table[1].strip()} for table in tables]

  def get_columns_full(self, database, table):
    columns, description = query_and_fetch(self.db, "DESCRIBE %s.%s" % (database, table))
    return [{"comment": col[2] and col[2].strip(), "type": col[1], "name": col[0] and col[0].strip()} for col in columns]

  def get_sample_data(self, database, table, column=None, nested=None):
    column = column or '*'
    return query_and_fetch(self.db, 'SELECT %s FROM %s.%s limit 100' % (column, database, table))
