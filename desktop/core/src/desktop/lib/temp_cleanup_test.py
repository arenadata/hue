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
import time
import threading
import subprocess
from io import StringIO

import pytest
from django.core.management import call_command

from desktop.conf import TEMP_CLEANUP
from desktop.lib import temp_cleanup
from desktop.lib.temp_paths import ARCHIVE_TEMP_PREFIX

DEAD_PID = 4000000


def _touch_old(path, hours=2):
  timestamp = time.time() - hours * 3600
  os.utime(path, (timestamp, timestamp))


def _make_mako_dir(path, with_data=False):
  module = path / 'desktop'
  module.mkdir(parents=True)
  (module / 'login.mako.py').write_text('# compiled mako module\n')
  if with_data:
    (module / 'data.csv').write_text('col\n')


def test_cleanup_mako_dirs_removes_only_dead_processes(tmp_path):
  dead = tmp_path / ('hue_mako_%d_dead' % DEAD_PID)
  live = tmp_path / ('hue_mako_%d_live' % os.getpid())
  fresh = tmp_path / ('hue_mako_%d_fresh' % DEAD_PID)

  for directory in (dead, live, fresh):
    _make_mako_dir(directory)
  _touch_old(dead)
  _touch_old(live)

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1)

  assert str(dead) in removed
  assert not dead.exists()
  assert live.exists()
  assert fresh.exists()


def test_cleanup_legacy_mako_dirs_only_with_signature(tmp_path):
  legacy_mako = tmp_path / 'tmpabc123'
  unrelated = tmp_path / 'tmpdef456'
  mixed = tmp_path / 'tmpghi789'
  fresh = tmp_path / 'tmpjkl012'

  _make_mako_dir(legacy_mako)
  unrelated.mkdir()
  (unrelated / 'notes.txt').write_text('not a mako module\n')
  _make_mako_dir(mixed, with_data=True)
  _make_mako_dir(fresh)

  for directory in (legacy_mako, unrelated, mixed):
    _touch_old(directory)

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1, clean_legacy=True)

  assert str(legacy_mako) in removed
  assert not legacy_mako.exists()
  assert unrelated.exists()
  assert mixed.exists()
  assert fresh.exists()


def test_legacy_mako_dirs_are_kept_without_legacy_flag(tmp_path):
  legacy_mako = tmp_path / 'tmpabc123'
  _make_mako_dir(legacy_mako)
  _touch_old(legacy_mako)

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1, clean_legacy=False)

  assert removed == []
  assert legacy_mako.exists()


def test_cleanup_vault_dirs(tmp_path):
  dead = tmp_path / ('hue_vault_%d_dead' % DEAD_PID)
  live = tmp_path / ('hue_vault_%d_live' % os.getpid())
  fresh = tmp_path / ('hue_vault_%d_fresh' % DEAD_PID)

  for directory in (dead, live, fresh):
    directory.mkdir()
    (directory / 'ccache').write_text('credentials\n')
  _touch_old(dead)
  _touch_old(live)

  removed = temp_cleanup.cleanup_vault_dirs(str(tmp_path), ttl_hours=1)

  assert str(dead) in removed
  assert not dead.exists()
  assert live.exists()
  assert fresh.exists()


def test_cleanup_legacy_vault_dirs_without_pid(tmp_path):
  dead = tmp_path / 'hue_vault_legacy'
  fresh = tmp_path / 'hue_vault_legacy_fresh'
  foreign = tmp_path / 'tmpvaultlike'
  for directory in (dead, fresh, foreign):
    directory.mkdir()
    (directory / 'ccache').write_text('credentials\n')
  _touch_old(dead)
  _touch_old(foreign)

  removed = temp_cleanup.cleanup_vault_dirs(str(tmp_path), ttl_hours=1)

  assert str(dead) in removed
  assert not dead.exists()
  assert fresh.exists()
  assert foreign.exists()


