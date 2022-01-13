# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.odoo_magento2_ept.models.api_request import req

_logger = logging.getLogger(__name__)
MAGENTO_HELP = "This field is a technical / configuration field for " \
                   "the attribute on Magento. \nPlease refer to the Magento " \
                   "documentation for details. "
PRODUCT_ATTRIBUTE = 'product.attribute'
MAGENTO_ATTRIBUTE_OPTIONS = 'magento.attribute.option'


class MagentoProductAttribute(models.Model):
    _name = "magento.product.attribute"
    _rec_name = 'magento_attribute_code'
    _description = 'Magento Product Attribute'

    name = fields.Char('Magento Attribute', required=True, translate=True)
    odoo_attribute_id = fields.Many2one(
        PRODUCT_ATTRIBUTE, required=True, string='Odoo Attributes', ondelete='cascade')
    instance_id = fields.Many2one('magento.instance', string="Instance", ondelete="cascade",)
    magento_attribute_id = fields.Char(string="Magento Id")
    magento_attribute_code = fields.Char(string='Attribute Code', required=True, size=200)
    scope = fields.Selection([
        ('store', 'store'), ('website', 'website'), ('global', 'global')
    ], string='Scope', default='global', required=True, help=MAGENTO_HELP)
    frontend_label = fields.Char(string='Label', required=True, size=100, help=MAGENTO_HELP)
    position = fields.Integer(string='Positions', help=MAGENTO_HELP)
    group_id = fields.Integer(string='Group', help=MAGENTO_HELP)
    default_value = fields.Char(string='Default', size=10, help=MAGENTO_HELP)
    note = fields.Char(string='Notes', size=200, help=MAGENTO_HELP)
    entity_type_id = fields.Integer(string='Entity Type', help=MAGENTO_HELP)
    is_visible_in_advanced_search = fields.Boolean(
        string='Visible in advanced search?', help=MAGENTO_HELP, default=True)
    is_visible = fields.Boolean(string='Visible?', help=MAGENTO_HELP, default=True)
    is_visible_on_front = fields.Boolean(string='Visible (front)?', help=MAGENTO_HELP, default=True)
    is_html_allowed_on_front = fields.Boolean(string='Html (front)?', help=MAGENTO_HELP)
    is_wysiwyg_enabled = fields.Boolean(string='Wysiwyg enabled?', help=MAGENTO_HELP)
    is_global = fields.Boolean('Global?', help=MAGENTO_HELP)
    is_unique = fields.Boolean('Unique?', help=MAGENTO_HELP)
    is_required = fields.Boolean('Required?', help=MAGENTO_HELP)
    is_filterable = fields.Boolean('Filterable?', help=MAGENTO_HELP, default=True)
    is_comparable = fields.Boolean('Comparable?', help=MAGENTO_HELP, default=True)
    is_searchable = fields.Boolean('Searchable ?', help=MAGENTO_HELP, default=True)
    is_configurable = fields.Boolean('Configurable?', help=MAGENTO_HELP)
    is_user_defined = fields.Boolean('User defined?', help=MAGENTO_HELP)
    used_for_sort_by = fields.Boolean('Use for sort?', help=MAGENTO_HELP)
    is_used_for_price_rules = fields.Boolean('Used for pricing rules?', help=MAGENTO_HELP)
    is_used_for_promo_rules = fields.Boolean('Use for promo?', help=MAGENTO_HELP)
    used_in_product_listing = fields.Boolean('In product listing?', help=MAGENTO_HELP)
    option_ids = fields.One2many(MAGENTO_ATTRIBUTE_OPTIONS, 'magento_attribute_id', string='Options')
    create_state = fields.Selection([('new', 'New'), ('created', 'Done')], string='State')
    additional_check = fields.Boolean(string='is it additional?')
    attribute_type = fields.Selection([
        ('char', 'Char'), ('text', 'Text'), ('select', 'Select'),
        ('multiselect', 'Multiselect'), ('boolean', 'Boolean'), ('integer', 'Integer'),
        ('date', 'Date'), ('datetime', 'Datetime'), ('binary', 'Binary'), ('float', 'Float')
    ], string='Type Of Attribute', required=True)
    active = fields.Boolean(string="Status", default=True)

    def import_magento_attributes(self, magento_instance, attribute_set_list):
        """
        Import Attributes from Magento to Odoo.
        :param magento_instance: Magento Instance object
        :param attribute_set_list:  magento attribute set dictionary
        :return:
        """
        magento_attribute_group_obj = self.env['magento.attribute.group']
        for attribute_set in attribute_set_list:
            url = "/V1/attribute"
            data = {'attribute_set_id': int(attribute_set.attribute_set_id)}

            magento_attributes = req(magento_instance, url, method='POST', data=data)

            for magento_attribute in magento_attributes:
                for key, items in magento_attribute.items():
                    group_name = key
                    attributes = items
                    attribute_group = magento_attribute_group_obj.search(
                        [('name', '=', group_name), ('instance_id', '=', magento_instance.id),
                         ('attribute_set_id', '=', attribute_set.id)])
                    if attribute_group:
                        self.search_or_create_product_attribute(attributes, magento_instance, attribute_group)

    def search_or_create_product_attribute(self, attributes, magento_instance, attribute_group):
        magento_attribute_dict = []
        for attribute in list(attributes.keys()):
            magento_attribute = attributes.get(attribute)
            if magento_attribute:
                magento_id = attribute
                if isinstance(magento_attribute, list) and len(magento_attribute) > 0:
                    magento_attribute = magento_attribute[0]
                if isinstance(magento_attribute, dict):
                    magento_attribute_name = magento_attribute.get(list(magento_attribute.keys())[0])
                else:
                    magento_attribute_name = magento_attribute
                product_attribute = self.search(
                    [('magento_attribute_id', '=', magento_id),
                     ('magento_attribute_code', '=', magento_attribute_name),
                     ('instance_id', '=', magento_instance.id)])
                product_attribute = self.create_product_attribute_in_odoo(
                    magento_instance, magento_id, product_attribute)
                if product_attribute:
                    magento_attribute_dict.append(product_attribute.id)
            self._cr.commit()
        attribute_group.write({'magento_attribute_ids': [(6, 0, magento_attribute_dict)]})

    def create_product_attribute_in_odoo(self, magento_instance, magento_attribute, magento_product_attribute):
        """
        This method for create a product attribute in odoo while import magento attributes from magento.
        :param magento_instance: Magento Instance object
        :param magento_attribute: magento attribute Id
        :param magento_product_attribute: magento product attribute object
        :return:
        """
        attribute_values, attribute_data = self.prepare_magento_attribute_values(
            magento_instance, magento_attribute)

        if not attribute_values['frontend_label']:
            return False
        if not magento_product_attribute:
            magento_product_attribute = self.create(attribute_values)
            if magento_product_attribute.odoo_attribute_id:
                product_attribute_obj = self.env[PRODUCT_ATTRIBUTE].browse(magento_product_attribute.odoo_attribute_id.id)
                if product_attribute_obj:
                    product_attribute_obj.magento_attribute_id = magento_product_attribute.id
        if attribute_data.get('options'):
            self.create_attribute_options_in_odoo(magento_product_attribute, attribute_data)
        return magento_product_attribute

    def prepare_magento_attribute_values(self, magento_instance, magento_attribute):
        """
        This method prepare values for attribute while create product attribute in odoo.
        :param magento_instance: Magento Instance object
        :param magento_attribute: magento attribute Id
        :return:
        """
        product_attribute_obj = self.env[PRODUCT_ATTRIBUTE]
        url = '/V1/products/attributes/%s' % magento_attribute
        try:
            attribute_data = req(magento_instance, url)
        except Exception as error:
            raise UserError(_("Error while requesting Attribute" + str(error)))
        odoo_attribute = False
        attribute_data, attribute_type = self.get_magento_attribute_data_type(attribute_data)

        if attribute_data.get('default_frontend_label'):
            odoo_attribute = product_attribute_obj.get_attribute(
                attribute_data.get('default_frontend_label'), attribute_type=attribute_type,
                create_variant='always', auto_create=True)
        attribute_vals = {
            'instance_id': magento_instance.id,
            'magento_attribute_id': attribute_data.get('attribute_id'),
            'name': attribute_data.get('default_frontend_label') or 'No frontend label',
            'magento_attribute_code': attribute_data.get('attribute_code'),
            'scope': attribute_data.get('scope'),
            'attribute_type': attribute_data.get('type'),
            'frontend_label': attribute_data.get('default_frontend_label'),
            'default_value': attribute_data.get('default_value')
        }

        if odoo_attribute:
            attribute_vals.update({'odoo_attribute_id': odoo_attribute.id})
        return attribute_vals, attribute_data

    @staticmethod
    def get_magento_attribute_data_type(attribute_data):
        attribute_type = 'radio'
        if attribute_data.get('frontend_input'):
            if attribute_data.get('frontend_input') in ['textarea']:
                attribute_data['type'] = 'text'
            elif attribute_data.get('frontend_input') == 'text':
                attribute_data['type'] = 'char'
            elif attribute_data.get('frontend_input') == 'date':
                attribute_data['type'] = 'date'
            elif attribute_data.get('frontend_input') == 'boolean':
                attribute_data['type'] = 'boolean'
            elif attribute_data.get('frontend_input') == 'multiselect':
                attribute_data['type'] = 'multiselect'
                attribute_type = 'select'
            elif attribute_data.get('frontend_input') in ['price', 'weee', 'weight']:
                attribute_data['type'] = 'float'
            elif attribute_data.get('frontend_input') == 'media_image':
                attribute_data['type'] = 'binary'
            elif attribute_data.get('frontend_input') == 'select':
                attribute_type = 'select'
                attribute_data['type'] = 'select'
            elif attribute_data.get('frontend_input') == 'swatch_visual' \
                    or attribute_data.get('frontend_input') == 'swatch_text':
                attribute_type = 'color'
                attribute_data['type'] = 'select'
            else:
                attribute_data['type'] = 'text'
        else:
            attribute_data['type'] = 'text'
        return attribute_data, attribute_type

    def create_attribute_options_in_odoo(self, magento_product_attribute, attribute_data):
        """
        This method for import and create attribute options in odoo.
        :param magento_product_attribute: magento product attribute object
        :param attribute_data: dictionary of magento attribute
        :return:
        """
        magento_option_obj = self.env[MAGENTO_ATTRIBUTE_OPTIONS]
        for attribute_value in attribute_data.get('options'):
            magento_attr_options = magento_option_obj.search([
                ('name', '=', attribute_value.get('label', '-')),
                ('odoo_attribute_id', '=', magento_product_attribute.odoo_attribute_id.id),
                ('magento_attribute_id', '=', magento_product_attribute.id)])
            if not magento_attr_options:
                value = self.get_magento_attribute_values(attribute_value)
                if value == '':
                    continue
                if not attribute_value.get('label', '-'):
                    raise attribute_value
                vals = {
                    'name': attribute_value.get('label', '-') or '-',
                    'magento_attribute_option_name': attribute_value.get('label') or '-',
                    'magento_attribute_option_id': value,
                    'magento_attribute_id': magento_product_attribute.id,
                    'odoo_attribute_id': magento_product_attribute.odoo_attribute_id.id,
                    'instance_id': magento_product_attribute.instance_id.id,
                }
                odoo_attribute_option = self.find_magento_attribute_values(
                    magento_product_attribute, attribute_value)
                if odoo_attribute_option:
                    vals.update({'odoo_option_id': odoo_attribute_option.id})
                magento_option_obj.create(vals)

    def find_magento_attribute_values(self, magento_product_attribute, attribute_value):
        """
        Find duplicate attribute option values into magento layer and
         set it if no duplicate attribute options found
        :param magento_product_attribute: Magento Product Attribute object
        :param attribute_value: dictionary of attribute values
        :return: product attribute values object
        """
        attr_opt_vals = False
        product_attribute_value = self.env['product.attribute.value']
        magento_option_obj = self.env[MAGENTO_ATTRIBUTE_OPTIONS]
        odoo_attribute_option = product_attribute_value.get_attribute_values(
            attribute_value.get('label', '-'), magento_product_attribute.odoo_attribute_id.id, True)
        mag_attr_opt_vals = magento_option_obj.search([
            ('odoo_option_id.id', 'in', odoo_attribute_option.ids),
            ('magento_attribute_id', '=', magento_product_attribute.id)
        ])
        if mag_attr_opt_vals and mag_attr_opt_vals.odoo_option_id:
            attr_opt_vals = product_attribute_value.create(({
                'name': attribute_value.get('label', '-'),
                'attribute_id': magento_product_attribute.odoo_attribute_id.id
            }))
        odoo_attr_opt_vals = attr_opt_vals if attr_opt_vals else odoo_attribute_option
        return odoo_attr_opt_vals

    def get_magento_attribute_values(self, attribute_value):
        if attribute_value.get('value') == 0:
            value = 0
        elif attribute_value.get('value') is None:
            value = None
        elif attribute_value.get('value') is False:
            value = 'False'
        elif attribute_value.get('value') == '':
            value = ''
        else:
            value = attribute_value.get('value')
        return value

    def open_attribute_value(self):
        """
        This method used for smart button for view all attribute value.
        :return:
        """
        return {
            'name': 'Attribute Value',
            'type': 'ir.actions.act_window',
            'res_model': MAGENTO_ATTRIBUTE_OPTIONS,
            'view_mode': 'tree,form',
            'domain': [('magento_attribute_id', '=', self.id)]
        }
