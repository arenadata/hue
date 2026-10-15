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
import base64
from unittest import mock

import pytest
from hvac.exceptions import Forbidden

from desktop.lib import vault_client
from desktop.lib.vault_client import VaultClient, VaultSecretResolver
from desktop.lib.vault_conf import VaultConfig

LOGIN_OK = {'auth': {'client_token': 'client-token-1', 'lease_duration': 300, 'renewable': False}}
TOKEN_BYTES = b'krb5-ap-req'
EXPECTED_AUTHORIZATION = 'Negotiate %s' % base64.b64encode(TOKEN_BYTES).decode('ascii')


def kerberos_config(**kwargs):
  params = dict(url='https://vault.corp:8200', auth_type='kerberos')
  params.update(kwargs)
  return VaultConfig(**params)


@pytest.fixture
def fake_gssapi():
  gssapi = mock.MagicMock(name='gssapi')
  gssapi.SecurityContext.return_value.step.return_value = TOKEN_BYTES
  with mock.patch.object(vault_client, 'gssapi', gssapi, create=True), \
      mock.patch.object(vault_client, 'HAS_GSSAPI', True, create=True):
    yield gssapi


@pytest.fixture
def fake_hvac_client():
  with mock.patch.object(vault_client, 'hvac') as hvac_mock:
    hvac_mock.Client.return_value.adapter.post.return_value = dict(LOGIN_OK)
    yield hvac_mock.Client.return_value


class TestKerberosLogin:

  def test_sets_token_and_posts_to_default_mount(self, fake_gssapi, fake_hvac_client):
    client = VaultClient(kerberos_config())

    assert client.is_initialized
    fake_hvac_client.adapter.post.assert_called_once_with(
        '/v1/auth/kerberos/login', json={}, headers={'Authorization': EXPECTED_AUTHORIZATION})
    assert fake_hvac_client.token == 'client-token-1'

  def test_custom_mount_point_and_role(self, fake_gssapi, fake_hvac_client):
    client = VaultClient(kerberos_config(auth_mount_point='krb5', kerberos_role='hue-role'))

    assert client.is_initialized
    fake_hvac_client.adapter.post.assert_called_once_with(
        '/v1/auth/krb5/login', json={'role': 'hue-role'}, headers={'Authorization': EXPECTED_AUTHORIZATION})

  def test_default_target_name_is_hostbased_service(self, fake_gssapi, fake_hvac_client):
    VaultClient(kerberos_config())

    fake_gssapi.Name.assert_called_once_with('HTTP@vault.corp', fake_gssapi.NameType.hostbased_service)

  def test_service_principal_override_uses_kerberos_principal(self, fake_gssapi, fake_hvac_client):
    VaultClient(kerberos_config(kerberos_service_principal='HTTP/vault.lb.corp@CORP'))

    fake_gssapi.Name.assert_called_once_with('HTTP/vault.lb.corp@CORP', fake_gssapi.NameType.kerberos_principal)

  def test_keytab_and_ccache_passed_in_cred_store(self, fake_gssapi, fake_hvac_client):
    VaultClient(kerberos_config(keytab_path='/etc/hue.keytab', principal='hue/node.corp@CORP', ccache_path='/var/run/hue/vault_ccache'))

    _, kwargs = fake_gssapi.Credentials.call_args
    assert kwargs['usage'] == 'initiate'
    assert kwargs['store'] == {'client_keytab': '/etc/hue.keytab', 'ccache': 'FILE:/var/run/hue/vault_ccache'}

  def test_dedicated_ccache_derived_when_keytab_without_ccache(self, fake_gssapi, fake_hvac_client):
    VaultClient(kerberos_config(keytab_path='/etc/hue.keytab', principal='hue/node.corp@CORP'))

    _, kwargs = fake_gssapi.Credentials.call_args
    assert kwargs['store']['client_keytab'] == '/etc/hue.keytab'
    assert kwargs['store']['ccache'].startswith('FILE:')
    assert 'hue_vault_ccache' in kwargs['store']['ccache']

  def test_krb5_conf_path_sets_krb5_config(self, fake_gssapi, fake_hvac_client):
    with mock.patch.dict(os.environ, {}, clear=False):
      os.environ.pop('KRB5_CONFIG', None)
      client = VaultClient(kerberos_config(krb5_conf_path='/custom/krb5.conf'))

      assert client.is_initialized
      assert os.environ['KRB5_CONFIG'] == '/custom/krb5.conf'

  def test_login_error_response_leaves_client_uninitialized(self, fake_gssapi, fake_hvac_client):
    response = mock.Mock(status_code=401)
    response.json.return_value = {'errors': ['SPNEGO authentication failed']}
    fake_hvac_client.adapter.post.return_value = response

    client = VaultClient(kerberos_config())

    assert not client.is_initialized
    assert fake_hvac_client.adapter.post.called

  def test_missing_gssapi_disables_login(self, fake_hvac_client, caplog):
    with mock.patch.object(vault_client, 'gssapi', None, create=True), \
        mock.patch.object(vault_client, 'HAS_GSSAPI', False, create=True):
      client = VaultClient(kerberos_config())

    assert not client.is_initialized
    assert not fake_hvac_client.adapter.post.called
    assert any('gssapi' in record.message for record in caplog.records)


class TestTokenRelogin:

  def test_forbidden_triggers_spnego_relogin_and_retry(self, fake_gssapi, fake_hvac_client):
    fake_hvac_client.adapter.post.side_effect = [dict(LOGIN_OK), dict(LOGIN_OK)]
    fake_hvac_client.secrets.kv.v2.read_secret_version.side_effect = [
        Forbidden(),
        {'data': {'data': {'value': 's3cr3t'}}},
    ]
    client = VaultClient(kerberos_config())

    secret = client.get_secret('db/password')

    assert secret == 's3cr3t'
    assert fake_hvac_client.adapter.post.call_count == 2
    assert fake_hvac_client.secrets.kv.v2.read_secret_version.call_count == 2


class TestResolverClientCaching:

  def config(self):
    return VaultConfig(url='https://vault.corp:8200', auth_type='token', token='tok')

  def test_initialized_client_is_reused_across_resolves(self):
    with mock.patch.object(vault_client, 'VaultClient') as vault_client_class:
      vault_client_class.return_value.is_initialized = True
      vault_client_class.return_value.get_secret.return_value = 's3cr3t'
      resolver = VaultSecretResolver(self.config())

      assert resolver.resolve('vault://db/password') == 's3cr3t'
      assert resolver.resolve('vault://db/password') == 's3cr3t'

      assert vault_client_class.call_count == 1

  def test_failed_client_is_dropped_for_next_resolve(self):
    with mock.patch.object(vault_client, 'VaultClient') as vault_client_class:
      vault_client_class.return_value.is_initialized = False
      resolver = VaultSecretResolver(self.config())

      assert resolver.resolve('vault://db/password') is None
      assert resolver._client is None

      assert resolver.resolve('vault://db/password') is None
      assert vault_client_class.call_count == 2
