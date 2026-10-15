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

import pytest

from desktop.lib.vault_conf import VaultConfig


class TestVaultConfigKerberos:

  def test_keytab_requires_principal(self):
    with pytest.raises(ValueError, match='[Pp]rincipal'):
      VaultConfig(url='https://vault.corp:8200', auth_type='kerberos', keytab_path='/etc/hue.keytab')

  def test_keytab_with_principal_is_valid(self):
    config = VaultConfig(
        url='https://vault.corp:8200',
        auth_type='kerberos',
        keytab_path='/etc/hue.keytab',
        principal='hue/node.corp@CORP',
    )
    assert config.auth_type == 'kerberos'

  def test_ccache_only_is_valid(self):
    config = VaultConfig(url='https://vault.corp:8200', auth_type='kerberos')
    assert config.auth_type == 'kerberos'

  def test_ip_url_rejected_without_service_principal(self):
    with pytest.raises(ValueError, match='IP'):
      VaultConfig(url='https://127.0.0.1:8200', auth_type='kerberos')

  def test_ip_url_allowed_with_service_principal(self):
    config = VaultConfig(
        url='https://127.0.0.1:8200',
        auth_type='kerberos',
        kerberos_service_principal='HTTP/vault.corp@CORP',
    )
    assert config.kerberos_service_principal == 'HTTP/vault.corp@CORP'

  def test_token_still_valid(self):
    config = VaultConfig(url='https://vault.corp:8200', auth_type='token', token='tok')
    assert config.auth_type == 'token'
