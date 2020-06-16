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

import { simplePostAsync } from 'api/apiUtils';
import { AUTOCOMPLETE_API_PREFIX } from 'api/urls';
import { Argument, Connector, UdfDetails } from './sqlReferenceRepository';
import I18n from 'utils/i18n';

export interface ApiUdf {
  name: string;
  is_builtin?: string;
  is_persistent?: string;
  return_type?: string;
  signature?: string;
}

const FUNCTIONS_OPERATION = 'functions';
const DEFAULT_DESCRIPTION = I18n('No description available.');
const DEFAULT_RETURN_TYPES = ['T'];
const DEFAULT_ARGUMENTS = [[{ type: 'T', multiple: true }]];

const SIGNATURE_REGEX = /([a-z]+(?:\.{3})?)/gi;
const TYPE_REGEX = /(?<type>[a-z]+)(?<multiple>\.{3})?/i;

const stripPrecision = (typeString: string): string => typeString.replace(/\(\*(,\*)?\)/g, '');

const adaptApiUdf = (apiUdf: ApiUdf): UdfDetails => {
  const signature = apiUdf.name + '()';
  return {
    name: apiUdf.name,
    returnTypes: extractReturnTypes(apiUdf),
    arguments: extractArgumentTypes(apiUdf),
    signature: signature,
    draggable: signature,
    description: DEFAULT_DESCRIPTION
  };
};

const extractReturnTypes = (apiUdf: ApiUdf): string[] =>
  apiUdf.return_type ? [stripPrecision(apiUdf.return_type)] : DEFAULT_RETURN_TYPES;

export const extractArgumentTypes = (apiUdf: ApiUdf): Argument[][] => {
  if (apiUdf.signature) {
    const cleanSignature = stripPrecision(apiUdf.signature);
    if (cleanSignature === '()') {
      return [];
    }
    const match = cleanSignature.match(SIGNATURE_REGEX);
    if (match) {
      return match.map(argString => {
        const typeMatch = argString.match(TYPE_REGEX);
        if (typeMatch && typeMatch.groups) {
          const arg: Argument = { type: typeMatch.groups.type };
          if (typeMatch.groups.multiple) {
            arg.multiple = true;
          }
          return [arg];
        } else {
          return [];
        }
      });
    }
  }
  return DEFAULT_ARGUMENTS;
};

export const mergeArgumentTypes = (target: Argument[][], additional: Argument[][]) => {
  for (let i = 0; i < target.length; i++) {
    if (i >= additional.length) {
      break;
    }
    if (target[i][0].type === 'T') {
      continue;
    }
    if (additional[i][0].type === 'T') {
      target[i] = additional[i];
      continue;
    }
    target[i].push(...additional[i]);
  }
};

export const adaptApiFunctions = (functions: ApiUdf[]): UdfDetails[] => {
  const udfs: UdfDetails[] = [];
  const adapted: { [attr: string]: UdfDetails } = {};
  functions.forEach(apiUdf => {
    if (adapted[apiUdf.name]) {
      const adaptedUdf = adapted[apiUdf.name];

      const additionalArgs = extractArgumentTypes(apiUdf);
      mergeArgumentTypes(adaptedUdf.arguments, additionalArgs);

      if (adaptedUdf.returnTypes[0] !== 'T') {
        const additionalReturnTypes = extractReturnTypes(apiUdf);
        if (additionalReturnTypes[0] !== 'T') {
          adaptedUdf.returnTypes.push(...additionalReturnTypes);
        } else {
          adaptedUdf.returnTypes = additionalReturnTypes;
        }
      }
    } else {
      adapted[apiUdf.name] = adaptApiUdf(apiUdf);
      udfs.push(adapted[apiUdf.name]);
    }
  });
  return udfs;
};

export const fetchUdfs = async (options: {
  connector: Connector;
  database?: string;
  silenceErrors: boolean;
}): Promise<ApiUdf[]> => {
  let url = AUTOCOMPLETE_API_PREFIX;
  if (options.database) {
    url += '/' + options.database;
  }

  const data = {
    notebook: {},
    snippet: JSON.stringify({
      type: options.connector.id
    }),
    operation: FUNCTIONS_OPERATION
  };

  try {
    const response = await simplePostAsync(url, data, options);

    if (response && response.functions) {
      return adaptApiFunctions(response.functions);
    }
    return (response && response.functions) || [];
  } catch (err) {
    return [];
  }
};