def test_cleanup_legacy_empty_mako_dirs_only_with_explicit_flag(tmp_path):
  empty = tmp_path / 'tmpemptymako'
  nonempty = tmp_path / 'tmpnonemptymako'
  empty.mkdir()
  nonempty.mkdir()
  (nonempty / 'notes.txt').write_text('not mako\n')
  _touch_old(empty)
  _touch_old(nonempty)

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1)
  assert removed == []
  assert empty.exists()

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1, clean_legacy_empty=True)

  assert str(empty) in removed
  assert not empty.exists()
  assert nonempty.exists()


def test_cleanup_archive_tempdir(tmp_path):
  archive = tmp_path / 'hue_uploads'
  old_dir = archive / (ARCHIVE_TEMP_PREFIX + 'extract-old')
  fresh_dir = archive / (ARCHIVE_TEMP_PREFIX + 'extract-fresh')
  old_file = archive / (ARCHIVE_TEMP_PREFIX + 'old_part')
  fresh_file = archive / (ARCHIVE_TEMP_PREFIX + 'fresh_part')
  foreign_dir = archive / 'foreign-dir'
  foreign_file = archive / 'foreign_file'

  for directory in (old_dir, fresh_dir, foreign_dir):
    directory.mkdir(parents=True)
    (directory / 'file').write_text('data\n')
  old_file.write_text('data\n')
  fresh_file.write_text('data\n')
  foreign_file.write_text('data\n')

  _touch_old(old_dir)
  _touch_old(old_dir / 'file')
  _touch_old(old_file)
  _touch_old(foreign_dir)
  _touch_old(foreign_file)

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1)

  assert not old_dir.exists()
  assert not old_file.exists()
  assert fresh_dir.exists()
  assert fresh_file.exists()
  assert foreign_dir.exists()
  assert foreign_file.exists()
  assert archive.exists()
  assert str(old_dir) in removed
  assert str(foreign_dir) not in removed
  assert str(foreign_file) not in removed


def test_cleanup_archive_tempdir_legacy_requires_explicit_flag(tmp_path):
  archive = tmp_path / 'hue_uploads'
  legacy_dir = archive / 'extract-old'
  legacy_dir.mkdir(parents=True)
  (legacy_dir / 'file').write_text('data\n')
  _touch_old(legacy_dir)

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1)
  assert legacy_dir.exists()
  assert str(legacy_dir) not in removed

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1, clean_legacy=True)
  assert not legacy_dir.exists()
  assert str(legacy_dir) in removed


def test_cleanup_archive_tempdir_refuses_system_tempdir(tmp_path, monkeypatch):
  monkeypatch.setattr(temp_cleanup.tempfile, 'gettempdir', lambda: str(tmp_path))
  old_dir = tmp_path / (ARCHIVE_TEMP_PREFIX + 'old')
  old_dir.mkdir()
  (old_dir / 'file').write_text('data\n')
  _touch_old(old_dir)

  removed = temp_cleanup.cleanup_archive_tempdir(str(tmp_path), ttl_hours=1, clean_legacy=True)

  assert removed == []
  assert old_dir.exists()


def test_dry_run_does_not_delete(tmp_path):
  dead = tmp_path / ('hue_mako_%d_dead' % DEAD_PID)
  _make_mako_dir(dead)
  _touch_old(dead)

  removed = temp_cleanup.cleanup_mako_dirs(str(tmp_path), ttl_hours=1, dry_run=True)

  assert str(dead) in removed
  assert dead.exists()


def test_symlinks_are_not_followed(tmp_path):
  outside = tmp_path / 'outside'
  outside.mkdir()
  (outside / 'keep.txt').write_text('keep\n')

  root = tmp_path / 'tmpdir'
  root.mkdir()
  link = root / ('hue_mako_%d_link' % DEAD_PID)
  os.symlink(str(outside), str(link))

  temp_cleanup.cleanup_mako_dirs(str(root), ttl_hours=1)

  assert (outside / 'keep.txt').exists()
  assert os.path.islink(str(link))


