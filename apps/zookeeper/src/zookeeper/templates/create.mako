## Licensed to Cloudera, Inc. under one
## or more contributor license agreements.  See the NOTICE file
## distributed with this work for additional information
## regarding copyright ownership.  Cloudera, Inc. licenses this file
## to you under the Apache License, Version 2.0 (the
## "License"); you may not use this file except in compliance
## with the License.  You may obtain a copy of the License at
##
##     http://www.apache.org/licenses/LICENSE-2.0
##
## Unless required by applicable law or agreed to in writing, software
## distributed under the License is distributed on an "AS IS" BASIS,
## WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
## See the License for the specific language governing permissions and
## limitations under the License.

<%!
  import sys
  from desktop.views import commonheader, commonfooter
  if sys.version_info[0] > 2:
    from django.utils.translation import gettext as _
  else:
    from django.utils.translation import ugettext as _
%>

<%namespace name="shared" file="shared_components.mako" />

%if not is_embeddable:
${ commonheader("ZooKeeper Browser > Create Znode", app_name, user, request) | n,unicode }
${ shared.menubar() }
%endif
<%
  _split = path.split("/");
  _breadcrumbs = [
    [_("Home"), url('zookeeper:index')],
    [cluster['nice_name'].lower(), url('zookeeper:view', id=cluster['id'])],
  ]
  for idx, p in enumerate(_split):
    if p != "":
      _breadcrumbs.append([p, url('zookeeper:tree', id=cluster['id'], path= "/".join(_split[:idx+1]))]);

  _breadcrumbs.append([_('New Znode'), ""]);
%>

${ shared.header(_breadcrumbs, clusters) }

<div id="createZnodeError" class="alert alert-error hide"></div>

<form class="createZnodeForm" action="${url('zookeeper:create', id=cluster['id'], path=path)}" method="POST">
  ${ csrf_token(request) | n,unicode }
  ${form.as_table()|n}
  <br/>
  <br/>
  <input type="submit" class="btn btn-primary" value="${ _('Create Znode') }">
  <a class="btn" href="${url('zookeeper:tree', id=cluster['id'], path=path)}">${ _('Cancel') }</a>
</form>

<script type="text/javascript">
  $(document).ready(function () {
    var $form = $(".createZnodeForm");
    var $error = $("#createZnodeError");

    $form.on("submit", function (event) {
      event.preventDefault();
      $error.addClass("hide").text("");

      $.post($form.attr("action"), $form.serialize(), function (data) {
        var currentPath = window.location.pathname;
        var appIndex = currentPath.indexOf("/zookeeper/");
        var base = appIndex > 0 ? currentPath.substring(0, appIndex) : "";
        location.href = base + data.redirect;
      }).fail(function (xhr) {
        var response = xhr.responseJSON || {};
        $error.removeClass("hide").text(response.error || xhr.statusText || "${ _('Could not create znode') }");
      });
    });
  });
</script>


${ shared.footer() }

%if not is_embeddable:
${ commonfooter(request, messages) | n,unicode }
%endif
