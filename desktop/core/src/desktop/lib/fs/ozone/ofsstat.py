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

from builtins import oct

from django.utils.encoding import smart_str

from desktop.lib.fs.ozone import _serviceid_join, join as ofs_join
from hadoop.fs.webhdfs_types import WebHdfsStat


class OzoneFSStat(WebHdfsStat):
  """
  Information about a path in Ozone.

  Modelled after org.apache.hadoop.fs.FileStatus
  """

  def __init__(self, file_status, parent_path, ofs_serviceid=''):
    super(OzoneFSStat, self).__init__(file_status, parent_path)

    # Check for edge case when volume name is equal to service_id,
    # then forcefully append ofs://<service_id> in current path so that further directory level paths are consistent.
    is_vol_serviceid_equal = parent_path.startswith(f'/{ofs_serviceid}')
    self.path = _serviceid_join(ofs_join(parent_path, self.name), ofs_serviceid, is_vol_serviceid_equal)

  def __unicode__(self):
    return "[OzoneFSStat] %7s %8s %8s %12s %s%s" % (oct(self.mode), self.user, self.group, self.size, self.path, self.isDir and '/' or "")

  def __repr__(self):
    return smart_str("<OzoneFSStat %s>" % (self.path))
