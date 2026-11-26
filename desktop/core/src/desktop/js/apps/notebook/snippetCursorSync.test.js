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

import { syncHandleCursor } from './snippetCursorSync';

describe('syncHandleCursor', () => {
  it('should copy next_uri and row_count from an intermediate result page', () => {
    const handle = { next_uri: 'https://trino/v1/statement/executed/q/1', row_count: 0 };
    syncHandleCursor(handle, {
      next_uri: 'https://trino/v1/statement/executed/q/1#hue_off=100',
      row_count: 100
    });
    expect(handle.next_uri).toBe('https://trino/v1/statement/executed/q/1#hue_off=100');
    expect(handle.row_count).toBe(100);
  });

  it('should clear next_uri with null on the last page even when the key is present with null', () => {
    const handle = {
      next_uri: 'https://trino/v1/statement/executed/q/2#hue_off=200',
      row_count: 200
    };
    syncHandleCursor(handle, { next_uri: null, row_count: 250 });
    expect(handle.next_uri).toBeNull();
    expect(handle.row_count).toBe(250);
  });

  it('should fall back to the given row_count when the source has no row_count', () => {
    const handle = { next_uri: 'https://trino/v1/statement/queued/q/1', row_count: 42 };
    syncHandleCursor(
      handle,
      { status: 'waiting', next_uri: 'https://trino/v1/statement/queued/q/2' },
      0
    );
    expect(handle.next_uri).toBe('https://trino/v1/statement/queued/q/2');
    expect(handle.row_count).toBe(0);
  });

  it('should leave the handle untouched when the source has no next_uri key', () => {
    const handle = { has_result_set: true, row_count: 7 };
    syncHandleCursor(handle, { data: [], has_more: false });
    expect(handle).toEqual({ has_result_set: true, row_count: 7 });
    expect('next_uri' in handle).toBe(false);
  });

  it('should not throw on null handle or missing source', () => {
    expect(() => syncHandleCursor(null, { next_uri: 'x' })).not.toThrow();
    expect(() => syncHandleCursor(undefined, undefined)).not.toThrow();
    expect(() => syncHandleCursor({ next_uri: 'keep' }, null)).not.toThrow();
    expect(() => syncHandleCursor({ next_uri: 'keep' }, undefined)).not.toThrow();
  });
});
