# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Requrests API to magento.
"""
import json
import socket
import logging
import requests
from odoo import _
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)


def req(backend, path, method='GET', data=None, params=None):
    """
    This method use for base on API request it call API method.
    """
    location_url = backend._check_location_url(backend.magento_url)
    verify_ssl = backend.magento_verify_ssl
    api_url = '%s%s' % (location_url, path)
    headers = {
        'Accept': '*/*', 'Content-Type': 'application/json',
        'User-Agent': 'My User Agent 1.0', 'Authorization': 'Bearer %s' % backend.access_token}
    try:
        _logger.info('Data pass to Magento : %s', data)
        if verify_ssl:
            resp = call_ssl_verify_request(method, api_url, headers, params, data)
        else:
            resp = call_without_ssl_verify_request(method, api_url, headers, params, data)
        content = resp.json()
        _logger.info('API URL : %s', api_url)
        _logger.info('Response Status code : %s', resp.status_code)
        if resp.status_code == 401:
            raise UserError(_('Given Credentials is incorrect, please provide correct Credentials.'))
        if resp.status_code == 500:
            return content
        if not resp.ok:
            if resp.headers.get('content-type').split(';')[0] == 'text/html':
                raise UserError(_('Content-type is not JSON \n %s : %s \n %s \n %s', (
                    resp.status_code, resp.reason, path, resp.content)))
            response = resp.json()
            response.update({'status_code':resp.status_code})
            raise UserError(str(response), response=response)
    except (socket.gaierror, socket.error, socket.timeout) as err:
        raise UserError(_('A network error caused the failure of the job: %s', err))
    except Exception as error:
        raise UserError(_("It is possible that the API request has not been satisfied for the following "
                          "reasons:\n1. Access tokens can be incorrect or not configured properly: "
                          "Magento2 admin panel > System > Integration > API > Set 'All' in the Resource Access field."
                          " Refer to the user guide for more details.\n "
                          "2. There is no Emipro API change plugin installed on Magento2 or the "
                          "plugin is not updated correctly. Download the latest API change plugin "
                          "from the instance wizard and upload it on the Magento2 server. "
                          "Please read the user guide on how to download and upload the API change plugin.\n "
                          "3. It's possible that Magento2 has blocked your IP address, for which you need to "
                          "whitelist it. Please contact your Magento2 support team "
                          "for more information. {}".format(error)))
    return content


def call_ssl_verify_request(method, api_url, headers, params, data):
    if method == 'GET':
        resp = requests.get(api_url, headers=headers, verify=True, params=params)
    elif method == 'POST':
        resp = requests.post(api_url, headers=headers, data=json.dumps(data), verify=True, params=params)
    elif method == 'DELETE':
        resp = requests.delete(api_url, headers=headers, verify=True, params=params)
    elif method == 'PUT':
        resp = requests.put(api_url, headers=headers, data=json.dumps(data), verify=True, params=params)
    else:
        resp = requests.get(api_url, headers=headers, verify=True, params=params)
    return resp


def call_without_ssl_verify_request(method, api_url, headers, params, data):
    if method == 'GET':
        resp = requests.get(api_url, headers=headers, params=params)
    elif method == 'POST':
        resp = requests.post(api_url, headers=headers, data=json.dumps(data), params=params)
    elif method == 'DELETE':
        resp = requests.delete(api_url, headers=headers, params=params)
    elif method == 'PUT':
        resp = requests.put(api_url, headers=headers, data=json.dumps(data), params=params)
    else:
        resp = requests.get(api_url, headers=headers, params=params)
    return resp


def create_filter(field, value, condition_type='eq'):
    """
    Create dictionary for filter.
    :param field: Field to be filter
    :param value: Value to be filter
    :param condition_type: condition type to be filter
    :return: Dictionary for filter
    """
    filter_dict = {'field': field}
    if isinstance(value, str) and condition_type == "in":
        filter_dict['condition_type'] = 'like'
    elif isinstance(value, str) and condition_type == "nin":
        filter_dict['condition_type'] = 'nlike'
    else:
        filter_dict['condition_type'] = condition_type
    filter_dict['value'] = value

    return filter_dict


def create_search_criteria(filters):
    """
        Create Search Criteria
        if filters is {'updated_at': {'to': '2016-12-22 10:42:44', 'from': '2016-12-16 10:42:18'}}
        then searchCriteria = {'searchCriteria': {'filterGroups': [{'filters': [{'field':
        'updated_at', 'condition_type': 'to', 'value': '2016-12-22 10:42:44'}]},{'filters':
        [{'field': 'updated_at', 'condition_type': 'from', 'value': '2016-12-16 10:42:18'}]}]}}
    """
    searchcriteria = {}
    if filters is None:
        filters = {}

    if not filters:
        searchcriteria = {
            'searchCriteria': {
                'filterGroups': [{
                    'filters': [{
                        'field': 'id', 'value': -1, 'condition_type': 'gt'
                    }]
                }]
            }
        }
    else:
        searchcriteria.setdefault('searchCriteria', {})
        filtersgroup_list = []
        for k, val in filters.items():
            tempfilters = {}
            filters_list = []
            if isinstance(val, dict):
                for operator, values in val.items():
                    filters_list, filtersgroup_list, tempfilters = generate_filter_groups(
                        operator, values, k, filters_list, tempfilters, filtersgroup_list)
            else:
                filters_list.append(create_filter(k, val))
                tempfilters["filters"] = filters_list
                filtersgroup_list.append(tempfilters)
        searchcriteria["searchCriteria"]['filterGroups'] = filtersgroup_list
    return searchcriteria


def generate_filter_groups(operator, values, k, filters_list, tempfilters, filtersgroup_list):
    if isinstance(values, list):
        if operator == "in":
            for value in values:
                filters_list.append(create_filter(k, value, operator))
            tempfilters["filters"] = filters_list
            filtersgroup_list.append(tempfilters)
        elif operator == "nin":
            for value in values:
                filters_list.append(create_filter(k, value, operator))
                tempfilters["filters"] = filters_list
                filtersgroup_list.append(tempfilters)
    else:
        filters_list.append(create_filter(k, values, operator))
        tempfilters["filters"] = filters_list
        filtersgroup_list.append(tempfilters)
        filters_list = []
        tempfilters = {}
    return filters_list, filtersgroup_list, tempfilters
