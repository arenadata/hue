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

DJANGO_APPS = ['kyuubi']
NICE_NAME = 'Kyuubi'
MENU_INDEX = -1

REQUIRES_HADOOP = False
IS_URL_NAMESPACED = True

# Per-engine access permissions for granular control over multiple Kyuubi engines.
# Each entry creates a separate HuePermission record (app='kyuubi', action=<action>).
# Naming convention: interpreter key 'kyuubi_<engine>' maps to action 'access_<engine>'.
# Example hue.ini section for Spark 3 engine: [[[kyuubi_spark3]]]
PERMISSION_ACTIONS = (
  ('access_spark3', 'Access Kyuubi with Spark 3 engine'),
  ('access_spark2', 'Access Kyuubi with Spark 2 engine'),
)
