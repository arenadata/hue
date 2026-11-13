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

import pytest

from desktop.lib import temp_paths


def _path(root, *parts):
  return os.path.join(str(root), *parts)


def test_new_hue_artifacts_are_protected_by_prefix(tmp_path):
  paths = (
    _path(tmp_path, 'hue_mako_4000000_dead'),
    _path(tmp_path, 'hue_mako_4000000_dead', 'desktop', 'login.mako.py'),
    _path(tmp_path, 'hue_vault_4000000'),
    _path(tmp_path, 'hue_vault_4000000', 'krb5cc'),
    _path(tmp_path, 'hue_indexer_alice_11111111-2222-3333-4444-555555555555:default;query.csv'),
    _path(tmp_path, 'hue_indexer_cfg_123', 'solr_configs'),
    _path(tmp_path, temp_paths.ARCHIVE_TEMP_PREFIX + 'extract-old'),
  )

  for path in paths:
    assert temp_paths.is_protected_tmp_path(path, root=str(tmp_path)), path


def test_exact_hue_artifacts_and_descendants_are_protected(tmp_path):
  paths = (
    _path(tmp_path, temp_paths.SMART_INDEXER_LIB_DIR_NAME),
    _path(tmp_path, temp_paths.SMART_INDEXER_LIB_DIR_NAME, 'library'),
    _path(tmp_path, temp_paths.HUE_CREATE_DB_DIR_NAME),
    _path(tmp_path, temp_paths.HUE_UPLOADS_DIR_NAME),
    _path(tmp_path, temp_paths.HUE_UPLOADS_DIR_NAME, 'archive.zip'),
    _path(tmp_path, temp_paths.TEMP_CLEANUP_LOCK_NAME),
  )

  for path in paths:
    assert temp_paths.is_protected_tmp_path(path, root=str(tmp_path)), path


def test_similar_names_are_not_protected(tmp_path):
  paths = (
    _path(tmp_path, 'hue_mako'),
    _path(tmp_path, 'hue_indexer'),
    _path(tmp_path, 'hue_uploads_backup'),
    _path(tmp_path, 'tmp123'),
    _path(tmp_path, 'other', 'hue_mako_4000000_dead'),
  )

  for path in paths:
    assert not temp_paths.is_protected_tmp_path(path, root=str(tmp_path)), path


def test_default_root_is_the_platform_temp_directory(tmp_path, monkeypatch):
  monkeypatch.setattr(temp_paths.tempfile, 'gettempdir', lambda: str(tmp_path))

  assert temp_paths.is_protected_tmp_path(_path(tmp_path, 'hue_mako_4000000_dead'))
  assert not temp_paths.is_protected_tmp_path(_path(tmp_path, 'tmp123'))


def test_lock_file_name_is_shared_with_the_cleaner():
  assert temp_paths.TEMP_CLEANUP_LOCK_NAME == 'hue_temp_cleanup.lock'


def test_regular_paths_can_be_removed(tmp_path):
  regular = tmp_path / 'regular'
  regular.write_text('data\n')

  assert temp_paths.can_remove_tmp_path(str(regular), root=str(tmp_path))


def test_protected_paths_cannot_be_removed(tmp_path):
  protected = tmp_path / 'hue_mako_4000000_dead'
  protected.mkdir()

  assert not temp_paths.can_remove_tmp_path(str(protected), root=str(tmp_path))


def test_symlinks_cannot_be_removed(tmp_path):
  target = tmp_path / 'target'
  target.write_text('data\n')
  link = tmp_path / 'link'

  try:
    os.symlink(str(target), str(link))
  except (OSError, NotImplementedError):
    pytest.skip('symlinks are unavailable on this platform')

  assert not temp_paths.can_remove_tmp_path(str(link), root=str(tmp_path))
  assert target.exists()
