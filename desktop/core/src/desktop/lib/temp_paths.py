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

import os
import tempfile

MAKO_DIR_PREFIX = 'hue_mako_'
VAULT_DIR_PREFIX = 'hue_vault_'
INDEXER_STAGING_PREFIX = 'hue_indexer_'
INDEXER_CONFIG_DIR_PREFIX = 'hue_indexer_cfg_'
LEGACY_TMP_PREFIX = 'tmp'
TEMP_CLEANUP_LOCK_NAME = 'hue_temp_cleanup.lock'
ARCHIVE_TEMP_PREFIX = 'hue_archive_'
SMART_INDEXER_LIB_DIR_NAME = 'smart_indexer_lib'
HUE_CREATE_DB_DIR_NAME = 'hue_create_db'
HUE_UPLOADS_DIR_NAME = 'hue_uploads'

PROTECTED_TMP_NAMES = (
  SMART_INDEXER_LIB_DIR_NAME,
  HUE_CREATE_DB_DIR_NAME,
  HUE_UPLOADS_DIR_NAME,
  TEMP_CLEANUP_LOCK_NAME,
)

PROTECTED_TMP_PREFIXES = (
  MAKO_DIR_PREFIX,
  VAULT_DIR_PREFIX,
  INDEXER_STAGING_PREFIX,
  ARCHIVE_TEMP_PREFIX,
)


def is_protected_tmp_path(path, root=None):
  root = os.path.abspath(root or tempfile.gettempdir())
  normalized = os.path.abspath(path)

  for name in PROTECTED_TMP_NAMES:
    protected = os.path.join(root, name)
    if normalized == protected or normalized.startswith(protected + os.sep):
      return True

  for prefix in PROTECTED_TMP_PREFIXES:
    if normalized.startswith(os.path.join(root, prefix)):
      return True

  return False
