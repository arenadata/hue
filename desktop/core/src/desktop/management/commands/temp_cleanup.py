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

import signal
import threading

from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from desktop.conf import TEMP_CLEANUP
from desktop.lib.temp_cleanup import run_cleanup_locked, run_cleanup_loop


class Command(BaseCommand):
  help = _(
    """
    Remove stale temporary files and directories created by Hue.

    By default only artifacts owned by Hue and older than temp_cleanup.ttl_hours are removed.
    Use --legacy to also remove the anonymous tmp* Mako module directories left by older
    Hue versions. For a safe one-time cleanup, restart Hue first and then run this command.

    Use --loop to run a dedicated background worker. It is intended to be managed by
    supervisor/systemd, not by the Hue web processes.
    """
  )

  def add_arguments(self, parser):
    parser.add_argument(
      '--ttl-hours',
      type=int,
      default=None,
      help=_('Only remove artifacts older than this many hours. Defaults to temp_cleanup.ttl_hours.')
    )
    parser.add_argument(
      '--dry-run',
      action='store_true',
      default=None,
      help=_('Only log what would be removed. Defaults to temp_cleanup.dry_run.')
    )
    parser.add_argument(
      '--legacy',
      action='store_true',
      default=None,
      help=_('Also remove legacy anonymous tmp* Mako module directories created by older Hue versions.')
    )
    parser.add_argument(
      '--legacy-empty-mako',
      action='store_true',
      default=None,
      help=_('Also remove empty legacy Mako directories during an explicit upgrade cleanup.')
    )
    parser.add_argument(
      '--legacy-indexer-config',
      action='store_true',
      default=None,
      help=_('Also remove legacy anonymous indexer copy_configs temporary directories.')
    )
    parser.add_argument(
      '--loop',
      action='store_true',
      default=False,
      help=_('Run the cleanup continuously as a background worker.')
    )
    parser.add_argument(
      '--interval-seconds',
      type=int,
      default=None,
      help=_('Worker interval in seconds. Defaults to temp_cleanup.interval_seconds.')
    )

  def handle(self, *args, **options):
    ttl_hours = options['ttl_hours'] if options['ttl_hours'] is not None else TEMP_CLEANUP.TTL_HOURS.get()
    dry_run = options['dry_run'] if options['dry_run'] is not None else TEMP_CLEANUP.DRY_RUN.get()
    clean_legacy = options['legacy'] if options['legacy'] is not None else TEMP_CLEANUP.CLEAN_LEGACY_MAKO_DIRS.get()
    clean_legacy_empty = (
      options['legacy_empty_mako']
      if options['legacy_empty_mako'] is not None else TEMP_CLEANUP.CLEAN_LEGACY_EMPTY_MAKO_DIRS.get()
    )
    clean_legacy_indexer_config = (
      options['legacy_indexer_config']
      if options['legacy_indexer_config'] is not None else TEMP_CLEANUP.CLEAN_LEGACY_INDEXER_CONFIG_TEMPS.get()
    )
    clean_legacy_vault = TEMP_CLEANUP.CLEAN_LEGACY_VAULT_DIRS.get()

    if ttl_hours < 0:
      raise ValueError('--ttl-hours must not be negative')

    if options['loop']:
      if not TEMP_CLEANUP.ENABLED.get():
        self.stdout.write(self.style.WARNING('Temporary cleanup is disabled (temp_cleanup.enabled=False).'))
        return

      interval_seconds = (
        options['interval_seconds'] if options['interval_seconds'] is not None else TEMP_CLEANUP.INTERVAL_SECONDS.get()
      )
      if interval_seconds <= 0:
        raise ValueError('--interval-seconds must be greater than zero')

      stop_event = threading.Event()
      previous_handlers = {}

      def _stop(signum, frame):
        stop_event.set()

      for signum in (signal.SIGTERM, signal.SIGINT):
        try:
          previous_handlers[signum] = signal.signal(signum, _stop)
        except (OSError, ValueError):
          pass

      try:
        run_cleanup_loop(
          interval_seconds=interval_seconds,
          ttl_hours=ttl_hours,
          dry_run=dry_run,
          clean_legacy=clean_legacy,
          clean_legacy_empty=clean_legacy_empty,
          clean_legacy_vault=clean_legacy_vault,
          clean_legacy_indexer_config=clean_legacy_indexer_config,
          stop_event=stop_event,
        )
      finally:
        for signum, handler in previous_handlers.items():
          signal.signal(signum, handler)
      return

    result = run_cleanup_locked(
      ttl_hours=ttl_hours,
      dry_run=dry_run,
      clean_legacy=clean_legacy,
      clean_legacy_empty=clean_legacy_empty,
      clean_legacy_vault=clean_legacy_vault,
      clean_legacy_indexer_config=clean_legacy_indexer_config,
    )

    if result is None:
      self.stdout.write(self.style.WARNING('Skipped: another Hue temporary cleanup is already running.'))
      return

    self.stdout.write(
      self.style.SUCCESS(
        'Removed mako=%d vault=%d archive=%d django_uploads=%d indexer_staging=%d indexer_config=%d '
        'legacy_indexer_config=%d item(s) (ttl_hours=%d, dry_run=%s, legacy=%s, legacy_empty=%s)'
        % (
          len(result['mako']),
          len(result['vault']),
          len(result['archive']),
          len(result['django_uploads']),
          len(result['indexer_staging']),
          len(result['indexer_config']),
          len(result['legacy_indexer_config']),
          ttl_hours,
          dry_run,
          clean_legacy,
          clean_legacy_empty,
        )
      )
    )
