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

from __future__ import absolute_import

import sys
import json
import logging
import posixpath
import time
import re

import requests
from django.utils.translation import gettext as _

from desktop.lib.i18n import force_unicode
from desktop.lib.rest.http_client import HttpClient, RestException
from desktop.lib.rest.resource import Resource
from notebook.connectors.base import Api, QueryError

LOG = logging.getLogger()
_JSON_CONTENT_TYPE = 'application/json'
_API_VERSION = 'v1'
SESSIONS = {}
SESSION_KEY = '%(username)s-%(connector_name)s'

n = 0

def parse_java_exception_message(message: str):
  java_errors = re.findall(r".*(Caused by:.+)$", message)
  message_parsed = java_errors[-1] if java_errors else message
  message_parsed = message_parsed.replace("\\n", "\n").replace("\\t", "\t")

  return message_parsed

def query_error_handler(func):
  def decorator(*args, **kwargs):
    try:
      return func(*args, **kwargs)
    except RestException as e:
      try:
        message = parse_java_exception_message(json.loads(e.message)['errors'])
      except Exception:
        message = parse_java_exception_message(e.message)
      message = force_unicode(message)
      raise QueryError(message)
    except Exception as e:
      message = force_unicode(str(e))
      raise QueryError(message)
  return decorator


