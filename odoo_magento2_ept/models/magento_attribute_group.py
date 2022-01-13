# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from odoo.addons.odoo_magento2_ept.models.api_request import req, create_search_criteria

_logger = logging.getLogger(__name__)


class MagentoAttributeGroup(models.Model):
    _name = "magento.attribute.group"
    _description = 'Magento Attribute Group'

    name = fields.Char(string="Attribute Group Name", help="Magento Attribute Group Name", required=True)
    instance_id = fields.Many2one(
        'magento.instance',
        'Instance',
        ondelete="cascade",
        help="This field relocates magento instance"
    )
    attribute_group_id = fields.Char(
        string="Attribute Group", help="Magento Attribute Group ID")
    sort_order = fields.Integer(
        string='Sort Order', readonly=True)
    attribute_set_id = fields.Many2one(
        'magento.attribute.set', string="Magento Attribute Set")
    magento_attribute_ids = fields.Many2many(
        'magento.product.attribute', string='Magento Attribute IDs', help='Magento Attribute')
    active = fields.Boolean(string="Status", default=True)

    def import_magento_attribute_group(self, instance, attribute_set_list):
        """
        Import Magento Attribute Group in odoo
        :param instance: Magento instance
        :param attribute_set_list: attribute set list
        :return:
        """
        for attribute_set in attribute_set_list:
            filters = {'attribute_set_id': int(attribute_set.attribute_set_id)}
            filters = create_search_criteria(filters)
            query_string = Php.http_build_query(filters)
            url = "/V1/products/attribute-sets/groups/list?%s" % query_string
            try:
                attribute_group_list = req(instance, url)
            except Exception as error:
                raise UserError(_("Error while requesting Attribute Group" + str(error)))
            attribute_group_list = attribute_group_list.get('items')
            for attribute_group in attribute_group_list:
                magento_attribute_group = self.search([
                    ('attribute_group_id', '=', attribute_group.get('attribute_group_id')),
                    ('instance_id', '=', instance.id)])
                if not magento_attribute_group:
                    self.create({
                        'attribute_group_id': attribute_group.get('attribute_group_id'),
                        'name': attribute_group.get('attribute_group_name'),
                        'attribute_set_id': attribute_set.id,
                        'instance_id': instance.id})