def test_is_server_process():
  assert temp_cleanup.is_server_process(['hue', 'runserver'])
  assert temp_cleanup.is_server_process(['hue', 'rungunicornserver'])
  assert temp_cleanup.is_server_process(['hue', 'runcpserver'])
  assert not temp_cleanup.is_server_process(['hue', 'migrate'])
  assert not temp_cleanup.is_server_process(['hue'])


@pytest.mark.skipif(temp_cleanup.fcntl is None, reason='fcntl is unavailable on this platform')
def test_run_cleanup_locked_skips_when_lock_is_held(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(
    temp_cleanup,
    'run_cleanup',
    lambda **kwargs: calls.append(kwargs) or {
      'mako': [],
      'vault': [],
      'archive': [],
      'django_uploads': [],
      'indexer_staging': [],
      'indexer_config': [],
      'legacy_indexer_config': [],
    },
  )

  lock_path = str(tmp_path / 'cleanup.lock')
  file_descriptor = temp_cleanup._acquire_lock(lock_path)
  try:
    assert temp_cleanup.run_cleanup_locked(lock_path=lock_path) is None
    assert calls == []
  finally:
    temp_cleanup._release_lock(file_descriptor)

  result = temp_cleanup.run_cleanup_locked(lock_path=lock_path)

  assert result == {
    'mako': [],
    'vault': [],
    'archive': [],
    'django_uploads': [],
    'indexer_staging': [],
    'indexer_config': [],
    'legacy_indexer_config': [],
  }
  assert len(calls) == 1


def test_run_cleanup_loop_runs_until_stop(monkeypatch):
  calls = []
  first_run = threading.Event()

  def fake_cleanup_locked(**kwargs):
    calls.append(kwargs)
    first_run.set()
    return {'mako': [], 'vault': [], 'archive': []}

  monkeypatch.setattr(temp_cleanup, 'run_cleanup_locked', fake_cleanup_locked)
  stop_event = threading.Event()
  thread = threading.Thread(
    target=temp_cleanup.run_cleanup_loop,
    kwargs={'interval_seconds': 0.01, 'stop_event': stop_event},
    daemon=True,
  )

  thread.start()
  assert first_run.wait(1)
  stop_event.set()
  thread.join(1)

  assert not thread.is_alive()
  assert len(calls) >= 1


@pytest.mark.skipif(temp_cleanup.fcntl is None, reason='fcntl is unavailable on this platform')
def test_run_cleanup_locked_skips_when_lock_cannot_be_opened():
  assert temp_cleanup.run_cleanup_locked(lock_path='/nonexistent/hue-temp-cleanup.lock') is None


def test_in_process_is_disabled_by_default():
  enabled = TEMP_CLEANUP.ENABLED.set_for_testing(True)
  in_process = TEMP_CLEANUP.IN_PROCESS.set_for_testing(False)
  try:
    assert temp_cleanup.start_if_server_process(['hue', 'rungunicornserver']) is None
  finally:
    in_process()
    enabled()


def test_cleanup_archive_tempdir_keeps_active_chunk_group(tmp_path):
  archive = tmp_path / 'hue_uploads'
  archive.mkdir()
  upload_id = '11111111-2222-3333-4444-555555555555'
  old_part = archive / ('%s_0' % upload_id)
  fresh_part = archive / ('%s_1' % upload_id)
  old_other = archive / 'old_other'
  fresh_other = archive / 'fresh_other'

  old_part.write_text('part\n')
  fresh_part.write_text('part\n')
  old_other.write_text('old\n')
  fresh_other.write_text('fresh\n')
  _touch_old(old_part)
  _touch_old(old_other)

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1)

  assert old_part.exists()
  assert fresh_part.exists()
  assert old_other.exists()
  assert fresh_other.exists()
  assert str(old_other) not in removed
  assert str(old_part) not in removed


