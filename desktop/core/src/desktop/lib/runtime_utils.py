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
import os
import subprocess

LOG = logging.getLogger()

DEFAULT_RUNTIME_UTILS_BIN = os.environ.get(
  'AD_RUNTIME_UTILS_BIN', '/usr/lib/ad-runtime-utils/bin/ad-runtime-utils')
DEFAULT_RUNTIME_UTILS_CONFIG = os.environ.get(
  'AD_RUNTIME_UTILS_CONFIG', '/etc/ad-runtime-utils/config.yaml')

_EXPORT_PREFIX = 'export JAVA_HOME='

_JAVA_HOME_CACHE = {}


def resolve_java_home(service=None, binary=None, config=None, timeout=30):
  binary = binary or DEFAULT_RUNTIME_UTILS_BIN
  config = config or DEFAULT_RUNTIME_UTILS_CONFIG

  cache_key = (service or '', binary, config)
  if cache_key in _JAVA_HOME_CACHE:
    return _JAVA_HOME_CACHE[cache_key]

  if not os.path.isfile(binary):
    LOG.warning("ad-runtime-utils binary not found at '%s'; cannot resolve JAVA_HOME", binary)
    return None

  cmd = [binary, '--config', config, '--service', service or '', '--runtime', 'java']

  try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
  except Exception as e:
    LOG.error("Failed to execute ad-runtime-utils %s: %s", cmd, e)
    return None

  if result.returncode != 0:
    LOG.error(
      "ad-runtime-utils failed (rc=%s) for service '%s': %s",
      result.returncode, service or '', (result.stderr or '').strip())
    return None

  java_home = _parse_java_home(result.stdout)
  if java_home:
    _JAVA_HOME_CACHE[cache_key] = java_home
  return java_home


def _parse_java_home(stdout):
  for line in (stdout or '').splitlines():
    line = line.strip()
    if line.startswith(_EXPORT_PREFIX):
      java_home = line[len(_EXPORT_PREFIX):].strip().strip('"').strip("'")
      if java_home:
        return java_home

  LOG.error("ad-runtime-utils did not return a JAVA_HOME line; stdout=%r", stdout)
  return None
