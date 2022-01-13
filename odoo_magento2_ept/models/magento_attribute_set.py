# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from odoo.addons.odoo_magento2_ept.models.api_request import req

_logger = logging.getLogger(__name__)


class MagentoAttributeSet(models.Model):
    _name = "magento.attribute.set"
    _description = 'Magento Attribute Set'
    _rec_name = 'display_name'

    def _compute_get_display_name(self):
        for attribute_set in self:
            magento = attribute_set.instance_id.name if attribute_set.instance_id else ''
            attribute_set.display_name = "%s - %s" % (
                attribute_set.attribute_set_name, magento)

    attribute_set_name = fields.Char(string="Attribute Set Name", help="Magento Attribute Set Name")
    instance_id = fields.Many2one(
        'magento.instance', 'Instance', ondelete="cascade", help="This field relocates magento instance record")
    attribute_set_id = fields.Char(string="Attribute Set ID", help="Magento Attribute Set ID")
    sort_order = fields.Integer(string='Sort Order')
    attribute_group_ids = fields.One2many(
        'magento.attribute.group', 'attribute_set_id',
        string="Attribute group", help="Attribute group")
    active = fields.Boolean(string="Status", default=True)
    display_name = fields.Char(string="Display Name", help="Display Name", compute='_compute_get_display_name')

    def import_magento_product_attribute_set(self, instance):
        """
        Import Attribute set in odoo
        :param instance: Magento Instance
        :return:
        """
        new_attribute_set = []
        attribute_group_obj = self.env['magento.attribute.group']
        magento_attribute_obj = self.env['magento.product.attribute']
        filters = {'searchCriteria': {'filterGroups': [{'filters': [{'field': 'entity_type_id',
                                                                     'value': -1,
                                                                     'condition_type': 'gt'}]}]}}
        query_string = Php.http_build_query(filters)
        api_url = "/V1/products/attribute-sets"
        url = "%s/sets/list?%s" % (api_url, query_string)
        try:
            attribute_set_list = req(instance, url)
        except Exception as error:
            raise UserError(_("Error while requesting Attribute Group" + str(error)))
        attribute_set_list = attribute_set_list.get('items')
        if attribute_set_list:
            for attribute_set in attribute_set_list:
                magento_attribute_set = self.search([
                    ('attribute_set_id', '=', attribute_set.get('attribute_set_id'))
                    , ('instance_id', '=', instance.id)])
                if not magento_attribute_set:
                    magento_attribute_set = self.create(
                        {'attribute_set_name': attribute_set.get('attribute_set_name'),
                         'attribute_set_id': attribute_set.get('attribute_set_id'),
                         'instance_id': instance.id,
                         'sort_order': attribute_set.get('sort_order')})
                    new_attribute_set.append(magento_attribute_set)
                attribute_group_obj.import_magento_attribute_group(instance, magento_attribute_set)
                magento_attribute_obj.import_magento_attributes(instance, magento_attribute_set)