class FlinkSqlApi(Api):

  def __init__(self, user, interpreter=None):
    Api.__init__(self, user, interpreter=interpreter)

    self.options = interpreter['options']
    api_url = self.options['url']

    self.db = FlinkSqlClient(user=user, api_url=api_url)

  @query_error_handler
  def create_session(self, lang=None, properties=None):
    session = self._get_session()

    response = {
      'type': lang,
      'id': session['id']
    }

    return response

  def _get_session(self):
    session_key = SESSION_KEY % {
      'username': self.user.username,
      'connector_name': self.interpreter['name']
    }

    if session_key not in SESSIONS:
      SESSIONS[session_key] = self.db.create_session()

    try:
      self.db.session_heartbeat(session_id=SESSIONS[session_key]['sessionHandle'])
    except Exception as e:
      if 'Session \'%(id)s\' does not exist' % SESSIONS[session_key] in str(e):
        LOG.warning('Session: %(id)s does not exist, opening a new one' % SESSIONS[session_key])
        SESSIONS[session_key] = self.db.create_session()
      else:
        raise e

    SESSIONS[session_key]['id'] = SESSIONS[session_key]['sessionHandle']

    return SESSIONS[session_key]

  @query_error_handler
  def execute(self, notebook, snippet):
    global n
    n = 0
    session = self._get_session()
    session_id = session['id']

    statement = snippet['statement'].strip().rstrip(';')

    resp = self.db.execute_statement(session_id=session_id, statement=statement)

    operation_handle = resp['operationHandle']

    return {
      'sync': False,
      'has_result_set': True,
      'guid': operation_handle,
      'result': {
        'has_more': True,
        'data': [''],
        'type': 'table'
      }
    }

  @query_error_handler
  def check_status(self, notebook, snippet):
    global n
    response = {}
    session = self._get_session()

    status = 'expired'

    if snippet.get('result'):
      statement_id = ''
      if snippet['result'].get('handle'):
        statement_id = snippet['result']['handle']['guid']
      if session:
        if not statement_id:  # Sync result
          status = 'available'
        else:
          try:
            resp = self.db.fetch_status(session['id'], statement_id)
            if resp.get('status') == 'RUNNING':
              status = 'available'
            elif resp.get('status') == 'FINISHED':
              status = 'available'
            elif resp.get('status') == 'FAILED' or resp.get('status') == 'ERROR':
              status = 'failed'
              try:
                # TODO: simplify error message on sql gateway side, : see https://issues.apache.org/jira/browse/FLINK-29646
                result_error = self.db.fetch_results(session['id'], operation_handle=statement_id)
              except RestException as restException:
                error_str = str(restException.get_parent_ex().response.json().get('errors', 'Something went wrong'))
                raise RestException(error_str)
            elif resp.get('status') == 'CANCELED':
              status = 'expired'
          except Exception as e:
            if '%s does not exist in current session' % statement_id in str(e):
              LOG.warning('Job: %s does not exist' % statement_id)
            else:
              raise e

    response['status'] = status

    return response

  @query_error_handler
  def fetch_result(self, notebook, snippet, rows, start_over):
    global n
    session = self._get_session()
    statement_id = snippet['result']['handle']['guid']
    token = n  # rows

    while True:
      resp = self.db.fetch_results(session['id'], operation_handle=statement_id, token=token)
      next_result = resp.get('nextResultUri')
      result_type = resp.get('resultType')

      if not result_type or result_type != 'NOT_READY':
        break

      time.sleep(0.1)

    if next_result:
      n += 1

    data = []

    if resp['results'].get('data'):
      data = [row['fields'] for row in resp['results']['data']]

    data_to_return = {
        'row_count': len(data),
        'next_uri': next_result,
        'has_more': bool(next_result),
        'data': data,  # No escaping...
        'meta': [{
            'name': column['name'],
            'type': column['logicalType']['type'],
            'comment': ''
          }
          for column in resp['results']['columns'] if resp
        ],
        'type': 'table'
    }

    LOG.info(f"data_to_return: {data_to_return}")

    return data_to_return

  @query_error_handler
  def autocomplete(self, snippet, database=None, table=None, column=None, nested=None, operation=None):
    response = {}

    if database is None:
      response['databases'] = self._show_databases()
    elif table is None:
      response['tables_meta'] = self._show_tables(database)
    elif column is None:
      columns = self._get_columns(database, table)
      response['columns'] = [col['name'] for col in columns]
      response['extended_columns'] = [{
          'comment': col.get('comment'),
          'name': col.get('name'),
          'type': col['type']
        }
        for col in columns
      ]

    return response

  @query_error_handler
  def get_sample_data(self, snippet, database=None, table=None, column=None, nested=None, is_async=False, operation=None):
    if operation == 'hello':
      snippet['statement'] = "SELECT 'Hello World!'"
    else:
      snippet['statement'] = f"SELECT `{column}` from {database}.{table} LIMIT 5"

    response = {
      'status': 0,
      'result': {}
    }

    sample = self.fetch_results_all(self._get_session()['id'], statement=snippet['statement'])
    data = [ db['fields'][0] for db in sample['data'] ]

    response['rows'] = data
    response['full_headers'] = sample['columns']

    return response

  @query_error_handler
  def explain(self, notebook, snippet):
    statement = snippet['statement'].rstrip(';')
    explanation = ''

    if statement:
      try:
        result = self.fetch_results_all(self._get_session()['id'], statement="EXPLAIN " + snippet['statement'])
        explanation = [ db['fields'][0] for db in result['data'] ]

      except Exception as e:
        explanation = str(e)

    return {
      'status': 0,
      'explanation': explanation,
      'statement': statement
    }

  @query_error_handler
  def cancel(self, notebook, snippet):
    session = self._get_session()
    statement_id = snippet['result']['handle']['guid']

    try:
      if session and statement_id:
        self.db.close_statement(session_id=session['id'], operation_handle=statement_id)
      else:
        return {'status': -1}  # missing operation ids
    except Exception as e:
      if 'does not exist in current session:' in str(e):
        return {'status': -1}  # skipped
      else:
        raise e

    return {'status': 0}

  def close_session(self, session):
    # Avoid closing session on page refresh or editor close for now
    pass
    # session = self._get_session()
    # self.db.close_session(session['id'])


  def fetch_results_all(self, session_id, statement):
    all_data = []
    columns = []

    resp = self.db.execute_statement(session_id=session_id, statement=statement)
    operation_handle = resp['operationHandle']
    token = 0

    # check token value to prevent infinite loop
    while token < 9999:
      results = self.db.fetch_results(session_id=session_id, operation_handle=operation_handle, token=token)
      result_type = results['resultType']
      next_result_uri = results.get('nextResultUri')

      if result_type == 'NOT_READY':
        time.sleep(0.1)
        continue

      if not columns:
        columns = results['results']['columns']

      if results['results']['data']:
        all_data.extend(results['results']['data'])

      token += 1

      if result_type == 'EOS' or not next_result_uri:
        break

    return {
      'columns': columns,
      'data': all_data
    }

  def _show_databases(self):
    session = self._get_session()
    session_id = session['id']

    results = self.fetch_results_all(session_id=session_id, statement='SHOW DATABASES')

    return [ db['fields'][0] for db in results['data'] ]

  def _show_tables(self, database):
    session = self._get_session()
    session_id = session['id']

    self.db.execute_statement(session_id=session_id, statement='USE %(database)s' % {'database': database})

    results = self.fetch_results_all(session_id=session_id, statement='SHOW TABLES')

    return [table['fields'][0] for table in results['data']]

  def _get_columns(self, database, table):
    session = self._get_session()
    session_id = session['id']

    self.db.execute_statement(session_id=session_id, statement='USE %(database)s' % {'database': database})
    results = self.fetch_results_all(session_id=session_id, statement='DESCRIBE %(table)s' % {'table': table})
    columns = results['data']

    return [{
        'name': col['fields'][0],
        'type': col['fields'][1],  # Types to unify
        'comment': '',
      }
      for col in columns
    ]

  def get_log(self, notebook, snippet, startFrom=None, size=None):
    guid = snippet['result']['handle']['guid'] if snippet.get('result') and snippet['result'].get('handle') and \
                                                    snippet['result']['handle'].get('guid') else None
    session_id = self._get_session()['id']
    return f"session id: {session_id}, operation id: {guid}"


