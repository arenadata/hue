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
import re
import sys
import time
import shutil
import logging
import tempfile
import threading

from desktop.conf import TEMP_CLEANUP

try:
  import fcntl
except ImportError:
  fcntl = None

LOG = logging.getLogger(__name__)

MAKO_DIR_PREFIX = 'hue_mako_'
VAULT_DIR_PREFIX = 'hue_vault_'
LOCK_FILE_NAME = 'hue_temp_cleanup.lock'
SERVER_COMMANDS = ('runserver', 'rungunicornserver', 'runcpserver')

_service = None
_service_guard = threading.Lock()


def _cutoff(ttl_hours):
  return time.time() - ttl_hours * 3600


def _is_old(path, cutoff):
  try:
    return os.lstat(path).st_mtime < cutoff
  except OSError:
    return False


def _pid_from_name(name, prefix):
  match = re.match(r'^%s(\d+)_' % re.escape(prefix), name)
  return int(match.group(1)) if match else None


def _is_process_alive(pid):
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  except OSError:
    return False
  return True


def _remove_dir(path, root, dry_run):
  try:
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    if real_path == real_root or os.path.commonpath([real_root, real_path]) != real_root:
      LOG.warning('Refusing to remove a path outside of %s: %s', root, path)
      return False
  except (OSError, ValueError):
    LOG.warning('Refusing to remove a path that cannot be validated: %s', path)
    return False

  if dry_run:
    LOG.info('[dry-run] Would remove directory %s', path)
    return True

  try:
    shutil.rmtree(path)
    LOG.info('Removed directory %s', path)
    return True
  except OSError as error:
    LOG.warning('Failed to remove directory %s: %s', path, error)
    return False


def _remove_file(path, dry_run):
  if dry_run:
    LOG.info('[dry-run] Would remove file %s', path)
    return True
  try:
    os.unlink(path)
    LOG.info('Removed file %s', path)
    return True
  except OSError as error:
    LOG.warning('Failed to remove file %s: %s', path, error)
    return False


def _is_mako_module_dir(path):
  found_mako = False
  for current, dirs, files in os.walk(path):
    dirs[:] = [directory for directory in dirs if not os.path.islink(os.path.join(current, directory))]
    for name in files:
      if name.endswith('.mako.py'):
        found_mako = True
      elif not name.endswith(('.py', '.pyc', '.pyo')):
        return False
  return found_mako


def _cleanup_prefixed_dirs(root, prefix, ttl_hours, dry_run, clean_legacy):
  cutoff = _cutoff(ttl_hours)
  removed = []
  try:
    entries = os.scandir(root)
  except OSError as error:
    LOG.warning('Cannot scan %s: %s', root, error)
    return removed

  with entries:
    for entry in entries:
      try:
        if not entry.is_dir(follow_symlinks=False) or not entry.name.startswith(prefix):
          continue
      except OSError:
        continue

      pid = _pid_from_name(entry.name, prefix)
      if pid is not None and _is_process_alive(pid):
        continue
      if pid is None and not clean_legacy:
        continue
      if not _is_old(entry.path, cutoff):
        continue
      if _remove_dir(entry.path, root, dry_run):
        removed.append(entry.path)

  return removed


def cleanup_mako_dirs(root=None, ttl_hours=None, dry_run=False, clean_legacy=False):
  root = root or tempfile.gettempdir()
  ttl_hours = TEMP_CLEANUP.TTL_HOURS.get() if ttl_hours is None else ttl_hours
  removed = _cleanup_prefixed_dirs(root, MAKO_DIR_PREFIX, ttl_hours, dry_run, clean_legacy)

  if clean_legacy:
    cutoff = _cutoff(ttl_hours)
    try:
      entries = os.scandir(root)
    except OSError as error:
      LOG.warning('Cannot scan %s: %s', root, error)
      return removed

    with entries:
      for entry in entries:
        try:
          if (
            not entry.is_dir(follow_symlinks=False)
            or not entry.name.startswith('tmp')
            or not _is_old(entry.path, cutoff)
            or not _is_mako_module_dir(entry.path)
          ):
            continue
        except OSError:
          continue
        if _remove_dir(entry.path, root, dry_run):
          removed.append(entry.path)

  return removed


def cleanup_vault_dirs(root=None, ttl_hours=None, dry_run=False, clean_legacy=False):
  root = root or tempfile.gettempdir()
  ttl_hours = TEMP_CLEANUP.TTL_HOURS.get() if ttl_hours is None else ttl_hours
  return _cleanup_prefixed_dirs(root, VAULT_DIR_PREFIX, ttl_hours, dry_run, clean_legacy)


def cleanup_archive_tempdir(directory, ttl_hours=None, dry_run=False):
  ttl_hours = TEMP_CLEANUP.TTL_HOURS.get() if ttl_hours is None else ttl_hours
  cutoff = _cutoff(ttl_hours)
  removed = []

  if not directory or not os.path.isdir(directory):
    return removed

  try:
    entries = os.scandir(directory)
  except OSError as error:
    LOG.warning('Cannot scan %s: %s', directory, error)
    return removed

  with entries:
    for entry in entries:
      try:
        if not _is_old(entry.path, cutoff):
          continue
        if entry.is_dir(follow_symlinks=False):
          if _remove_dir(entry.path, directory, dry_run):
            removed.append(entry.path)
        elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
          if _remove_file(entry.path, dry_run):
            removed.append(entry.path)
      except OSError:
        continue

  return removed


def _get_archive_tempdir():
  try:
    from filebrowser.conf import ARCHIVE_UPLOAD_TEMPDIR
    return ARCHIVE_UPLOAD_TEMPDIR.get()
  except Exception as error:
    LOG.debug('Cannot read the filebrowser archive temp directory: %s', error)
    return None


