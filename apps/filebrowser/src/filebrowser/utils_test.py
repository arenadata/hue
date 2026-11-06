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
import uuid

from filebrowser.conf import ARCHIVE_UPLOAD_TEMPDIR
from filebrowser.utils import cleanup_upload_chunks, generate_chunks


def _write_parts(upload_id, total_parts, size=1024):
  directory = ARCHIVE_UPLOAD_TEMPDIR.get()
  os.makedirs(directory, exist_ok=True)
  for index in range(total_parts):
    with open(os.path.join(directory, '%s_%d' % (upload_id, index)), 'wb') as output:
      output.write(b'x' * size)


def _part_paths(upload_id, total_parts):
  return [os.path.join(ARCHIVE_UPLOAD_TEMPDIR.get(), '%s_%d' % (upload_id, index)) for index in range(total_parts)]


def test_cleanup_upload_chunks_removes_all_parts():
  upload_id = str(uuid.uuid4())
  _write_parts(upload_id, 2)

  cleanup_upload_chunks(upload_id, 2)

  assert not any(os.path.exists(path) for path in _part_paths(upload_id, 2))


def test_generate_chunks_cleans_parts_when_consumer_closes_early():
  upload_id = str(uuid.uuid4())
  _write_parts(upload_id, 2, size=1024 * 1024 + 1)

  generator = generate_chunks(upload_id, 2, default_write_size=1024 * 1024)
  next(generator)
  generator.close()

  assert not any(os.path.exists(path) for path in _part_paths(upload_id, 2))
