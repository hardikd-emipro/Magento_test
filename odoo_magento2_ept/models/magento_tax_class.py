# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes Magento Tax Class
"""
from odoo import models, api, fields


class MagentoTaxClass(models.Model):
    """
    Describes Magento Tax Class
    """
    _name = 'magento.tax.class'
    _description = 'Magento Tax Class'
    _rec_name = 'magento_tax_class_name'

    magento_instance_id = fields.Many2one(
        'magento.instance',
        'Instance',
        ondelete="cascade",
        help="This field relocates magento instance"
    )
    magento_tax_class_id = fields.Char(string='Magento Tax Class Id', help='Magento Tax Class Id')
    magento_tax_class_name = fields.Char(string='Magento Tax Class Name', help='Magento Tax Class Name')
    magento_tax_class_type = fields.Char(string='Magento Tax Class Type', help='Magento Tax Class Type')
    active = fields.Boolean(string="Status", default=True)

    _sql_constraints = [
        ('unique_magento_tax_class_id', 'unique(magento_instance_id,magento_tax_class_id)',
         'This tax class is already exist')]