def test_cleanup_archive_tempdir_removes_old_chunk_group(tmp_path):
  archive = tmp_path / 'hue_uploads'
  archive.mkdir()
  upload_id = '11111111-2222-3333-4444-555555555555'
  part_0 = archive / ('%s_0' % upload_id)
  part_1 = archive / ('%s_1' % upload_id)

  part_0.write_text('part\n')
  part_1.write_text('part\n')
  _touch_old(part_0)
  _touch_old(part_1)

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1)

  assert not part_0.exists()
  assert not part_1.exists()
  assert str(part_0) in removed
  assert str(part_1) in removed


def test_cleanup_django_uploads_only_removes_upload_files(tmp_path):
  old_upload = tmp_path / 'tmpabc.upload.txt'
  fresh_upload = tmp_path / 'tmpdef.upload.csv'
  unrelated = tmp_path / 'tmpabc'
  old_upload.write_text('data\n')
  fresh_upload.write_text('data\n')
  unrelated.write_text('keep\n')
  _touch_old(old_upload)
  _touch_old(unrelated)

  removed = temp_cleanup.cleanup_django_uploads(str(tmp_path), ttl_hours=1)

  assert not old_upload.exists()
  assert fresh_upload.exists()
  assert unrelated.exists()
  assert str(old_upload) in removed


def test_cleanup_indexer_staging_only_removes_hue_staging(tmp_path):
  old_new = tmp_path / 'hue_indexer_alice_11111111-2222-3333-4444-555555555555:data;abc.csv'
  fresh_new = tmp_path / 'hue_indexer_alice_11111111-2222-3333-4444-555555555555:data;def.csv'
  old_legacy = tmp_path / 'alice_11111111-2222-3333-4444-555555555555:data;ghi.csv'
  unrelated = tmp_path / 'alice_notes.csv'
  for path in (old_new, fresh_new, old_legacy, unrelated):
    path.write_text('data\n')
  _touch_old(old_new)
  _touch_old(old_legacy)
  _touch_old(unrelated)

  removed = temp_cleanup.cleanup_indexer_staging(str(tmp_path), ttl_hours=1)

  assert not old_new.exists()
  assert fresh_new.exists()
  assert not old_legacy.exists()
  assert unrelated.exists()
  assert str(old_new) in removed
  assert str(old_legacy) in removed


def test_cleanup_indexer_config_dirs_only_removes_hue_prefix(tmp_path):
  old_config = tmp_path / 'hue_indexer_cfg_old'
  fresh_config = tmp_path / 'hue_indexer_cfg_fresh'
  unrelated = tmp_path / 'tmp_other'
  for directory in (old_config, fresh_config, unrelated):
    directory.mkdir()
  _touch_old(old_config)
  _touch_old(unrelated)

  removed = temp_cleanup.cleanup_indexer_config_dirs(str(tmp_path), ttl_hours=1)

  assert not old_config.exists()
  assert fresh_config.exists()
  assert unrelated.exists()
  assert str(old_config) in removed


def test_cleanup_legacy_indexer_config_dirs_by_signature(tmp_path):
  old_config = tmp_path / 'tmplegacyconfig'
  fresh_config = tmp_path / 'tmplegacyconfigfresh'
  foreign = tmp_path / 'tmpforeignconfig'
  for directory in (old_config, fresh_config, foreign):
    (directory / 'solr_configs' / 'conf').mkdir(parents=True)
    (directory / 'solr_configs' / 'conf' / 'solrconfig.xml').write_text('<config/>\n')
  _touch_old(old_config)
  _touch_old(old_config / 'solr_configs' / 'conf' / 'solrconfig.xml')
  _touch_old(foreign)
  (foreign / 'solr_configs' / 'conf' / 'solrconfig.xml').unlink()

  removed = temp_cleanup.cleanup_legacy_indexer_config_dirs(str(tmp_path), ttl_hours=1)

  assert str(old_config) in removed
  assert not old_config.exists()
  assert fresh_config.exists()
  assert foreign.exists()


