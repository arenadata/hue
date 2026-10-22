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
from io import StringIO

import pytest
from django.core.management import call_command

from desktop.conf import TEMP_CLEANUP
from desktop.lib import temp_cleanup

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


def test_cleanup_archive_tempdir(tmp_path):
  archive = tmp_path / 'hue_uploads'
  old_dir = archive / 'extract-old'
  fresh_dir = archive / 'extract-fresh'
  old_file = archive / 'old_part'
  fresh_file = archive / 'fresh_part'

  for directory in (old_dir, fresh_dir):
    directory.mkdir(parents=True)
    (directory / 'file').write_text('data\n')
  old_file.write_text('data\n')
  fresh_file.write_text('data\n')

  _touch_old(old_dir)
  _touch_old(old_dir / 'file')
  _touch_old(old_file)

  removed = temp_cleanup.cleanup_archive_tempdir(str(archive), ttl_hours=1)

  assert not old_dir.exists()
  assert not old_file.exists()
  assert fresh_dir.exists()
  assert fresh_file.exists()
  assert archive.exists()
  assert str(old_dir) in removed


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
    lambda **kwargs: calls.append(kwargs) or {'mako': [], 'vault': [], 'archive': []},
  )

  lock_path = str(tmp_path / 'cleanup.lock')
  file_descriptor = temp_cleanup._acquire_lock(lock_path)
  try:
    assert temp_cleanup.run_cleanup_locked(lock_path=lock_path) is None
    assert calls == []
  finally:
    temp_cleanup._release_lock(file_descriptor)

  result = temp_cleanup.run_cleanup_locked(lock_path=lock_path)

  assert result == {'mako': [], 'vault': [], 'archive': []}
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


def test_loop_command_exits_when_disabled():
  enabled = TEMP_CLEANUP.ENABLED.set_for_testing(False)
  try:
    output = StringIO()
    call_command('temp_cleanup', '--loop', stdout=output)
    assert 'disabled' in output.getvalue().lower()
  finally:
    enabled()
