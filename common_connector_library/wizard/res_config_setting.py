# coding: utf-8
"""
@author: Emipro Technologies
@create_date: 22.07.2021
"""
import logging
from odoo import models, fields, api
_logger = logging.getLogger("InAppNotification")


class CustomerAppNotificationSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    app_update_notify_ept = fields.Boolean(string="Enable Emipro's app update notification?",
                                           help="If True, Get the notification of latest app "
                                                "update of Emipro.",
                                           config_parameter='common_connector_library.app_update_notification')

    def execute(self):
        params = self.env['ir.config_parameter'].sudo()
        cron = self.env['ir.cron']
        is_notify = params.get_param('common_connector_library.app_update_notification', False)
        try:
            cron = self.env.ref("common_connector_library.in_app_notification_ept")
        except Exception as error:
            _logger.error(error)
        if cron:
            if not (is_notify and self.app_update_notify_ept):
                cron.write({'active': self.app_update_notify_ept})
        return super(CustomerAppNotificationSettings, self).execute()