class FlinkSqlClient():
  '''
  Implements https://nightlies.apache.org/flink/flink-docs-release-2.0/docs/dev/table/sql-gateway/overview/
  '''

  def __init__(self, user, api_url):
    self.user = user
    self._url = posixpath.join(api_url + '/' + _API_VERSION + '/')
    self._client = HttpClient(self._url, logger=LOG)
    self._root = Resource(self._client)

  def __str__(self):
    return "FlinkClient at %s" % (self._url,)

  def info(self):
    return self._root.get('info')

  def create_session(self, **properties):
    data = {
        "sessionName": "hue_session",  # optional
        "properties": {  # optional
            # "yarn.application.id": "application_1744112939468_0103" # we can set yarn application id here
        }
    }
    data.update(properties)

    return self._root.post('sessions', data=json.dumps(data), contenttype=_JSON_CONTENT_TYPE)

  def session_heartbeat(self, session_id):
    return self._root.post('sessions/%(session_id)s/heartbeat' % {'session_id': session_id})

  def execute_statement(self, session_id, statement):
    data = {
        "statement": statement,  # required
        "executionTimeout": ""  # execution time limit in milliseconds, optional, but required for stream SELECT ?
    }

    return self._root.post(
        'sessions/%(session_id)s/statements' % {
        'session_id': session_id
      },
      data=json.dumps(data),
      contenttype=_JSON_CONTENT_TYPE
    )

  def fetch_status(self, session_id, operation_handle):
    return self._root.get(
      'sessions/%(session_id)s/operations/%(operation_handle)s/status' % {
        'session_id': session_id,
        'operation_handle': operation_handle
      }
    )

  def fetch_results(self, session_id, operation_handle, token=0):
    return self._root.get(
      'sessions/%(session_id)s/operations/%(operation_handle)s/result/%(token)s' % {
        'session_id': session_id,
        'operation_handle': operation_handle,
        'token': token
      }
    )

  def close_statement(self, session_id, operation_handle):
    return self._root.delete(
      'sessions/%(session_id)s/operations/%(operation_handle)s/close' % {
        'session_id': session_id,
        'operation_handle': operation_handle,
      }
    )

  def cancel_statement(self, session_id, operation_handle):
    return self._root.post(
      'sessions/%(session_id)s/operations/%(operation_handle)s/cancel' % {
        'session_id': session_id,
        'operation_handle': operation_handle,
      }
    )

  def close_session(self, session_id):
    return self._root.delete(
      'sessions/%(session_id)s' % {
        'session_id': session_id,
      }
    )
