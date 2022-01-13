# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
from odoo import models, fields


class MagentoResPartnerEpt(models.Model):
    _name = "magento.res.partner.ept"
    _description = "Magento Res Partner"

    partner_id = fields.Many2one("res.partner", "Customer", ondelete='cascade')
    magento_instance_id = fields.Many2one('magento.instance', string='Instance',
                                          help="This field relocates magento instance")
    magento_website_id = fields.Many2one("magento.website", string="Magento Website",
                                         help="Magento Website")
    magento_customer_id = fields.Char(string="Magento Customer", help="Magento Customer Id")
    address_id = fields.Char(string="Address", help="Address Id")
