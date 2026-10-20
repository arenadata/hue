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

from desktop.lib.conf import Config, ConfigSection, UnspecifiedConfigSection, coerce_bool, coerce_string

# Used only for ZooKeeper app properties, ZooKeeper specific properties should come from libzookeeper
CLUSTERS = UnspecifiedConfigSection(
  "clusters",
  help="One entry for each Zookeeper cluster",
  each=ConfigSection(
    help="Information about a single Zookeeper cluster",
    members=dict(
      HOST_PORTS=Config(
          "host_ports",
          help="Zookeeper ensemble. Comma separated list of Host/Port, e.g. localhost:2181,localhost:2182,localhost:2183",
          default="localhost:2181",
          type=coerce_string,
      ),
      REST_URL=Config(
          "rest_url",
          help="The URL of the REST contrib service.",
          default="http://localhost:9998",
          type=str,
      ),
      ADMIN_PORT=Config(
          "admin_port",
          help="Admin server port on each member; when set, stats/clients use its /commands endpoint over plain HTTP",
          default=None,
          type=int,
      ),
      SECURITY_ENABLED=Config(
          "security_enabled",
          help="Is the REST service running with Kerberos (SPNEGO) authentication",
          default=False,
          type=coerce_bool,
      ),
      SSL_CERT_CA_VERIFY=Config(
          "ssl_cert_ca_verify",
          help="In secure mode (HTTPS), if the SSL certificate of the REST service has to be verified against certificate authority",
          default=False,
          type=coerce_bool,
      ),
      PRINCIPAL_NAME=Config(
          "principal_name",
          help="Name of Kerberos principal when using security",
          default="zookeeper",
          type=str,
      ),
    )
  )
)
