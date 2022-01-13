# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
from odoo import models, fields


class MagentoProductOption(models.Model):
    _name = "magento.attribute.option"
    _description = 'Magento Attribute Option'

    name = fields.Char(string='Magento Attribute Value', required=True, translate=True)
    odoo_option_id = fields.Many2one('product.attribute.value', string='Odoo Attribute option', ondelete='cascade')
    odoo_attribute_id = fields.Many2one('product.attribute', string='Odoo Attribute', ondelete='cascade')
    magento_attribute_option_name = fields.Char(string="Magento Attribute Option Value", help="Magento Attribute Value")
    magento_attribute_id = fields.Many2one("magento.product.attribute", string="Magento Attribute", ondelete='cascade')
    magento_attribute_option_id = fields.Char(string='Magento ID')
    instance_id = fields.Many2one('magento.instance', string="Instance", ondelete="cascade")
    active = fields.Boolean(string="Status", default=True)