def run_cleanup(ttl_hours=None, dry_run=None, clean_legacy=None):
  ttl_hours = TEMP_CLEANUP.TTL_HOURS.get() if ttl_hours is None else ttl_hours
  dry_run = TEMP_CLEANUP.DRY_RUN.get() if dry_run is None else dry_run
  clean_legacy = TEMP_CLEANUP.CLEAN_LEGACY_MAKO_DIRS.get() if clean_legacy is None else clean_legacy

  result = {
    'mako': cleanup_mako_dirs(ttl_hours=ttl_hours, dry_run=dry_run, clean_legacy=clean_legacy),
    'vault': cleanup_vault_dirs(ttl_hours=ttl_hours, dry_run=dry_run, clean_legacy=clean_legacy),
    'archive': cleanup_archive_tempdir(_get_archive_tempdir(), ttl_hours=ttl_hours, dry_run=dry_run),
  }
  LOG.info(
    'Hue temporary cleanup removed %d item(s): mako=%d vault=%d archive=%d (ttl_hours=%s, dry_run=%s)',
    sum(len(items) for items in result.values()),
    len(result['mako']),
    len(result['vault']),
    len(result['archive']),
    ttl_hours,
    dry_run,
  )
  return result


def _acquire_lock(lock_path):
  if fcntl is None:
    return -1
  try:
    file_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
  except OSError as error:
    LOG.warning('Cannot open Hue temporary cleanup lock %s: %s', lock_path, error)
    return None
  try:
    fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except OSError:
    os.close(file_descriptor)
    return None
  return file_descriptor


def _release_lock(file_descriptor):
  if fcntl is None or file_descriptor is None or file_descriptor < 0:
    return
  try:
    fcntl.flock(file_descriptor, fcntl.LOCK_UN)
  finally:
    os.close(file_descriptor)


def _lock_path(lock_path=None):
  return lock_path or os.path.join(tempfile.gettempdir(), LOCK_FILE_NAME)


def run_cleanup_locked(ttl_hours=None, dry_run=None, clean_legacy=None, lock_path=None):
  file_descriptor = _acquire_lock(_lock_path(lock_path))
  if file_descriptor is None:
    LOG.info('Hue temporary cleanup skipped: another cleanup is already running')
    return None
  try:
    return run_cleanup(ttl_hours=ttl_hours, dry_run=dry_run, clean_legacy=clean_legacy)
  finally:
    _release_lock(file_descriptor)


def run_cleanup_loop(interval_seconds, ttl_hours=None, dry_run=None, clean_legacy=None, lock_path=None, stop_event=None):
  stop_event = stop_event or threading.Event()
  LOG.info('Hue temporary cleanup worker started (interval=%ss)', interval_seconds)

  while not stop_event.is_set():
    try:
      run_cleanup_locked(
        ttl_hours=ttl_hours,
        dry_run=dry_run,
        clean_legacy=clean_legacy,
        lock_path=lock_path,
      )
    except Exception as error:
      LOG.warning('Hue temporary cleanup failed: %s', error)
    if stop_event.wait(interval_seconds):
      break

  LOG.info('Hue temporary cleanup worker stopped')


class TempCleanupService(object):
  def __init__(self, interval_seconds, ttl_hours, dry_run, clean_legacy, lock_path=None):
    self.interval_seconds = interval_seconds
    self.ttl_hours = ttl_hours
    self.dry_run = dry_run
    self.clean_legacy = clean_legacy
    self.lock_path = lock_path or os.path.join(tempfile.gettempdir(), LOCK_FILE_NAME)
    self._stop_event = threading.Event()
    self._thread = None

  def start(self):
    if self._thread is not None:
      return
    self._thread = threading.Thread(target=self._run, name='hue-temp-cleanup', daemon=True)
    self._thread.start()
    LOG.info(
      'Hue temporary cleanup started (interval=%ss, ttl=%sh, dry_run=%s)',
      self.interval_seconds,
      self.ttl_hours,
      self.dry_run,
    )

  def is_alive(self):
    return self._thread is not None and self._thread.is_alive()

  def stop(self):
    self._stop_event.set()

  def _run(self):
    while not self._stop_event.is_set():
      self._run_once()
      if self._stop_event.wait(self.interval_seconds):
        break

  def _run_once(self):
    try:
      run_cleanup_locked(
        ttl_hours=self.ttl_hours,
        dry_run=self.dry_run,
        clean_legacy=self.clean_legacy,
        lock_path=self.lock_path,
      )
    except Exception as error:
      LOG.warning('Hue temporary cleanup failed: %s', error)


def is_server_process(argv=None):
  argv = sys.argv if argv is None else argv
  if len(argv) < 2:
    return False
  return os.path.basename(argv[1]) in SERVER_COMMANDS


def start_temp_cleanup_service():
  global _service

  if not TEMP_CLEANUP.ENABLED.get() or not TEMP_CLEANUP.IN_PROCESS.get():
    return None

  with _service_guard:
    if _service is not None and _service.is_alive():
      return _service
    _service = TempCleanupService(
      interval_seconds=TEMP_CLEANUP.INTERVAL_SECONDS.get(),
      ttl_hours=TEMP_CLEANUP.TTL_HOURS.get(),
      dry_run=TEMP_CLEANUP.DRY_RUN.get(),
      clean_legacy=TEMP_CLEANUP.CLEAN_LEGACY_MAKO_DIRS.get(),
    )
    _service.start()
    return _service


def start_if_server_process(argv=None):
  if not is_server_process(argv):
    return None
  return start_temp_cleanup_service()
