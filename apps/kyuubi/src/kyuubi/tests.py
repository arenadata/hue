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

import pytest

from useradmin.models import GroupPermission, HuePermission, get_default_user_group


@pytest.mark.django_db
def test_kyuubi_access_permission_exists():
  actions = set(HuePermission.objects.filter(app='kyuubi').values_list('action', flat=True))
  assert 'access' in actions


@pytest.mark.django_db
def test_default_group_has_kyuubi_access():
  default_group = get_default_user_group()
  assert default_group is not None
  assert GroupPermission.objects.filter(
    group=default_group,
    hue_permission__app='kyuubi',
    hue_permission__action='access',
  ).exists()
