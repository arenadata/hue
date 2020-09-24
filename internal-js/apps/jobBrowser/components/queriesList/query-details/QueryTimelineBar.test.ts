// Licensed to Cloudera, Inc. under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  Cloudera, Inc. licenses this file
// to you under the Apache License, Version 2.0 (the
// 'License'); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an 'AS IS' BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { shallowMount } from '@vue/test-utils';
import QueryTimelineBar from './QueryTimelineBar.vue';

describe('QueryTimelineBar.vue', () => {
  it('should render a timeline bar', () => {
    const wrapper = shallowMount(QueryTimelineBar, {
      propsData: {
        title: 'Some title',
        value: 132,
        total: 210
      }
    });
    expect(wrapper.element).toMatchSnapshot();
  });

  it('should render a timeline bar with 0 total (div 0 check)', () => {
    const wrapper = shallowMount(QueryTimelineBar, {
      propsData: {
        value: 0,
        total: 0
      }
    });
    expect(wrapper.element).toMatchSnapshot();
  });
});