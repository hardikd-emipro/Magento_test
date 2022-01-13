# coding: utf-8
"""
@author: Emipro Technologies
@create_date: 22.07.2021
"""
import requests
import odoo
import logging
from distutils.version import LooseVersion
from odoo import models, fields, api

_logger = logging.getLogger("InAppNotification")


class EmiproAppVersionDetails(models.Model):
    _name = 'emipro.app.version.details'
    _rec_name = 'module_id'

    module_id = fields.Many2one(comodel_name='ir.module.module', string="Module")
    version = fields.Char(string="App Version", help="Emipro's installed app version.")
    update_detail = fields.Html(string="Version Details", help="App version update details.")
    is_latest = fields.Boolean(string="Is Latest Version?",
                               help="True, if the installed app version is latest.")
    upgrade_require = fields.Boolean(string="Is Update Required?",
                                     help="True, if required to update app to latest version.")
    is_notify = fields.Boolean(string="Is Notify?",
                               help="False, It will not notify any updates related to this app.\n"
                                    "If customer click on the close button it will mark that \n"
                                    "update as True and never show the update again.",
                               default=True)
    update_url = fields.Char(string="Odoo Store URL")

    def auto_send_installed_app_details_ept(self):
        """
        This method are used in cronjob.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :return: True
        """
        details = self._prepare_odoo_details()
        request_data = self._get_installed_modules(details)
        url = 'http://192.168.1.139:8080/app_notification/send'
        headers = {
            'Accept': '*/*',
            'Content-Type': 'application/json',
        }
        try:
            requests.post(url, headers=headers, json=request_data, verify=False, timeout=180)
        except Exception as error:
            _logger.error(error)
        return True

    def _prepare_odoo_details(self):
        """
        This method are used to prepare dictionary for odoo basic details like
        version, platform, odoo_url, email, user etc..
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :return: dict()
        """
        info = self._get_version_info()
        details = self._get_company_info()
        details.update({
            'odoo_version': info.get('server_version'),
            'platform': info.get('platform'),
        })
        return details

    def _get_installed_modules(self, info):
        """
        This method are used to gather the information of installed/uninstalled modules
        in the customer's database and updated it into the param: info.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :param info: dict()
        :return: info
        """
        module = self.env['ir.module.module'].sudo()
        module_list = dict()
        for state in ['installed', 'uninstalled']:
            modules = module.search_read([('author', 'in', self.get_author()),
                                          ('state', '=', state)],
                                         fields=['name', 'latest_version', 'author'])
            if state == 'uninstalled':
                for module in modules:
                    manifest = odoo.modules.load_information_from_description_file(
                        module.get('name'))
                    module.update({'latest_version': manifest.get('version')})
            module_list.update({state: modules})
        info.update({
            'app_details': module_list
        })
        return info

    @staticmethod
    def get_author():
        return [
            'Emipro Technologies Pvt. Ltd.',
            'Emipro',
            'Emipro Technologies',
        ]

    @staticmethod
    def _get_version_info():
        """
        This method are used to get the odoo version information, If we get the "e" param in
        the list then the version is "enterprise" otherwise it will "community".
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :return: dict()
        """
        info = odoo.service.common.exp_version()
        platform = 'community'
        info.update({'platform': 'community'})
        if '+e' in info.get('server_version'):
            platform = 'enterprise'
        info.update({
            'platform': platform
        })
        return info

    def _get_company_info(self):
        """
        This method are used to get the basic company information like name, email, odoo_url,
        db_uuid.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :return: dict()
        """
        params = self._get_ipc_param_info()
        return {
            'company_name': self.env.company.name,
            'company_email': self.env.company.email or self.env.user.email,
            'odoo_url': params.get('url'),
            'send_notification': params.get('is_notify'),
            'db_uuid': params.get('db_uuid')
        }

    def _get_ipc_param_info(self):
        """
        This method are used to get the required system parameter information.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :return: dict()
        """
        ipc = self.env['ir.config_parameter'].sudo()
        params = {
            'url': 'web.base.url',
            'is_notify': 'common_connector_library.app_update_notification',
            'db_uuid': 'database.uuid',
        }
        for param in params:
            params.update({
                param: ipc.get_param(params.get(param))
            })
        return params

    def create_update_details(self, data):
        """
        This method are used to create app update details in the system. It search the update
        based on the module_id and module version, If the app update is available then
        default system will update that update details record otherwise its create new one.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :param data: dict()
        :return: True
        """
        module = self.env['ir.module.module'].sudo()
        app_details = data.get('app_details')
        for app in app_details:
            app_data = app.get(list(app.keys())[0])
            module = module.search([('name', '=', list(app.keys())[0])], limit=1)
            if module:
                for data in app_data:
                    emipro_app = self.search([('module_id', '=', module.id),
                                              ('version', '=', data.get('version'))], limit=1)
                    if emipro_app:
                        emipro_app.sudo().write(data)
                    else:
                        data.update({'module_id': module.id})
                        self.sudo().create(data)
            self._cr.commit()
        return True

    def find_update_details(self, module):
        """
        This method are used to find an update details based on the module_id from
        customer's database and return it.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :param module: ir.module.module object
        :return: list(update details)
        """
        updates = self.search([('module_id', '=', module.id), ('is_notify', '=', True)])
        versions = updates.mapped('version')
        versions = sorted(versions, key=LooseVersion, reverse=True)
        details = list()
        for version in versions:
            if len(details) >= 5:
                break
            update = updates.filtered(lambda u: u.version == version)
            details.append({
                'version': update.version,
                'detail': update.update_detail,
                'is_latest': update.is_latest,
                'update_required': update.upgrade_require,
                'update_url': update.update_url
            })
        return details

    def disable_notification(self, module_name):
        """
        This method are used to find the update details of specific module, and disable the
        notification for that specific module for the customer.
        :created_by: Mayur Jotaniya
        :create_date: 07.09.2021
        -----------------
        :param module_name: string
        :return: True
        """
        module = self.env['ir.module.module'].sudo()
        module = module.search([('name', '=', module_name)], limit=1)
        if module:
            details = self.search([('module_id', '=', module.id)])
            if details:
                details.write({'is_notify': False})
        return True
