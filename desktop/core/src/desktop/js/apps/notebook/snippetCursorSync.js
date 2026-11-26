// Licensed to Cloudera, Inc. under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  Cloudera, Inc. licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * For any interpreter, returning `next_uri` updates the result handle's pagination cursor.
 * Omit the key to keep the current cursor, or send `null` to clear it after the final page.
 * During status polling, a cursor update that omits `row_count` resets the count to zero.
 *
 * @param {Object} handle - The result handle to update.
 * @param {Object} source - The API response carrying the cursor (handle, result or query_status).
 * @param {number} [fallbackRowCount] - Used as row_count when the source carries next_uri but no row_count.
 */
export const syncHandleCursor = (handle, source, fallbackRowCount) => {
  if (handle && source && Object.prototype.hasOwnProperty.call(source, 'next_uri')) {
    handle.next_uri = source.next_uri;
    if (Object.prototype.hasOwnProperty.call(source, 'row_count')) {
      handle.row_count = source.row_count;
    } else if (typeof fallbackRowCount !== 'undefined') {
      handle.row_count = fallbackRowCount;
    }
  }
};