def test_run_cleanup_includes_new_categories(monkeypatch, tmp_path):
  calls = {}
  archive_calls = []

  monkeypatch.setattr(temp_cleanup, 'cleanup_mako_dirs', lambda **kwargs: calls.setdefault('mako', []))
  monkeypatch.setattr(temp_cleanup, 'cleanup_vault_dirs', lambda **kwargs: calls.setdefault('vault', []))
  monkeypatch.setattr(
    temp_cleanup,
    'cleanup_archive_tempdir',
    lambda *args, **kwargs: archive_calls.append(kwargs) or calls.setdefault('archive', []),
  )
  monkeypatch.setattr(temp_cleanup, 'cleanup_django_uploads', lambda **kwargs: calls.setdefault('django_uploads', []))
  monkeypatch.setattr(temp_cleanup, 'cleanup_indexer_staging', lambda **kwargs: calls.setdefault('indexer_staging', []))
  monkeypatch.setattr(temp_cleanup, 'cleanup_indexer_config_dirs', lambda **kwargs: calls.setdefault('indexer_config', []))
  monkeypatch.setattr(temp_cleanup, 'cleanup_legacy_indexer_config_dirs', lambda **kwargs: calls.setdefault('legacy_indexer_config', []))

  result = temp_cleanup.run_cleanup(
    ttl_hours=1,
    dry_run=False,
    clean_legacy=False,
    clean_legacy_indexer_config=True,
    clean_legacy_archive=True,
  )

  assert set(result) == {
    'mako',
    'vault',
    'archive',
    'django_uploads',
    'indexer_staging',
    'indexer_config',
    'legacy_indexer_config',
  }
  assert set(calls) == set(result)
  assert archive_calls[0]['clean_legacy'] is True


def test_run_cleanup_skips_archive_category_when_disabled(monkeypatch):
  calls = []

  for name in (
    'cleanup_mako_dirs',
    'cleanup_vault_dirs',
    'cleanup_django_uploads',
    'cleanup_indexer_staging',
    'cleanup_indexer_config_dirs',
    'cleanup_legacy_indexer_config_dirs',
  ):
    monkeypatch.setattr(temp_cleanup, name, lambda **kwargs: [])
  monkeypatch.setattr(temp_cleanup, 'cleanup_archive_tempdir', lambda *args, **kwargs: calls.append(kwargs) or [])

  disabled = TEMP_CLEANUP.CLEAN_ARCHIVE_TEMPDIR.set_for_testing(False)
  try:
    result = temp_cleanup.run_cleanup(ttl_hours=1, dry_run=False)
  finally:
    disabled()

  assert result['archive'] == []
  assert calls == []


def test_dry_run_does_not_delete_new_categories(tmp_path):
  old_upload = tmp_path / 'tmpabc.upload.txt'
  old_config = tmp_path / 'hue_indexer_cfg_old'
  old_upload.write_text('data\n')
  old_config.mkdir()
  _touch_old(old_upload)
  _touch_old(old_config)

  removed_uploads = temp_cleanup.cleanup_django_uploads(str(tmp_path), ttl_hours=1, dry_run=True)
  removed_config = temp_cleanup.cleanup_indexer_config_dirs(str(tmp_path), ttl_hours=1, dry_run=True)

  assert str(old_upload) in removed_uploads
  assert str(old_config) in removed_config
  assert old_upload.exists()
  assert old_config.exists()


def test_loop_command_exits_when_disabled():
  enabled = TEMP_CLEANUP.ENABLED.set_for_testing(False)
  try:
    output = StringIO()
    call_command('temp_cleanup', '--loop', stdout=output)
    assert 'disabled' in output.getvalue().lower()
  finally:
    enabled()


def test_zombie_process_is_not_alive():
  if not os.path.isdir('/proc'):
    pytest.skip('procfs is unavailable on this platform')

  child = subprocess.Popen(['/bin/true'])
  try:
    time.sleep(0.2)
    assert not temp_cleanup._is_process_alive(child.pid)
  finally:
    child.wait()
