# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes fields and methods for Magento products templates
"""
import re
import time
import logging
import json
import codecs
import io
from PIL import Image
from odoo.addons.odoo_magento2_ept.models.api_request import req
from odoo.addons.odoo_magento2_ept.python_library.php import Php
from odoo import models, fields, api

PRODUCT_TEMPLATE = 'product.template'
MAGENTO_PRODUCT = 'magento.product.product'
MAGENTO_WEBSITE = 'magento.website'
MAGENTO_PRODUCT_IMAGE = 'magento.product.image'
PRODUCT_PRODUCT = 'product.product'
PRODUCT_ATTRIBUTE = 'product.attribute'
MAGENTO_ATTRIBUTE_SET = 'magento.attribute.set'
IR_ACTIONS_ACT_WINDOW = 'ir.actions.act_window'
IR_CONFIG_PARAMETER = "ir.config_parameter"
SET_MAGENTO_SALES_DESCRIPTION = "odoo_magento2_ept.set_magento_sales_description"
MAGENTO_ATTRIBUTE_OPTION = 'magento.attribute.option'
MAGENTO_PRODUCT_ATTRIBUTE = 'magento.product.attribute'
MAGENTO_STOREVIEW = 'magento.storeview'
_logger = logging.getLogger(__name__)


class MagentoProductTemplate(models.Model):
    """
    Describes fields and methods for Magento products templates
    """
    _name = 'magento.product.template'
    _description = 'Magento Product Template'
    _rec_name = "magento_product_name"

    magento_instance_id = fields.Many2one(
        'magento.instance',
        'Instance',
        ondelete="cascade",
        help="This field relocates magento instance"
    )
    magento_product_template_id = fields.Char(
        string="Magento Product Id",
        help="Magento Product Id"
    )
    magento_product_name = fields.Char(
        string="Magento Product Name",
        help="Magento Product Name",
        translate=True
    )
    odoo_product_template_id = fields.Many2one(
        PRODUCT_TEMPLATE,
        string="Odoo Product Template",
        ondelete='restrict',
        required=True
    )
    magento_product_ids = fields.One2many(
        MAGENTO_PRODUCT,
        'magento_tmpl_id',
        string="Magento Products",
        help="Magento Products"
    )
    magento_website_ids = fields.Many2many(
        MAGENTO_WEBSITE,
        string='Magento Websites',
        readonly=False,
        domain="[('magento_instance_id','=',magento_instance_id)]",
        help='Magento Websites'
    )
    created_at = fields.Date(
        string='Product Created At',
        help="Date when product created into Magento"
    )
    updated_at = fields.Date(
        string='Product Updated At',
        help="Date when product updated into Magento"
    )
    product_type = fields.Selection([
        ('simple', 'Simple Product'),
        ('configurable', 'Configurable Product'),
        ('virtual', 'Virtual Product'),
        ('downloadable', 'Downloadable Product'),
        ('group', 'Group Product'),
        ('bundle', 'Bundle Product'),
    ], string='Magento Product Type', help='Magento Product Type', default='simple')
    magento_sku = fields.Char(string="Magento Product SKU", help="Magento Product SKU")
    description = fields.Text(string="Product Description", help="Description", translate=True)
    short_description = fields.Text(
        string='Product Short Description',
        help='Short Description',
        translate=True
    )
    magento_product_image_ids = fields.One2many(
        MAGENTO_PRODUCT_IMAGE,
        'magento_tmpl_id',
        string="Magento Product Images",
        help="Magento Product Images"
    )
    magento_product_price = fields.Float(
        string="Magento Product Prices",
        help="Magento Product Price"
    )
    sync_product_with_magento = fields.Boolean(
        string='Sync Product with Magento',
        help="If Checked means, Product synced With Magento Product"
    )
    active_template = fields.Boolean('Odoo Template Active', related="odoo_product_template_id.active")
    active = fields.Boolean("Active", default=True)
    image_1920 = fields.Image(related="odoo_product_template_id.image_1920")
    total_magento_variants = fields.Integer(string="Total Variants", compute='_compute_total_magento_variant')
    list_price = fields.Float(
        'Sales Price', related='odoo_product_template_id.list_price', readonly=False,
        digits='Product Price')
    standard_price = fields.Float(
        'Cost', related='odoo_product_template_id.standard_price', readonly=False,
        digits='Product Price')
    attribute_line_ids = fields.One2many(related='odoo_product_template_id.attribute_line_ids')
    currency_id = fields.Many2one(related='odoo_product_template_id.currency_id')
    category_ids = fields.Many2many("magento.product.category", string="Categories", help="Magento Categories")
    attribute_set_id = fields.Many2one(MAGENTO_ATTRIBUTE_SET, string='Attribute Set', help="Magento Attribute Sets")
    export_product_to_all_website = fields.Boolean(
        string="Export product to all website?",
        help="If checked, product will be exported for all websites otherwise export for the selected websites")
    magento_tax_class = fields.Many2one('magento.tax.class', string='Tax Class', help="Magento Tax Class")

    _sql_constraints = [('_magento_template_unique_constraint',
                         'unique(magento_sku,magento_instance_id,magento_product_template_id)',
                         "Magento Product Template must be unique")]

    @api.depends('magento_product_ids.magento_tmpl_id')
    def _compute_total_magento_variant(self):
        for template in self:
            # do not pollute variants to be prefetched when counting variants
            template.total_magento_variants = len(template.with_prefetch().magento_product_ids)

    def write(self, vals):
        """
        This method use to archive/un-archive Magento product variants base on Magento product templates.
        :param vals: dictionary for template values
        :return: res
        """
        res = super(MagentoProductTemplate, self).write(vals)
        if (vals.get('active') and len(self.magento_product_ids) == 0) or ('active' in vals and not vals.get('active')):
            self.with_context(active_test=False).mapped('magento_product_ids').write({'active': vals.get('active')})
        return res

    def view_odoo_product_template(self):
        """
        This method id used to view odoo product template.
        :return: Action
        """
        if self.odoo_product_template_id:
            return {
                'name': 'Odoo Product',
                'type': IR_ACTIONS_ACT_WINDOW,
                'res_model': PRODUCT_TEMPLATE,
                'view_type': 'form',
                'view_mode': 'tree,form',
                'domain': [('id', '=', self.odoo_product_template_id.id)],
            }
        return True

    def create_or_update_configurable_product(
            self, item, magento_instance, log_book_id,
            error, magento_per_sku, order_data_queue_line_id, order_ref=False,
    ):
        """
        Create or Update product with product variants
        :param item: Product items received from magento
        :param magento_instance: Instance of Magento
        :param log_book_id: Common log book object
        :param error: if error, it will return True.
        :param magento_per_sku: Dictionary of Magento Product
        :param order_ref: order reference
        :param order_data_queue_line_id: queue line object
        :return: error log if any
        """
        magento_product_template = self.search([
            ('magento_sku', '=', item.get('sku')), ('magento_instance_id', '=', magento_instance.id)
        ])
        order_ref, queue_line = self.get_order_ref_and_queue_line(order_ref, item)
        if 'configurable_product_options_data' not in item.get('extension_attributes'):
            message = "Please check Apichange extention is installed in Magento store."
            log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': message,
                    'order_ref': order_ref,
                    queue_line: order_data_queue_line_id
                })]
            })
            error = True
            return error
        if magento_product_template:
            odoo_template, log_book_id, error = magento_product_template.check_product_template_is_exist_or_not(
                magento_instance, item, log_book_id, error, order_ref, queue_line, order_data_queue_line_id
            )
            if odoo_template and not error:
                magento_product_template_values = self.prepare_magento_product_template_vals(
                    item, magento_instance, odoo_template)
                magento_product_template.write(magento_product_template_values)
        else:
            odoo_template_id, log_book_id, error = self.check_product_template_is_exist_or_not(
                magento_instance, item, log_book_id, error, order_ref, queue_line, order_data_queue_line_id
            )
            if odoo_template_id:
                magento_product_template = self.search([
                    ('odoo_product_template_id', '=', odoo_template_id.id),
                    ('magento_instance_id', '=', magento_instance.id)
                ])
                if not magento_product_template:
                    magento_product_template, error = self.create_magento_product_template(
                        magento_instance, item, odoo_template_id,
                        log_book_id, order_ref, queue_line, order_data_queue_line_id, error)
        if not error:
            error, delete_main_prod = self.set_variant_sku(
                magento_instance, item, magento_product_template, magento_per_sku,
                log_book_id, error, order_data_queue_line_id, queue_line, order_ref)
            if delete_main_prod:
                magento_product_template.sudo().unlink()
            else:
                odoo_template = magento_product_template.odoo_product_template_id
                odoo_template.write({'name': item.get('name')})
        return error

    @staticmethod
    def get_order_ref_and_queue_line(order_ref, item):
        """
        Get Order_ref and queue_line.
        :param order_ref: order ref
        :param item: item received from Magento
        :return: order_ref and queue_line
        """
        queue_line = 'magento_order_data_queue_line_id'
        if not order_ref:
            queue_line = 'import_product_queue_line_id'
            order_ref = item.get('id')
        return order_ref, queue_line

    def get_magento_websites_and_descriptions(self, magento_instance_id, item):
        """
        return magento_websites, description, and short_description from the product item response.
        :param magento_instance_id:
        :param item:
        :return: magento_websites
        :return: description
        :return: short_description
        """
        description = short_description = ''
        website_ids = item.get('extension_attributes').get('website_ids')
        magento_websites = self.env[MAGENTO_WEBSITE].search([
            ('magento_website_id', 'in', website_ids),
            ('magento_instance_id', '=', magento_instance_id)
        ])
        for attribute_code in item.get('custom_attributes'):
            if attribute_code.get('attribute_code') == 'description':
                description = attribute_code.get('value')
            if attribute_code.get('attribute_code') == 'short_description':
                short_description = attribute_code.get('value')
        return magento_websites, description, short_description

    def prepare_magento_product_template_vals(self, item, magento_instance, odoo_template):
        """
        Prepare vals for the magento product template
        :param item: product vals
        :param magento_instance: magento instance
        :param odoo_template: odoo template
        :return: vals
        """
        ir_config_parameter_obj = self.env[IR_CONFIG_PARAMETER]
        if not odoo_template:
            magento_websites, description, short_description = self.get_magento_websites_and_descriptions(
                magento_instance.id, item
            )
        else:
            website_ids = item.get('extension_attributes').get('website_ids')
            magento_websites = self.env[MAGENTO_WEBSITE].search([
                ('magento_website_id', 'in', website_ids),
                ('magento_instance_id', '=', magento_instance.id)
            ])
            description = odoo_template.description_sale
            short_description = odoo_template.description
        values = {
            'magento_product_template_id': item.get('id'),
            'magento_product_name': item.get('name'),
            'magento_instance_id': magento_instance.id,
            'magento_website_ids': [(6, 0, magento_websites.ids)],
            'magento_sku': item.get('sku'),
            'product_type': item.get('type_id'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
            'odoo_product_template_id': odoo_template.id if odoo_template else False,
            'sync_product_with_magento': True,
        }
        magento_attribute_set = self.env[MAGENTO_ATTRIBUTE_SET].search(
            [('instance_id', '=', magento_instance.id), ('attribute_set_id', '=', item.get('attribute_set_id'))])
        if magento_attribute_set:
            values.update({'attribute_set_id': magento_attribute_set.id})
        magento_tax_class = ''
        for attribute_code in item.get('custom_attributes'):
            if attribute_code.get('attribute_code') == 'tax_class_id':
                magento_tax = self.env['magento.tax.class'].search([
                    ('magento_instance_id', '=', magento_instance.id),
                    ('magento_tax_class_id', '=', attribute_code.get('value'))])
                magento_tax_class = magento_tax.id
        if magento_tax_class:
            values.update({'magento_tax_class': magento_tax_class})
        magento_categories_dict = []
        if 'category_links' in item.get('extension_attributes'):
            for attribute_code in item.get('extension_attributes').get('category_links'):
                magento_categories_dict.append(attribute_code.get('category_id'))
            if magento_categories_dict:
                magento_categories = self.env['magento.product.category'].search([
                    ('instance_id', '=', magento_instance.id),
                    ('category_id', 'in', magento_categories_dict)])
                values.update({'category_ids': [(6, 0, magento_categories.ids)]})
        if ir_config_parameter_obj.sudo().get_param(SET_MAGENTO_SALES_DESCRIPTION):
            values.update({
                'description': description,
                'short_description': short_description,
            })
        return values

    def check_product_template_is_exist_or_not(
            self, magento_instance, item, log_book_id, error, order_ref, queue_line, order_data_queue_line_id
    ):
        """
        This method is used for checking odoo product template exist or not.
        :param magento_instance: Instance of Magento
        :param item: Product items received from magento
        :param log_book_id: common log book object
        :param error: True if error else False
        :param order_ref: Order reference
        :param queue_line: product or order queue line
        :param order_data_queue_line_id: queue line object
        :return: odoo_product, common product log and error
        """
        odoo_template_id = magento_sku = False
        configurable_product_options_data = item.get('extension_attributes').get('configurable_product_options_data')
        if item.get('extension_attributes').get('configurable_product_link_data'):
            for link in item.get('extension_attributes').get('configurable_product_link_data'):
                link = json.loads(link)
                magento_sku = link.get('simple_product_sku')
                if not magento_sku:
                    continue
                odoo_template_id = self.search_odoo_product_template_exists(magento_sku, item)
                if odoo_template_id and len(odoo_template_id.attribute_line_ids) > 0 and \
                        len(odoo_template_id.attribute_line_ids) != len(configurable_product_options_data):
                    # Magento side product attribute and odoo product attribute total both are different
                    # Create log and set error as True
                    # Make queue as Failed
                    message = '%s having mismatch Attribute count' \
                              '\n%s product having %s attribute at magento side and %s Attribute at odoo side.' \
                              % (item.get('sku'), item.get('sku'),
                                 len(configurable_product_options_data),
                                 len(odoo_template_id.attribute_line_ids))
                    log_book_id.add_log_line(message, order_ref,
                                             order_data_queue_line_id, queue_line, item.get('sku'))
                    error = True
                    odoo_template_id = False
                    return odoo_template_id, log_book_id, error
                if odoo_template_id:
                    break
            odoo_template_id, error = self.create_missing_variant_of_existing_odoo_product_template(
                odoo_template_id, configurable_product_options_data, magento_instance,
                item, log_book_id, order_ref, order_data_queue_line_id, queue_line, error)
        if not error:
            odoo_template_id, error = self.create_odoo_prod_temp_based_on_configuration(
                odoo_template_id, magento_instance, item, magento_sku, log_book_id,
                order_ref, order_data_queue_line_id, queue_line, error)
        return odoo_template_id, log_book_id, error

    def search_odoo_product_template_exists(self, magento_sku, item):
        """
        Search Odoo product template exists or not.
        :param magento_sku: SKU received from Magento
        :param item: item received from Magento
        :return: odoo product template object or False
        """
        product_obj = self.env[PRODUCT_PRODUCT]
        magento_product_obj = self.env[MAGENTO_PRODUCT]
        magento_product_product = magento_product_obj.search([('magento_sku', '=', magento_sku)])
        if magento_product_product:
            existing_products = magento_product_product.odoo_product_id
        else:
            existing_products = product_obj.search([('default_code', '=', magento_sku)])
        if not existing_products:
            # not getting product.product record using SKU then search in magento.product.product.
            # product not exist in odoo variant but exist in magento variant layer
            magento_product_template = self.search([('magento_sku', '=', item.get('sku'))], limit=1)
            odoo_template_id = magento_product_template.odoo_product_template_id if \
                magento_product_template else False
        else:
            odoo_template_id = existing_products and existing_products[0].product_tmpl_id
        return odoo_template_id

    def create_missing_variant_of_existing_odoo_product_template(
            self, odoo_template_id, configurable_product_options_data, magento_instance,
            item, log_book_id, order_ref, order_data_queue_line_id, queue_line, error):
        if odoo_template_id and \
                len(odoo_template_id.attribute_line_ids) == 0 and \
                len(configurable_product_options_data) > 0:
            # Case 1: First Magento product is simple and import in odoo
            # result : There is not any variant for the imported product (In odoo layer)
            # Case 2 : Now add new variant in magento and
            # make that simple product as configurable and then import
            # result : Not create new product but add that variant in the odoo product.
            # (Which was simple before import product second time)
            if magento_instance.auto_create_product:
                attribute_line_vals = self.prepare_attribute_line_data(
                    item.get('extension_attributes').get('configurable_product_options_data')
                )
                odoo_template_id.update({'attribute_line_ids': attribute_line_vals})
                odoo_template_id._create_variant_ids()
                error = True
            else:
                message = 'In odoo : %s is simple product and Magento that product type is configurable' \
                          ' \nAnd your "Automatically Create Odoo Product If Not Found" ' \
                          ' setting is %s ' % (item.get('sku'), magento_instance.auto_create_product)
                log_book_id.add_log_line(message, order_ref, order_data_queue_line_id,
                                         queue_line, item.get('sku'))
        if odoo_template_id and \
                len(item.get('extension_attributes').get('configurable_product_link_data')) != \
                len(odoo_template_id.product_variant_ids) and \
                len(odoo_template_id.attribute_line_ids) == len(configurable_product_options_data):
            # product template exist in odoo
            # Product attribute of odoo and magento both are same
            # Product attribute value is different at odoo and magento side
            # add new value for the existing attribute in template
            if magento_instance.auto_create_product:
                self.add_new_variant_value(odoo_template_id, item)
            else:
                message = 'Relevant variant not found for %s product. ' \
                          ' \nAnd your "Automatically Create Odoo Product If Not Found" ' \
                          ' setting is %s ' % (item.get('sku'), magento_instance.auto_create_product)
                log_book_id.add_log_line(message, order_ref, order_data_queue_line_id,
                                         queue_line, item.get('sku'))
                error = True
        return odoo_template_id, error

    def create_odoo_prod_temp_based_on_configuration(
            self, odoo_template_id, magento_instance, item, magento_sku, log_book_id,
            order_ref, order_data_queue_line_id, queue_line, error):
        if (not odoo_template_id) and (not magento_instance.auto_create_product):
            message = 'Magento Product Template : %s or ' \
                      '\nAny relevant variants are not found with SKU : %s' \
                      '\nAnd your "Automatically Create Odoo Product If Not Found" setting is %s ' \
                      % (item.get('sku'), magento_sku, magento_instance.auto_create_product)
            log_book_id.add_log_line(message, order_ref, order_data_queue_line_id, queue_line, item.get('sku'))
            error = True
        elif (not odoo_template_id) and magento_instance.auto_create_product:
            odoo_template_id = self.create_odoo_product_template(item, magento_instance)
        return odoo_template_id, error

    def add_new_variant_value(self, odoo_template_id, item):
        """
        Add new value in the existing attribute. Create new variant product
        :param odoo_template_id: odoo template object
        :param item: Product Item
        :return:
        """
        if item.get('extension_attributes').get('configurable_product_options_data'):
            for option_data in item.get('extension_attributes').get('configurable_product_options_data'):
                option_data = json.loads(option_data)
                odoo_attribute, product_attribute_value_obj = self.find_odoo_attribute_and_values(
                    option_data, odoo_template_id)
                self.insert_product_attribute_values(odoo_attribute, option_data, product_attribute_value_obj)
            odoo_template_id._create_variant_ids()

    def insert_product_attribute_values(self, odoo_attribute, option_data, product_attribute_value_obj):
        if odoo_attribute and option_data.get('opt_values'):
            for opt_value in option_data.get('opt_values'):
                attrib_value = self.find_odoo_attribute_value_id(odoo_attribute, opt_value)
                if attrib_value and attrib_value.id not in product_attribute_value_obj.value_ids.ids:
                    product_attribute_value_obj.value_ids = [(4, attrib_value.id, False)]

    def find_odoo_attribute_and_values(self, option_data, odoo_template_id):
        product_attribute_obj = self.env[PRODUCT_ATTRIBUTE]
        odoo_attribute = product_attribute_obj.get_attribute(
            option_data.get('frontend_label'),
            create_variant='always',
            auto_create=True
        )
        product_attribute_value_obj = odoo_template_id.attribute_line_ids. \
            filtered(lambda x: x.attribute_id.id == odoo_attribute.id)
        return odoo_attribute, product_attribute_value_obj

    def create_odoo_product_template(self, item, magento_instance):
        """
        Create Odoo product template if not found
        :param item: Response received from magento
        :param magento_instance: Magento instance object
        :return: odoo_template
        """
        odoo_template = False
        ir_config_parameter_obj = self.env[IR_CONFIG_PARAMETER]
        product_template_obj = self.env[PRODUCT_TEMPLATE]
        extension_attributes = item.get('extension_attributes') or False
        if extension_attributes:
            attribute_line_vals = self.prepare_attribute_line_data(
                item.get('extension_attributes').get('configurable_product_options_data')
            )
            if attribute_line_vals:
                magento_websites, description, short_description = self.get_magento_websites_and_descriptions(
                    magento_instance.id, item
                )
                vals = {
                    'name': item.get('name'),
                    'type': 'product',
                    'attribute_line_ids': attribute_line_vals,
                    'sale_ok': True,
                    'purchase_ok': True,
                    'categ_id': magento_instance.import_product_category.id,
                    'invoice_policy': 'order'
                }
                if ir_config_parameter_obj.sudo().get_param(SET_MAGENTO_SALES_DESCRIPTION):
                    vals.update({
                        'description': short_description,
                        'description_sale': description,
                    })
                # set the product category based on the instance setting
                odoo_template = product_template_obj.create(vals)
        return odoo_template

    def create_magento_product_template(
            self, magento_instance, item, odoo_template, log_book_id,
            order_ref, queue_line, order_data_queue_line_id, error):
        """
        This method is used for creating a product template in odoo.
        :param magento_instance: Instance of Magento
        :param item: Product Items received from Magento
        :param odoo_template: Odoo Product Template Object
        :param log_book_id: common log book object
        :param order_ref: Order reference/ product sku
        :param queue_line: magento order data queue line object
        :param order_data_queue_line_id: magento order data queue line id
        :param error: True if any error else False
        :return: magento_product_template,log_lines
        """
        website_ids = item.get('extension_attributes').get('website_ids')
        magento_websites = self.env[MAGENTO_WEBSITE].search(
            [('magento_instance_id', '=', magento_instance.id),
             ('magento_website_id', 'in', website_ids)], limit=1)
        magento_stores = magento_websites.store_view_ids
        template_vals = self.prepare_magento_product_template_vals(
            item, magento_instance, odoo_template
        )
        magento_product_template = self.create(template_vals)
        if magento_instance.allow_import_image_of_products:
            magento_media_url = False
            if magento_stores:
                magento_media_url = magento_stores[0].base_media_url
            if magento_media_url:
                full_img_url, error = self.create_or_update_product_images(
                    magento_instance, False, magento_product_template,
                    magento_media_url, item.get('media_gallery_entries'),
                    log_book_id, order_ref, queue_line, order_data_queue_line_id, error
                )
        self._cr.commit()
        return magento_product_template, error

    def set_variant_sku(
            self, magento_instance, item, magento_template,
            magento_per_sku, log_book_id, error, order_data_queue_line_id, queue_line, order_ref
    ):
        """
        Set different product variants of Product template.
        :param magento_instance: Instance of Magento
        :param item: Product Items received from Magento
        :param magento_template: Magento Template object
        :param magento_per_sku: Dictionary of Products
        :param log_book_id: Common log book object
        :param error: If error, It returns True
        :param order_data_queue_line_id: queue line object
        :param queue_line: magento order data queue line object
        :param order_ref: Order reference/ product sku
        :return: Logs if any
        """
        magento_product_obj = self.env[MAGENTO_PRODUCT]
        odoo_product_obj = self.env[PRODUCT_PRODUCT]
        odoo_product = False
        total_configured_variant_in_magento = len(
            item.get('extension_attributes').get('configurable_product_options')) \
            if item.get('extension_attributes').get('configurable_product_options') \
            else 0
        magento_prod_type = item if item.get('type_id') == 'configurable' else False
        variation_product_data, error = self.prepare_variation_product_data_dict(
            item, magento_instance, queue_line, error, log_book_id, order_data_queue_line_id)
        delete_main_prod = False
        if variation_product_data:
            virtual_child_prod = 0
            delete_main_prod = False
            for variation_product in variation_product_data.get('items'):
                if variation_product.get('type_id') != 'simple':
                    log_line_vals = {
                        'log_lines': [(0, 0, {
                            'message': 'Product with SKU %s is virtual type product and product type %s Is Not Supported' % (variation_product.get('sku'), variation_product.get('type_id')),
                            'order_ref': variation_product.get('id'),
                            queue_line: order_data_queue_line_id
                        })]
                    }
                    virtual_child_prod += 1
                    log_book_id.write(log_line_vals)
                    error = True
                    continue
                domain = []
                attribute_value_ids = self. \
                    get_attribute_value(variation_product.get('sku'),
                                        item.get('extension_attributes').get('configurable_product_link_data'))
                domain = self.prepare_attribute_domain(
                    attribute_value_ids, domain, magento_template, odoo_product,
                    variation_product.get('sku'), total_configured_variant_in_magento)

                if total_configured_variant_in_magento > 1:
                    self.write_product_product_sku(domain, magento_template.odoo_product_template_id.id,
                                                   odoo_product, variation_product.get('sku'))

                if domain:
                    domain.append(
                        ('product_tmpl_id', '=', magento_template.odoo_product_template_id.id)
                    )
                    odoo_product = odoo_product_obj.search(domain)
                if odoo_product:
                    odoo_product.write({'default_code': variation_product.get('sku')})
                self.map_magento_product_with_magento_template(magento_instance,
                                                               variation_product.get('sku'), magento_template)
                error = magento_product_obj.create_or_update_simple_product(
                    variation_product, magento_instance, log_book_id, error,
                    magento_per_sku, order_data_queue_line_id, magento_prod_tmpl=magento_template,
                    conf_product_item=magento_prod_type, order_ref=order_ref
                )  # pass conf_product_item parameter to set Magento Product Id and Magento Product SKU
                # while import product and product is already mapped before perform import operation
            if virtual_child_prod == len(variation_product_data.get('items')):
                delete_main_prod = True
        return error, delete_main_prod

    def prepare_variation_product_data_dict(
            self, item, magento_instance, queue_line, error, log_book_id, order_data_queue_line_id):
        """
        Prepare Variation product data dictionary
        :param item: item received from Magento
        :param magento_instance: Magento instance object
        :param queue_line: sync import magento product data queue line object
        :param error: True if any error else False
        :param log_book_id: common log book object
        :param order_data_queue_line_id: sync import magento product data queue line id
        :return: dictionary of variant product
        """
        magento_product_obj = self.env[MAGENTO_PRODUCT]
        product_sku_array = []
        variation_product_data = {}
        update_product = True
        if queue_line == 'import_product_queue_line_id':
            update_product = self.env['sync.import.magento.product.queue.line'].browse(
                order_data_queue_line_id).do_not_update_existing_product
        if item.get('extension_attributes').get('configurable_product_links'):
            for product_link_data in item.get('extension_attributes').get('configurable_product_link_data'):
                product_link_data = json.loads(product_link_data)
                magento_product = magento_product_obj.sudo(). \
                    search([('magento_sku', '=', product_link_data.get('simple_product_sku')),
                            ('magento_instance_id', '=', magento_instance.id)])
                if (not magento_product) or (not magento_product.magento_product_id) or (
                        magento_product and not update_product):
                    # add this code for only append sku while product not exist in the magento product layer
                    # or product exist and not checked the "Do not update product?" checkbox.
                    # Product exist in magento layer. Because previously perform map operation.
                    # So in that case product ID not set, So we sent the request to get the product data.
                    product_sku_array.append({'sku': product_link_data.get('simple_product_sku')})
            if product_sku_array:
                variation_product_data, error = magento_product_obj. \
                    get_magento_product_by_sku(magento_instance,
                                               product_sku_array, queue_line,
                                               error, log_book_id,
                                               order_data_queue_line_id)
        return variation_product_data, error

    def prepare_attribute_domain(
            self, attribute_value_ids, domain, magento_template, odoo_product,
            sku, total_configured_variant_in_magento):
        """
        prepare the domain for the attribute
        :param attribute_value_ids:  value ids of the odoo attribute
        :param domain: domain
        :param magento_template: magento template object
        :param odoo_product: odoo product object
        :param sku: variation product sku
        :param total_configured_variant_in_magento: number of configured variant in magento (variant count)
        :return: domain
        """
        for attribute_value_id in attribute_value_ids:
            tpl = ('product_template_attribute_value_ids.product_attribute_value_id', '=', attribute_value_id)
            domain.append(tpl)
            if total_configured_variant_in_magento == 1:
                self.write_product_product_sku(domain, magento_template.odoo_product_template_id.id, odoo_product,
                                               sku)
                domain = []
        return domain

    def write_product_product_sku(self, domain, odoo_product_template_id, odoo_product, sku):
        """
        Write the sku in the odoo product product layer.
        :param domain: domain to find the odoo product
        :param odoo_product_template_id: odoo product template
        :param odoo_product: odoo product product
        :param sku: SKU
        :return:
        """
        odoo_product_obj = self.env[PRODUCT_PRODUCT]
        if domain:
            domain.append(
                ('product_tmpl_id', '=', odoo_product_template_id)
            )
            odoo_product = odoo_product_obj.search(domain)
        if odoo_product:
            odoo_product.write({'default_code': sku, 'invoice_policy': 'order'})

    def get_attribute_value(self, sku, configurable_product_link_data):
        """
        Get product attributes values by calling magento API.
        :param sku: SKU
        :param configurable_product_link_data: dictionary of child products
        :return: dictionary of attribute vals
        """
        product_attribute_obj = self.env[PRODUCT_ATTRIBUTE]
        attr_val_ids = []
        for link_data in configurable_product_link_data:
            link_data = json.loads(link_data)
            if link_data.get('simple_product_sku') == sku:
                for simple_product_data in link_data.get('simple_product_attribute'):
                    odoo_attribute = product_attribute_obj.get_attribute(
                        simple_product_data.get('label'),
                        create_variant='always',
                        auto_create=True
                    )
                    if odoo_attribute:
                        attrib_value = self.find_odoo_attribute_value_id(odoo_attribute,
                                                                         simple_product_data.get('value'))

                        attr_val_ids.append(attrib_value.id)
                break
        return attr_val_ids

    def find_odoo_attribute_value_id(self, odoo_attribute, attribute_value):
        """
        Find the value of the odoo attribute.
        :param odoo_attribute: product.attribute object
        :param attribute_value: value of the attribute
        :return: odoo attribute value
        """
        product_attribute_value_obj = self.env['product.attribute.value']
        attrib_value = product_attribute_value_obj.search([
            ('attribute_id', '=', odoo_attribute.id), ('name', '=', attribute_value)
        ], limit=1)
        if not attrib_value:
            attrib_value = product_attribute_value_obj.create({
                'attribute_id': odoo_attribute.id, 'name': attribute_value
            })
        return attrib_value

    def create_or_update_product_images(
            self, magento_instance, magento_product_id,
            magento_product_template_id, magento_media_url, media_gallery_response,
            log_book_id, order_ref, queue_line, order_data_queue_line_id, error
    ):
        """
        If product image not found, then create new product image other wise update it.
        :param magento_instance: Instance of Magento
        :param magento_product_id: Magento Product product Object
        :param magento_product_template_id: Magento Product Template Object
        :param magento_media_url: Magento Instance Media URL
        :param media_gallery_response: Product Images received from Magento
        :param log_book_id: common log book object
        :param order_ref: Order reference/ product sku
        :param queue_line: magento order data queue line object
        :param order_data_queue_line_id: magento order data queue line id
        :param error: True if any error else False
        """
        full_image_url = ''
        product_id = product_template_id = False
        if magento_product_id:
            product_id = magento_product_id.odoo_product_id
        if magento_product_template_id:
            product_template_id = magento_product_template_id.odoo_product_template_id
        for image_url in media_gallery_response:
            full_image_url = self.get_image_full_url(image_url, magento_media_url)
            prod_image = False
            try:
                prod_image = self.env['common.product.image.ept'].get_image_ept(full_image_url)
            except Exception:
                message = "%s \nCan't find image.\nPlease provide valid Image URL." % full_image_url
                log_book_id.add_log_line(message, order_ref, order_data_queue_line_id, queue_line,
                                         magento_product_template_id.magento_sku if magento_product_template_id else False)
                error = True
            if prod_image:
                magento_prod_image = self.get_and_set_product_images(
                    magento_product_id, magento_product_template_id, full_image_url,
                    image_url.get('types'), product_id, product_template_id, prod_image
                )
                if not magento_prod_image:
                    self.create_magento_product_image(
                        prod_image, magento_product_id, product_id, magento_product_template_id,
                        product_template_id, magento_instance, full_image_url, image_url)
                elif not magento_prod_image.odoo_image_id:
                    magento_prod_image.write({'odoo_image_id': magento_prod_image.id})
        return full_image_url, error

    @staticmethod
    def get_image_full_url(image_url, magento_media_url):
        full_image_url = ''
        file_url = image_url.get('file')
        if file_url:
            full_image_url = magento_media_url + 'catalog/product' + file_url
        return full_image_url

    def create_magento_product_image(
            self, prod_image, magento_product_id, product_id, magento_product_template_id,
            product_template_id, magento_instance, full_image_url, image_url):
        """

        :param prod_image: Base64 encoded image
        :param magento_product_id: Magento product product object
        :param product_id: product id
        :param magento_product_template_id: Magento product template object
        :param product_template_id: product template id
        :param magento_instance: Magento instance object
        :param full_image_url: Full image URL of product
        :param image_url: Image details received from Magento
        """
        common_prod_image = False
        if magento_product_id:
            common_prod_image = self.get_common_product_image(product_id, prod_image)
        elif magento_product_template_id:
            common_prod_image = self.get_common_product_image(product_template_id, prod_image)
        product_image_values = self.prepare_product_image_vals(
            magento_instance.id, product_id, product_template_id, full_image_url, prod_image,
            magento_product_id, magento_product_template_id, image_url.get('id')
        )
        if not common_prod_image:
            common_prod_image = self.env['common.product.image.ept'].create(product_image_values)
        else:
            common_prod_image.write({
                'magento_image_ids': product_image_values.get('magento_image_ids')})
        common_prod_image.magento_image_ids

    @staticmethod
    def get_common_product_image(product, product_image):
        """
        Search and get common product image.
        :param product: product/ product template object
        :param product_image: product image
        :return: common product image object
        """
        return product.ept_image_ids.filtered(lambda x: x.image == product_image)

    def get_and_set_product_images(
            self, magento_product_id, magento_product_template_id,
            full_image_url, image_type, product_id, product_template_id, prod_image
    ):
        """
        Set product/ product template main image and get magento product/ product template image.
        :param magento_product_id: Magento product product object
        :param magento_product_template_id: Magento product template object
        :param full_image_url: Full image url
        :param image_type: Image type
        :param product_id: Product product object
        :param product_template_id: Product template object
        :param prod_image: Product image
        :return: Magento product image object or False
        """
        magento_prod_image = False
        if magento_product_id:
            if image_type and 'image' in image_type and product_id.image_1920 != prod_image:
                product_id.image_1920 = prod_image
            if product_id.image_1920 != prod_image:
                magento_prod_image = self.env[MAGENTO_PRODUCT_IMAGE].search([
                    ('magento_product_id', '=', magento_product_id.id), ('url', '=', full_image_url)])
            else:
                magento_prod_image = self.env[MAGENTO_PRODUCT_IMAGE].search([
                    ('magento_product_id', '=', magento_product_id.id), ('image', '=', prod_image),
                    ('sequence', '=', 0)])
        elif magento_product_template_id:
            if image_type and 'image' in image_type:
                product_template_id.image_1920 = prod_image
            if product_template_id.image_1920 != prod_image:
                magento_prod_image = self.env[MAGENTO_PRODUCT_IMAGE].search([
                    ('magento_tmpl_id', '=', magento_product_template_id.id), ('url', '=', full_image_url)
                ])
            else:
                magento_prod_image = self.env[MAGENTO_PRODUCT_IMAGE].search([
                    ('magento_tmpl_id', '=', magento_product_template_id.id), ('image', '=', prod_image),
                    ('sequence', '=', 0)
                ])
        return magento_prod_image

    def prepare_product_image_vals(
            self, magento_instance_id, product_id, product_template_id, full_image_url,
            prod_image, magento_prod_id, magento_tmpl_id, image_id
    ):
        """
        Prepare dictionary for Product images
        :param magento_instance_id: Magento instance id
        :param product_id: Product product object
        :param product_template_id: Product template object
        :param full_image_url: Full image url
        :param prod_image: Product image
        :param magento_prod_id: Magento product id
        :param magento_tmpl_id: Magento product template id
        :param image_id: Image id
        :return: Dictionary for Product images
        """
        product_image_vals = {
            'product_id': product_id.id if product_id else False,
            'template_id': product_template_id.id if product_template_id else False,
            'url': full_image_url or '',
            'image': prod_image,
            'magento_image_ids': [(0, 0, {
                'magento_product_id': magento_prod_id.id if magento_prod_id else False,
                'magento_tmpl_id': magento_tmpl_id.id if magento_tmpl_id else False,
                'magento_image_id': image_id,
                'url': full_image_url or '',
                'image': prod_image,
                'magento_instance_id': magento_instance_id,
            })]
        }
        return product_image_vals

    def map_magento_product_with_magento_template(self, magento_instance, sku, magento_template):
        """
        This method is used to check magento product exist or not in odoo
        :param magento_instance: Instance of Magento
        :param sku: Magento Product SKU
        :param magento_template: Magento Product Template
        """
        magento_product_obj = self.env[MAGENTO_PRODUCT]
        magento_product = magento_product_obj.search([
            ('magento_sku', '=', sku),
            ('magento_instance_id', '=', magento_instance.id)
        ])
        if magento_product and magento_template and magento_product.magento_tmpl_id != magento_template \
                and magento_product.magento_tmpl_id.total_magento_variants > 1:
            # add last condition for while all simple product is in odoo layer.
            # all those is configurable's simple product in magento side
            # after map import that specific product
            # stop to overwride magento template in magento product.
            magento_product.magento_tmpl_id = magento_template.id

    def prepare_attribute_line_data(self, configurable_options):
        """
        This method is used to prepare attribute line  for set attribute line ids in template.
        :param configurable_options: Configurable product attributes options
        :return: Dictionary of Attribute values
        """
        attrib_line_vals = []
        attribute_line_ids_data = False
        if configurable_options:
            for option in configurable_options:
                attribute_data = json.loads(option)
                if attribute_data.get('frontend_label'):
                    odoo_attribute = self.env[PRODUCT_ATTRIBUTE].get_attribute(
                        attribute_data.get('frontend_label'),
                        create_variant='always',
                        auto_create=True
                    )
                    attr_val_ids = []
                    for option_values in attribute_data.get('opt_values'):
                        attrib_value = self.find_odoo_attribute_value_id(odoo_attribute,
                                                                         option_values)
                        attr_val_ids.append(attrib_value.id)
                    attribute_line_ids_data = (0, 0, {'attribute_id': odoo_attribute.id, 'value_ids': attr_val_ids})
                if attribute_line_ids_data:
                    attrib_line_vals.append(attribute_line_ids_data)
        return attrib_line_vals

    def open_variant_list(self):
        """
        This method used for smart button for view variant.
        @return: Action
        """
        form_view_id = self.env.ref('odoo_magento2_ept.view_magento_product_form').id
        tree_view = self.env.ref('odoo_magento2_ept.view_magento_product_tree').id
        action = {
            'name': 'Magento Product Variant',
            'type': IR_ACTIONS_ACT_WINDOW,
            'view_type': 'form',
            'view_mode': 'tree',
            'res_model': MAGENTO_PRODUCT,
            'views': [(tree_view, 'tree'), (form_view_id, 'form')],
            'view_id': tree_view,
            'target': 'current',
            'domain': [('id', 'in', self.magento_product_ids.ids)]
        }
        return action

    def open_export_product_in_magento_ept_wizard(self):
        view = self.env.ref('odoo_magento2_ept.magento_export_products_ept_wizard')
        return {
            'type': IR_ACTIONS_ACT_WINDOW,
            'view_mode': 'form',
            'res_model': 'magento.export.product.ept',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
        }

    def export_products_in_magento(
            self, instance, magento_templates, magento_is_set_price,
            magento_publish, magento_is_set_image, attribute_set_id, common_log_id):
        """
        Export New product in Magento from odoo
        :param instance: Magento Instance
        :param magento_templates: Magento product template record
        :param magento_is_set_price: Set price in magento ?
        :param magento_publish: Publish new product in Magento ?
        :param magento_is_set_image: Upload the magento product template
        record image in magento product ?
        :param attribute_set_id: Create product under which attribute set?
        :param common_log_id: Log book record ID
        :return:
        """
        start = time.time()
        simple_product_tmpl = magento_templates.filtered(
            lambda x: x.product_type == 'simple' and not x.sync_product_with_magento)
        if len(simple_product_tmpl) > 0:
            self.export_simple_product(
                instance, simple_product_tmpl, magento_is_set_price,
                magento_publish, magento_is_set_image, attribute_set_id, common_log_id)

        configurable_product_tmpl = magento_templates.filtered(
            lambda x: x.product_type == 'configurable' and not x.sync_product_with_magento)
        if len(configurable_product_tmpl) > 0:
            self.export_configurable_product(
                instance, configurable_product_tmpl, magento_is_set_price,
                magento_publish, magento_is_set_image, attribute_set_id, common_log_id)
        end = time.time()
        _logger.info("Exported total templates  %s  in %s seconds.", len(magento_templates), str(end - start))
        return True

    def export_simple_product(
            self, instance, simple_product_tmpl, magento_is_set_price,
            magento_publish, magento_is_set_image, attribute_set_id, common_log_id):
        """
        Export simple product in magento
        :param instance: Magento Instance
        :param simple_product_tmpl: Simple product template
        :param magento_is_set_price: set price ?
        :param magento_publish: Publish product in magento ?
        :param magento_is_set_image: Set image ?
        :param attribute_set_id: Under which attribute set create a simple product ?
        :param common_log_id: Log book ID
        :return:
        """
        for product in simple_product_tmpl:
            _logger.info("start create new simple product : %s ", product.magento_sku)
            self.create_simple_configurable_product_in_magento(
                instance, product, magento_is_set_price, magento_publish,
                magento_is_set_image, attribute_set_id, common_log_id, product_type='simple')

    def export_configurable_product(
            self, instance, configurable_product_tmpl, magento_is_set_price,
            magento_publish, magento_is_set_image, attribute_set_id, common_log_id):
        """
        Export Configurable product in odoo
        :param instance: Instance record
        :param configurable_product_tmpl: Configurable product template
        :param magento_is_set_price: Set price ?
        :param magento_publish: Publish product in Magento ?
        :param magento_is_set_image: Upload image in magento ?
        :param attribute_set_id: Under which attribute set create the product?
        :param common_log_id: log book ID
        :return:
        """
        for product in configurable_product_tmpl:
            _logger.info("start create new configurable product name : %s ", product)
            self.create_simple_configurable_product_in_magento(
                instance, product, magento_is_set_price, magento_publish,
                magento_is_set_image, attribute_set_id, common_log_id, product_type='configurable')
            magento_attribute_option_obj = self.env[MAGENTO_ATTRIBUTE_OPTION]
            if product.attribute_line_ids:
                magento_attribute_obj = self.env[MAGENTO_PRODUCT_ATTRIBUTE]
                conf_product_sku = product.magento_product_name
                configurable_opt_vals = self.prepare_configurable_option_vals(
                    conf_product_sku, common_log_id, instance, product, attribute_set_id)
                if configurable_opt_vals:
                    continue
                for product_product in product.magento_product_ids:
                    if product_product.product_template_attribute_value_ids:
                        vals = []
                        for value_id in product_product.product_template_attribute_value_ids:
                            magento_attribute_option = magento_attribute_option_obj.search([
                                ('instance_id', '=', instance.id), ('odoo_option_id', '=', value_id.product_attribute_value_id.id)
                            ], limit=1)
                            if not magento_attribute_option:
                                _logger.info(
                                    "%s attribute option still not sync with odoo."
                                    , value_id.product_attribute_value_id.name)
                                break
                            magento_attribute = magento_attribute_obj. \
                                browse(magento_attribute_option.magento_attribute_id.id)
                            if not magento_attribute:
                                _logger.info(
                                    "Value not sync for %s attribute"
                                    " option in odoo.", value_id.product_attribute_value_id.name)
                                break
                            attribute_code = magento_attribute.magento_attribute_code
                            attribute_val = {
                                "attribute_code": attribute_code.lower(),
                                "value": magento_attribute_option.magento_attribute_option_id
                            }
                            product_product.magento_product_name = product_product.magento_product_name + "_" + magento_attribute_option.magento_attribute_option_name
                            vals.append(attribute_val)
                        self.create_simple_configurable_product_in_magento(instance, product_product,
                                                                           magento_is_set_price, magento_publish,
                                                                           magento_is_set_image, attribute_set_id,
                                                                           common_log_id, product_type='simple',
                                                                           is_it_child=True, custom_attributes=vals)

                self.bind_simple_with_configurable_product(instance,
                                                           product.magento_product_ids.mapped('magento_sku'),
                                                           conf_product_sku, common_log_id)

    def create_simple_configurable_product_in_magento(
            self, instance, product, magento_is_set_price, magento_publish, magento_is_set_image,
            attribute_set_id, common_log_book_id, product_type='simple', is_it_child=False, custom_attributes=[]):
        """
        Create the simple or configurable product in magento
        :param instance: Magento Instance
        :param product: Product.template
        :param magento_is_set_price: set price in magento ?
        :param magento_publish: Publish in magento ?
        :param magento_is_set_image: Upload image ?
        :param attribute_set_id: Under which Attribute set create a new product ?
        :param common_log_book_id: Log book record
        :param product_type: Product type
        :param is_it_child: Is the product is child of any configurable product
        :param custom_attributes: Custom Attribute array
        :return:
        """
        response = False
        configurable_custom_attributes = custom_attributes
        custom_attributes = self.prepare_main_product_description_array(custom_attributes, product)

        website_ids, category = self.find_category_website_for_the_product(product_type, is_it_child, product, instance)
        attribute_set = self.get_magento_attribute_set(
            product, product_type, is_it_child, attribute_set_id, common_log_book_id)
        conf_simple_product = self.get_simple_product(is_it_child, product, product_type)
        sku = product.magento_sku if product.magento_sku else product.magento_product_name
        data = {
            "product": {
                "sku": sku,
                "name": product.magento_product_name,
                "attribute_set_id": attribute_set,
                "status": 1 if magento_publish == "publish" else 0,
                "visibility": 4 if not is_it_child else 1,
                "type_id": product_type,
                "extension_attributes": {
                    "category_links": category or []
                },
                "custom_attributes": []
            }
        }
        ## Add below code for set configurable product's tax class in its child product
        main_product_tmpl = product if not is_it_child else product.magento_tmpl_id
        if main_product_tmpl and main_product_tmpl.magento_tax_class:
            magento_tax_class = {
                "attribute_code": "tax_class_id", "value": main_product_tmpl.magento_tax_class.magento_tax_class_id
            }
            data['product']['custom_attributes'].append(magento_tax_class)
        if configurable_custom_attributes:
            for configurable_opt in configurable_custom_attributes:
                if (configurable_opt.get('attribute_code') != 'description' and
                        configurable_opt.get('attribute_code') != 'short_description'):
                    data['product']['custom_attributes'].append(configurable_opt)
        if website_ids:
            magento_website_id = []
            for website in website_ids:
                website_store_view = self.search_website_vise_store_views(website, instance)
                currency = website.magento_base_currency.id
                for store in website_store_view:
                    data['product']['price'] = self.get_magento_product_price(
                        instance, conf_simple_product, magento_is_set_price, website, currency, common_log_book_id)
                    try:
                        if custom_attributes:
                            data = self.translate_description_and_short_description(
                                data, store, custom_attributes, product,
                                configurable_custom_attributes)
                        api_url = '/%s/V1/products' % store.magento_storeview_code
                        response = req(instance, api_url, 'POST', data)
                    except Exception as error:
                        common_log_book_id.write({
                            'log_lines': [(0, 0, {
                                'message': "%s \nNot able to create new Simple"
                                           " Product in Magento. SKU : %s" % (error, product.magento_sku),
                                'default_code': product.magento_sku
                            })]
                        })
                        return True

                magento_website_id.append(int(website.magento_website_id))
            self.set_website_in_product(
                instance, product, magento_website_id, common_log_book_id,
                product_type, custom_attributes, is_it_child, magento_is_set_image)
            _logger.info("Website set for product %s ", sku)
        else:
            common_log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': "Website not set in the product template, So we can't create new"
                               " Product in Magento with SKU : %s" % product.magento_sku,
                    'default_code': product.magento_sku
                })]
            })
            return True
        if response:
            self.write_product_id_in_odoo(response, product_type, is_it_child, product)
        if not common_log_book_id.log_lines:
            magento_product_images = self.get_magento_product_images(product, product_type, is_it_child)
            for magento_product_image in magento_product_images:
                magento_product_image.write({'exported_in_magento': True})

    @staticmethod
    def get_magento_product_images(simple_product_tmpl, product_type, is_it_child):
        if product_type == 'configurable' and not is_it_child:
            magento_product_images = simple_product_tmpl.magento_product_image_ids.filtered(
                lambda x: not x.exported_in_magento and not x.magento_product_id)
        elif product_type == 'simple' and is_it_child:
            magento_product_images = simple_product_tmpl.magento_product_image_ids.filtered(
                lambda x: not x.exported_in_magento and x.magento_product_id)
        else:
            magento_product_images = simple_product_tmpl.magento_product_image_ids.filtered(
                lambda x: not x.exported_in_magento)
        return magento_product_images

    def prepare_main_product_description_array(self, custom_attributes, product):
        sale_description_export = self.env[IR_CONFIG_PARAMETER].sudo().get_param(
            SET_MAGENTO_SALES_DESCRIPTION)
        if sale_description_export:
            if product.description:
                description = {"attribute_code": "description", "value": product.description}
                custom_attributes.append(description)
            if product.short_description:
                short_description = {"attribute_code": "short_description", "value": product.short_description}
                custom_attributes.append(short_description)
        return custom_attributes

    def find_category_website_for_the_product(self, product_type, is_it_child, product, instance):
        """
        Prepare the data for the website ID, Category ID
        :param product_type: Magento Product type
        :param is_it_child: True if product is child of configurable product
        :param product: product template object
        :param instance: Magento instance object
        :return: dictionary of categories
        """
        category = []
        if product_type == "simple" and is_it_child:
            category_ids = product.magento_tmpl_id.category_ids
            website_ids = self.get_magento_website_ids(instance, product.magento_tmpl_id)
        else:
            category_ids = product.category_ids
            website_ids = self.get_magento_website_ids(instance, product)
        for cat in category_ids:
            category.append({"position": 0, "category_id": cat.category_id})
        return website_ids, category

    @staticmethod
    def get_magento_website_ids(instance, product):
        if product.export_product_to_all_website:
            website_ids = instance.magento_website_ids
        else:
            website_ids = product.magento_website_ids
        return website_ids

    @staticmethod
    def get_magento_attribute_set(product, product_type, is_it_child, attribute_set_id, common_log_book_id):
        if product_type == 'simple' and is_it_child and not attribute_set_id:
            attribute_set = product.magento_tmpl_id.attribute_set_id.attribute_set_id
        elif not attribute_set_id:
            attribute_set = attribute_set_id.attribute_set_id if attribute_set_id \
                else product.attribute_set_id.attribute_set_id
        else:
            attribute_set = attribute_set_id.attribute_set_id
        if not attribute_set:
            common_log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': "Attribute set not set in the product template and wizard."
                               " \nNot able to create new Simple"
                               " Product in Magento. SKU : %s" % product.magento_sku,
                    'default_code': product.magento_sku
                })]
            })
        return attribute_set

    def get_magento_product_price(self, instance, conf_simple_product, magento_is_set_price, website, currency, common_log_book_id):
        product_price = 0

        if magento_is_set_price and instance.catalog_price_scope == 'global':
            product_price = self.get_scope_wise_product_price(
                instance, common_log_book_id, conf_simple_product, instance.pricelist_id)
        elif magento_is_set_price and instance.catalog_price_scope == 'website':
            price_list = website.pricelist_ids.filtered(lambda x: x.currency_id.id == currency)
            if price_list:
                price_list = price_list[0]
                product_price = self.get_scope_wise_product_price(instance, common_log_book_id, conf_simple_product, price_list)
        return product_price

    @staticmethod
    def get_scope_wise_product_price(instance, common_log_book_id, product, price_list):
        """
        Get product price based on the price scope
        :param instance:  Magento Instance Object
        :param common_log_book_id: Common Log book object
        :param product: Product.product object
        :param price_list: Product Price list object
        :return:
        """
        product_price = 0
        _logger.info("Instance %s price scope is Global.", instance.name)
        if price_list:
            product_price = price_list.get_product_price(product.odoo_product_id, price_list.id, False)
            _logger.info("Product : {} and product price is : {}".format(product.odoo_product_id.name, product_price))
        else:
            common_log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': "Still price list not set for the Instance : %s" % instance.name
                })]
            })
        return product_price

    @staticmethod
    def get_simple_product(is_it_child, product, product_type=False):
        if (not product_type or product_type and product_type == "simple") and is_it_child:
            conf_simple_product_product = product
        else:
            conf_simple_product_product = product.magento_product_ids[0] if \
                len(product.magento_product_ids) > 1 else product.magento_product_ids
        return conf_simple_product_product

    def prepare_export_images_values(self, simple_product_tmpl, product_type, is_it_child):
        """
        Prepare the product main and child image vals
        :param simple_product_tmpl: Simple product template
        :return:
        """
        media_gallery = []
        temp = 1
        main_product_img = False
        child_img = []
        if product_type == 'configurable' and not is_it_child:
            magento_product_images = simple_product_tmpl.magento_product_image_ids.filtered(
                lambda x: not x.magento_product_id)
        elif product_type == 'simple' and is_it_child:
            magento_product_images = simple_product_tmpl.magento_product_image_ids.filtered(
                lambda x: x.magento_product_id)
        else:
            magento_product_images = simple_product_tmpl.magento_product_image_ids
        if simple_product_tmpl.image_1920:
            main_product_img = simple_product_tmpl.image_1920
        for magento_product_image in magento_product_images:
            if main_product_img and magento_product_image.image == main_product_img and not magento_product_image.name:
                continue
            child_img.append(magento_product_image)
        if magento_product_images and not main_product_img and product_type == 'simple' and is_it_child:
            main_product_img = simple_product_tmpl.magento_tmpl_id.magento_product_image_ids.filtered(
                lambda x: x.sequence == 0 and not x.magento_product_id).image

        sku = simple_product_tmpl.magento_sku if simple_product_tmpl.magento_sku \
            else simple_product_tmpl.magento_product_name
        if main_product_img:
            self.prepare_export_image_values_dict(main_product_img, sku, temp, media_gallery, True)
        if child_img:
            for child_image in child_img:
                temp += 1
                self.prepare_export_image_values_dict(child_image.image, sku, temp, media_gallery, False)
        return media_gallery

    def prepare_export_image_values_dict(self, image, sku, temp, media_gallery, is_main_img):
        cimg_format = self.find_export_image_format(image)
        cimg_base64 = image.decode()
        img_name = sku + "_%s.%s" % (temp, cimg_format)
        cimg_vals = self.prepare_image_vals_ept(cimg_base64, img_name, cimg_format, is_main_img)
        media_gallery.append(cimg_vals)

    @staticmethod
    def find_export_image_format(img):
        """
        Find th product image format
        :param img:  Image
        :return:
        """
        image_stream = io.BytesIO(codecs.decode(img, "base64"))
        image = Image.open(image_stream)
        img_format = image.format
        return img_format.lower()

    def prepare_image_vals_ept(self, img_base64, name, format, is_main_img=False):
        """
        Prepare the Product IMage vals
        :param img_base64: Image Base64 code
        :param name: Image name
        :param format: Image format
        :param is_main_img: Is the product main image?
        :return:
        """
        img_val = {
            "mediaType": "image",
            "label": name,
            "position": 0,
            "disabled": False,
            "types": ["image", "small_image", "thumbnail"] if is_main_img else [],
            "file": "",
            "content": {
                "Base64EncodedData": img_base64,
                "Type": "image/%s" % format,
                "Name": "%s" % name
            }
        }
        return img_val

    def search_website_vise_store_views(self, website, instance):
        """
        Find the store code for the store
        :param website: Magento website
        :param instance: Magento Instance
        :return:
        """
        return self.env[MAGENTO_STOREVIEW].search([
            ('magento_website_id', '=', website.id), ('magento_instance_id', '=', instance.id)])

    @staticmethod
    def translate_description_and_short_description(
            export_product_data, store_view, custom_attributes,
            simple_product_tmpl, configurable_custom_attributes=[]):
        """
        convert the description and short description based on the store view lang
        :param export_product_data:
        :param store_view:
        :param custom_attributes:
        :param simple_product_tmpl:
        :return:
        """
        for attribute in custom_attributes:
            if attribute.get('attribute_code') == "description":
                product_description = simple_product_tmpl.with_context(lang=store_view.lang_id.code).description
                export_product_data['product']['custom_attributes'].append({'attribute_code': 'description', 'value': product_description})
            if attribute.get('attribute_code') == "short_description":
                product_short_description = simple_product_tmpl.with_context(
                    lang=store_view.lang_id.code).short_description
                export_product_data['product']['custom_attributes'].append({'attribute_code': 'short_description',
                                                'value': product_short_description})
        export_product_data['product']['name'] = simple_product_tmpl.\
            with_context(lang=store_view.lang_id.code).magento_product_name
        return export_product_data

    def set_website_in_product(
            self, instance, product, website_id, common_log_id,
            product_type, custom_attributes, is_it_child, magento_is_set_image):
        """
        Set website in magento product
        :param instance: Magento Instance
        :param product: Magento product object
        :param website_id: website ID
        :param common_log_id: log book record
        :param product_type: Magento product type
        :param custom_attributes: dictionary of custom attributes
        :param is_it_child: True if product is child product else False
        :param magento_is_set_image: True if export images else False
        :return:
        """
        try:
            conf_product_name = product.magento_product_name
            sku = product.magento_sku if product.magento_sku else product.magento_product_name
            api_url = '/all/V1/products/%s' % Php.quote_sku(sku)
            data = {
                "product": {
                    "sku": sku,
                    "name": conf_product_name,
                    "extension_attributes": {
                        "website_ids": website_id
                    },
                    "custom_attributes": custom_attributes
                }
            }
            if magento_is_set_image:
                media_gallery = self.prepare_export_images_values(product, product_type, is_it_child)
                if media_gallery:
                    data['product']['media_gallery_entries'] = media_gallery
            req(instance, api_url, 'PUT', data)
        except Exception:
            common_log_id.write({
                'log_lines': [(0, 0, {
                    'message': "Not able to assign website for product SKU : %s" % sku,
                    'default_code': sku
                })]
            })

    def write_product_id_in_odoo(self, response, product_type, is_it_child, product):
        """
        after response received set the product id in odoo and make that product is Sync with magento as true
        :param response: API response
        :param product_type: Product type
        :param is_it_child: Is this product child product of any configurable product
        :param product: product
        :return:
        """
        _logger.info("Product created in magento successfully with Product SKU : %s and "
                     "Product ID : %s" % (response.get('sku'), response.get('id')))
        if product_type == "simple" and not is_it_child:
            product.write({'sync_product_with_magento': True, "magento_product_template_id": response.get('id')})
            _logger.info("Sync product with magento.product.template successfully")
            if len(product.magento_product_ids) == 1:
                product.magento_product_ids.write(
                    {"magento_product_id": response.get('id'), "sync_product_with_magento": True})
                _logger.info("Sync product with magento.product.product successfully")
        elif product_type == "configurable":
            product.write({
                'sync_product_with_magento': True,
                "magento_product_template_id": response.get('id'),
                "magento_sku": response.get('sku')})
        else:
            product.write({"magento_product_id": response.get('id'), "sync_product_with_magento": True})
        self._cr.commit()
        return False

    def prepare_configurable_option_vals(self, conf_product_sku, common_log_book_id, instance, product, attribute_set_id):
        """
        Prepare the Vals for the configurable product options
        :param conf_product_sku: SKU for the configurable product
        :param common_log_book_id: Log book record
        :param instance: Magento Instance
        :return:
        """
        magento_att_obj = self.env[MAGENTO_PRODUCT_ATTRIBUTE]
        attribute_line = product.attribute_line_ids
        skip = False
        for line in attribute_line:
            magento_att = magento_att_obj.search([
                ('odoo_attribute_id', '=', line.attribute_id.id),
                ('instance_id', '=', instance.id),
            ], limit=1)
            if not magento_att:
                magento_att = self.create_magento_attribute(line.attribute_id, instance)
            attribute_options = self.get_magneto_attribute_options(magento_att, instance, line.value_ids)
            if magento_att and not magento_att.magento_attribute_id:
                skip = self.export_product_attribute_in_magento(
                    magento_att, instance, common_log_book_id, conf_product_sku, attribute_options)
                if skip:
                    return True
            elif magento_att and attribute_options:
                self.export_product_attribute_options_in_magento(
                    magento_att, instance, common_log_book_id, conf_product_sku, attribute_options)
            is_attribute_assigned = self.attribute_exists_in_attribute_set_in_magento(
                instance, attribute_set_id, magento_att.magento_attribute_id)
            if not is_attribute_assigned and attribute_set_id:
                skip = self.assign_attribute_to_attribute_set_in_magento(
                    instance, product, attribute_set_id, common_log_book_id, magento_att.magento_attribute_id)
                if skip:
                    return True
            if magento_att:
                opt_val = {
                    "option": {
                        "attribute_id": magento_att.magento_attribute_id,
                        "label": magento_att.name,
                        "position": 0,
                        "is_use_default": True,
                        "values": [
                            {
                                "value_index": line.id
                            }
                        ]
                    }
                }
                try:
                    api_url = '/V1/configurable-products/%s/options' % Php.quote_sku(conf_product_sku)
                    req(instance, api_url, 'POST', opt_val)
                except Exception:
                    common_log_book_id.write({
                        'log_lines': [(0, 0, {
                            'message': "Not able to assign option for product SKU : %s" % conf_product_sku,
                            'default_code': conf_product_sku
                        })]
                    })
                    return True
            else:
                # this else for attribute is not for the Magento
                common_log_book_id.write({
                    'log_lines': [(0, 0, {
                        'message': "Can't find attribute option in "
                                   "Magento Attribute Option list : %s" % line.attribute_id.name
                    })]
                })
                return True
        return skip

    def create_magento_attribute(self, attribute_id, instance_id):
        attribute_options = self.prepare_attribute_options_dict(attribute_id, instance_id)
        attribute_name = attribute_id.name.replace(" ", "_")
        attribute_values = {
            'name': attribute_id.name,
            'odoo_attribute_id': attribute_id.id,
            'instance_id': instance_id.id,
            'magento_attribute_code': attribute_name,
            'frontend_label': attribute_id.name,
            'attribute_type': 'select',
            'option_ids': attribute_options
        }
        return self.env[MAGENTO_PRODUCT_ATTRIBUTE].create(attribute_values)

    @staticmethod
    def prepare_attribute_options_dict(attribute_id, instance_id):
        attribute_options_dict = []
        for attribute_option in attribute_id.value_ids:
            attribute_options_dict.append((0, 0, {
                'name': attribute_option.name,
                'magento_attribute_option_name': attribute_option.name,
                'odoo_attribute_id': attribute_id.id,
                'instance_id': instance_id.id,
                'odoo_option_id': attribute_option.id
            }))
        return attribute_options_dict

    def export_product_attribute_in_magento(
            self, magento_attribute, instance, common_log_book_id, sku, attribute_options):
        magento_option_obj = self.env[MAGENTO_ATTRIBUTE_OPTION]
        attribute_code = magento_attribute.magento_attribute_code.replace(" ", "_")
        attribute_data = {
            "attribute": {
                "attribute_code": attribute_code.lower(),
                "frontend_input": "select",
                "options": attribute_options,
                "default_frontend_label": magento_attribute.name,
                "is_unique": "0"
            }
        }
        try:
            api_url = '/V1/products/attributes/'
            response = req(instance, api_url, 'POST', attribute_data)
            if response:
                magento_attribute.write({'magento_attribute_id': response.get('attribute_id')})
                for attribute_value in response.get('options'):
                    magento_attr_options = magento_option_obj.search([
                        ('name', '=', attribute_value.get('label', '-')),
                        ('odoo_attribute_id', '=', magento_attribute.odoo_attribute_id.id),
                        ('magento_attribute_id', '=', magento_attribute.id)])
                    value = self.env[MAGENTO_PRODUCT_ATTRIBUTE].get_magento_attribute_values(attribute_value)
                    if value != '':
                        magento_attr_options.write({'magento_attribute_option_id': value})

        except Exception:
            common_log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': "Not able to create attribute for product SKU : %s" % sku,
                    'default_code': sku
                })]
            })
            return True
        return False

    @staticmethod
    def attribute_exists_in_attribute_set_in_magento(instance, attribute_set_id, magento_attribute_id):
        try:
            api_url = '/V1/products/attribute-sets/%s/attributes' % attribute_set_id.attribute_set_id
            magento_attributes = req(instance, api_url, 'GET')
            for magento_attribute in magento_attributes:
                if magento_attribute.get('attribute_id') == int(magento_attribute_id):
                    return True
        except Exception:
            pass
        return False

    def assign_attribute_to_attribute_set_in_magento(self, instance, product, attribute_set_id, common_log_book_id, attribute_code):
        attribute_set_id = self.get_magento_attribute_set(
            product, 'configurable', False, attribute_set_id, common_log_book_id)
        attribute_set = self.env[MAGENTO_ATTRIBUTE_SET].search([
            ('attribute_set_id', '=', attribute_set_id), ('instance_id', '=', instance.id)])
        attribute_group_id = attribute_set.attribute_group_ids[0].attribute_group_id
        attribute_data = {
            "attributeSetId": attribute_set_id,
            "attributeGroupId": attribute_group_id,
            "attributeCode": attribute_code,
            "sort_order": 10
        }
        try:
            api_url = '/V1/products/attribute-sets/attributes'
            req(instance, api_url, 'POST', attribute_data)
        except Exception:
            common_log_book_id.write({
                'log_lines': [(0, 0, {
                    'message': "Not able to assign attribute %s in attribute set : %s" % (attribute_code, attribute_set.attribute_set_name),
                    'default_code': product.magento_sku
                })]
            })
            return True
        return False

    def get_magneto_attribute_options(self, magento_attribute, instance, odoo_attribute_options):
        attribute_options = []
        for attribute_option in odoo_attribute_options:
            magento_attr_opt = self.env[MAGENTO_ATTRIBUTE_OPTION].search([
                ('magento_attribute_id', '=', magento_attribute.id), ('instance_id', '=', instance.id), ('odoo_option_id', '=', attribute_option.id)])
            if not magento_attr_opt or (magento_attr_opt and not magento_attr_opt.magento_attribute_option_id):
                attribute_options.append({"label": attribute_option.name})
        return attribute_options

    def export_product_attribute_options_in_magento(self, magento_attribute, instance, common_log_book_id, sku, attribute_options):
        for attribute_option in attribute_options:
            attribute_options_data = {"option": attribute_option}
            try:
                api_url = '/V1/products/attributes/%s/options' % magento_attribute.magento_attribute_id
                response = req(instance, api_url, 'POST', attribute_options_data)
                if response:
                    self.env[MAGENTO_PRODUCT_ATTRIBUTE].create_product_attribute_in_odoo(
                        instance, magento_attribute.magento_attribute_id, magento_attribute)
            except Exception:
                common_log_book_id.write({
                    'log_lines': [(0, 0, {
                        'message': "Not able to create attribute for product SKU : %s" % sku,
                        'default_code': sku
                    })]
                })
        return True

    @staticmethod
    def get_magento_attribute_values(attribute_value):
        if attribute_value == 0:
            value = 0
        elif attribute_value is None:
            value = None
        elif attribute_value is False:
            value = 'False'
        elif attribute_value == '':
            value = ''
        else:
            value = attribute_value
        return value

    @staticmethod
    def bind_simple_with_configurable_product(
            instance, product_magento_sku_list, conf_product_sku, common_log_id):
        """
        Bind the simple product to their configurable product
        :param instance: instance record
        :param product_magento_sku_list: Simple product SKU
        :param conf_product_sku: Configurable product SKU
        :param common_log_id: log book record ID
        :return:
        """
        for product_magento_sku in product_magento_sku_list:
            try:
                data = {
                    "childSku": product_magento_sku
                }
                api_url = '/V1/configurable-products/%s/child' % Php.quote_sku(conf_product_sku)
                req(instance, api_url, 'POST', data)
            except Exception:
                common_log_id.write({
                    'log_lines': [(0, 0, {
                        'message': "Not able to Bind simple product : %s with "
                                   "Configurable Product : %s in Magento."
                                   "Possibly, Magento configurable product attributes are not of type dropdown." % (product_magento_sku, conf_product_sku),
                        'default_code': product_magento_sku
                    })]
                })

    def update_products_in_magento_ept(
            self, instance, magento_templates, update_img, update_price,
            basic_details, common_log_id, update_description):
        """
        Update product in Magento
        :param instance: Magento Instance
        :param magento_templates: Product template record
        :param update_img: Upload image ?
        :param update_price: Upload price?
        :param basic_details: Basic details need to change ?
        :param common_log_id: log book record
        :param update_description: Update product description and short description ?
        :return:
        """
        start = time.time()
        sale_description_export = self.env[IR_CONFIG_PARAMETER].sudo().get_param(
            SET_MAGENTO_SALES_DESCRIPTION)
        simple_product_tmpl = magento_templates.filtered(lambda x: x.product_type == 'simple')
        if len(simple_product_tmpl) > 0:
            for simple_product in simple_product_tmpl:
                self.update_simple_configurable_product(
                    instance, simple_product, update_img, update_price, basic_details,
                    common_log_id, is_child_product=False, update_description=update_description)

        configurable_product_tmpl = magento_templates.filtered(lambda x: x.product_type == 'configurable')
        if len(configurable_product_tmpl) > 0:
            for conf_product in configurable_product_tmpl:
                custom_attributes = []
                vals = {
                    "product": {
                        "name": conf_product.magento_product_name,
                        "custom_attributes": [],
                        "extension_attributes": {
                            "category_links": [],
                            "website_ids": []
                        }
                    }
                }
                if conf_product.magento_product_ids:
                    if sale_description_export and update_description:
                        if conf_product.description:
                            description = {
                                "attribute_code": "description",
                                "value": conf_product.description
                            }
                            custom_attributes.append(description)

                        if 'short_description' in conf_product:
                            description_sale = conf_product.short_description
                        if description_sale:
                            short_description = {
                                "attribute_code": "short_description",
                                "value": description_sale
                            }
                            custom_attributes.append(short_description)
                        vals['product']['custom_attributes'] = custom_attributes or []
                    category_ids = conf_product.category_ids
                    magento_website_ids, store_code_list = self.find_website_and_store_code_list(conf_product,
                                                                                                 instance)
                    if basic_details:
                        magento_tax_class = False
                        if conf_product.magento_tax_class:
                            magento_tax_class = conf_product.magento_tax_class
                        vals = self.prepare_vals_for_basic_details(
                            vals, category_ids, magento_website_ids, magento_tax_class)
                    if update_img or update_description or basic_details:
                        if update_img:
                            media_gallery = self.prepare_export_images_values(
                                conf_product, conf_product.product_type, False)
                            if media_gallery:
                                vals['product']['media_gallery_entries'] = media_gallery or []
                                vals['product']['extension_attributes']['website_ids'] = [
                                    int(magento_website_id) for magento_website_id in magento_website_ids.mapped('magento_website_id')]
                        api_url = '/all/V1/products/%s' % Php.quote_sku(conf_product.magento_sku)
                        self.update_product_request(instance, vals, api_url, conf_product,
                                                    common_log_id)

                    for child_product in conf_product.magento_product_ids:
                        self.update_simple_configurable_product(
                            instance, child_product, update_img, update_price, basic_details,
                            common_log_id, is_child_product=True, update_description=update_description)
        end = time.time()
        _logger.info("Updated total templates  %s  in %s seconds.", len(magento_templates), str(end - start))
        return True

    def update_simple_configurable_product(
            self, instance, simple_product_tmpl, update_img, update_price, basic_details,
            common_log_id, is_child_product=False, update_description=False):
        """
        Update simple or configurable product in magento
        :param instance: Magento Instance
        :param simple_product_tmpl: Magento product template record
        :param update_img: Update Image ?
        :param update_price: Update Price ?
        :param basic_details: Update basic details ?
        :param common_log_id: log book record
        :param is_child_product: is the child product of any configurable product
        :param update_description: Update description in magento ?
        :return:
        """
        conf_simple_product_product = self.get_simple_product(is_child_product, simple_product_tmpl)
        magento_website_ids, store_code_list, category_ids = self.get_categories_website_ids_store_views(
            instance, is_child_product, simple_product_tmpl)
        product_description = simple_product_tmpl.description
        custom_attributes = []
        sale_description_export = self.env[IR_CONFIG_PARAMETER].sudo().get_param(
            SET_MAGENTO_SALES_DESCRIPTION)
        if sale_description_export and update_description:
            custom_attributes = self.prepare_description_and_short_description_vals\
                (product_description,
                 custom_attributes,
                 simple_product_tmpl)
        vals = {
            "product": {
                "name": simple_product_tmpl.magento_product_name,
                "extension_attributes": {
                },
                "custom_attributes": []
            }
        }

        if category_ids and basic_details:
            category = []
            for cat in category_ids:
                val = {
                    "position": 0,
                    "category_id": cat.category_id
                }
                category.append(val)
            vals['product']['extension_attributes']['category_links'] = category or []
        if not is_child_product and simple_product_tmpl.magento_tax_class and basic_details:
            magento_tax_class = {
                "attribute_code": "tax_class_id", "value": simple_product_tmpl.magento_tax_class.magento_tax_class_id
            }
            vals['product']['custom_attributes'].append(magento_tax_class)

        if magento_website_ids:
            price_payload = []
            if basic_details:
                vals['product']['extension_attributes']['website_ids'] = [int(magento_website_id) for magento_website_id in magento_website_ids.mapped('magento_website_id')]
            for website in magento_website_ids:
                currency = website.magento_base_currency.id
                website_store_view = self.find_website_storecode_list(website, instance)
                price_payload = self.get_update_price_website_wise_dict(
                    instance, update_price, website_store_view, website,
                    currency, conf_simple_product_product, simple_product_tmpl, price_payload)
                self.update_product_website_vise_in_magento(
                    instance, sale_description_export, update_description, vals,
                    website_store_view, custom_attributes, simple_product_tmpl, common_log_id)
            self.update_product_price_in_magento(
                instance, update_price, conf_simple_product_product,
                simple_product_tmpl, price_payload, common_log_id)
            vals['product']['name'] = simple_product_tmpl.magento_product_name
            if update_img:
                media_gallery = self.prepare_export_images_values(
                    simple_product_tmpl, simple_product_tmpl.product_type, is_child_product)
                if media_gallery:
                    vals['product']['media_gallery_entries'] = media_gallery
                    vals['product']['extension_attributes']['website_ids'] = [
                        int(magento_website_id) for magento_website_id in magento_website_ids.mapped('magento_website_id')]
            api_url = '/all/V1/products/%s' % Php.quote_sku(simple_product_tmpl.magento_sku)
            self.update_product_request(instance, vals, api_url, simple_product_tmpl.magento_sku, common_log_id)
        else:
            common_log_id.write({
                'log_lines': [(0, 0, {
                    'message': "Not set any website in the product : %s" % simple_product_tmpl.magento_product_name,
                    'default_code': simple_product_tmpl.magento_sku
                })]
            })

    def update_product_website_vise_in_magento(
            self, instance, website_store_view, custom_attributes, simple_product_tmpl, common_log_id):
        if website_store_view:
            for store_view in website_store_view:
                # convert description and short description with store view lang.
                if custom_attributes:
                    vals = self.translate_description_and_short_description(
                        vals, store_view, custom_attributes, simple_product_tmpl)
                api_url = '/%s/V1/products/%s' % (
                    store_view.magento_storeview_code, Php.quote_sku(simple_product_tmpl.magento_sku))
                _logger.info("Store code %s", store_view.lang_id.code)
                self.update_product_request(
                    instance, vals, api_url, simple_product_tmpl.magento_sku, common_log_id)

    @staticmethod
    def prepare_description_and_short_description_vals(product_description, custom_attributes, simple_product_tmpl):
        description_sale = False
        if product_description:
            description = {
                "attribute_code": "description",
                "value": product_description
            }
            custom_attributes.append(description)

        if 'short_description' in simple_product_tmpl:
            description_sale = simple_product_tmpl.short_description
        if description_sale:
            short_description = {
                "attribute_code": "short_description",
                "value": description_sale
            }
            custom_attributes.append(short_description)
        return custom_attributes

    def find_website_storecode_list(self, website, instance):
        """
        Find the store code for the store
        :param website: Magento website
        :param instance: Magento Instance
        :return:
        """
        magento_store_view_obj = self.env[MAGENTO_STOREVIEW]
        magento_storeview = magento_store_view_obj.search([
            ('magento_website_id', '=', website.id), ('magento_instance_id', '=', instance.id)])
        return magento_storeview

    @staticmethod
    def update_product_request(instance, data, api_url, sku, common_log_id):
        """
        Update product request
        :param instance: Magento Instance
        :param data: body data
        :param api_url: API URL
        :param sku: Magento product SKU
        :param common_log_id: log book record
        :return:
        """
        try:
            req(instance, api_url, 'PUT', data)
        except Exception as error:
            common_log_id.write({
                'log_lines': [(0, 0, {
                    'message': "%s\nNot able to update product for SKU : %s" % (error, sku),
                    'default_code': sku
                })]
            })

    @staticmethod
    def update_product_base_price(instance, url, common_log_id, price_payload):
        """
        Update product basic price in magento
        :param instance: Magento Instance
        :param url: API URL
        :param common_log_id: Common log book record
        :param price_payload: price body
        :return:
        """
        try:
            req(instance, url, 'POST', price_payload)
        except Exception as error:
            common_log_id.write({
                'log_lines': [(0, 0, {
                    'message': "Not able to update product price. Error : %s" % error,
                })]
            })

    def find_website_and_store_code_list(self, product, instance):
        """
        Find the product's configured website and it's store view for the perticular instance
        :param product:
        :param instance:
        :return:
        """
        magento_store_view_obj = self.env[MAGENTO_STOREVIEW]
        store_code_list = []
        magento_website_ids = self.get_magento_website_ids(instance, product)
        if magento_website_ids:
            magento_storeview = magento_store_view_obj.search([('magento_website_id', 'in', magento_website_ids.ids)])
            store_code_list = magento_storeview.mapped('magento_storeview_code')
        return magento_website_ids, store_code_list

    @staticmethod
    def prepare_vals_for_basic_details(vals, category_ids, magento_website_ids, magento_tax_class=False):
        conf_product_category = []
        if category_ids:
            for cat in category_ids:
                val = {
                    "position": 0,
                    "category_id": cat.category_id
                }
                conf_product_category.append(val)
        vals['product']['extension_attributes']['category_links'] = conf_product_category or []

        if magento_tax_class:
            magento_tax_class = {
                "attribute_code": "tax_class_id",
                "value": magento_tax_class.magento_tax_class_id
            }
            vals['product']['custom_attributes'].append(magento_tax_class)
        return vals

    def get_categories_website_ids_store_views(self, instance, is_child_product, simple_product_tmpl):
        if is_child_product:
            conf_simple_product_tmpl = simple_product_tmpl.magento_tmpl_id
            magento_website_ids, store_code_list = self.find_website_and_store_code_list(
                conf_simple_product_tmpl, instance)
            category_ids = simple_product_tmpl.magento_tmpl_id.category_ids
        else:
            magento_website_ids, store_code_list = self.find_website_and_store_code_list(simple_product_tmpl, instance)
            category_ids = simple_product_tmpl.category_ids
        return magento_website_ids, store_code_list, category_ids

    @staticmethod
    def get_update_price_website_wise_dict(
            instance, update_price, website_store_view, website,
            currency, conf_simple_product_product, simple_product_tmpl, price_payload):
        if update_price and instance.catalog_price_scope == 'website' and website_store_view:
            for store_view in website_store_view:
                pricelist = website.pricelist_ids.filtered(lambda x: x.currency_id.id == currency)
                if pricelist:
                    pricelist = pricelist[0]
                    product_price = pricelist. \
                        get_product_price(conf_simple_product_product.odoo_product_id, pricelist.id, False)

                    price_vals = {"sku": simple_product_tmpl.magento_sku, "price": product_price,
                                  "store_id": store_view.magento_storeview_id}
                    price_payload.append(price_vals)
        return price_payload

    def update_product_website_vise_in_magento(
            self, instance, sale_description_export, update_description, vals,
            website_store_view, custom_attributes, simple_product_tmpl, common_log_id):
        if website_store_view:
            for store_view in website_store_view:
                # convert description and short description with store view lang.
                if custom_attributes and sale_description_export and update_description:
                    vals = self.translate_description_and_short_description(
                        vals, store_view, custom_attributes, simple_product_tmpl)
                api_url = '/%s/V1/products/%s' % (
                    store_view.magento_storeview_code, Php.quote_sku(simple_product_tmpl.magento_sku))
                _logger.info("Store code %s", store_view.lang_id.code)
                self.update_product_request(
                    instance, vals, api_url, simple_product_tmpl.magento_sku, common_log_id)

    def update_product_price_in_magento(
            self, instance, update_price, conf_simple_product_product,
            simple_product_tmpl, price_payload, common_log_id):
        if update_price:
            if instance.catalog_price_scope == 'global':
                _logger.info("Instance %s price scope is Global. ", instance.name)
                if instance.pricelist_id:
                    product_price = instance.pricelist_id. \
                        get_product_price(conf_simple_product_product.odoo_product_id,
                                          instance.pricelist_id.id, False)
                    _logger.info("%s : in product.product price is : %s" % (
                        conf_simple_product_product.odoo_product_id.name, product_price))
                    price_vals = {"sku": simple_product_tmpl.magento_sku, "price": product_price, "store_id": 0}
                    price_payload.append(price_vals)
                else:
                    common_log_id.write({
                        'log_lines': [(0, 0, {
                            'message': "Price scope is Global, "
                                       "But still pricelist not set for the Instance : %s" % instance.name
                        })]
                    })

            if price_payload:
                price_data = {"prices": price_payload}
                price_url = '/V1/products/base-prices'
                self.update_product_base_price(instance, price_url, common_log_id, price_data)
                _logger.info("Price Updated successfully.")

    def export_stock_in_magento(self, stock_item, instance, job, stock_data, source_code=False, msi=False):
        """
        Export stock in magento
        :param stock_item: Stock item
        :param instance: Magento Instance
        :param job: Common log record
        :param stock_data: dictionary of stock data
        :param source_code: if MSI then location source code
        :param msi: IS the MSI
        :return:
        """
        if stock_item:
            consumable_products = []
            magento_product_obj = self.env['magento.product.product']
            for product_id, stock in stock_item.items():
                exp_product = magento_product_obj.search([
                    ('odoo_product_id', '=', product_id), ('magento_instance_id', '=', instance.id)])
                if exp_product and stock >= 0.0:
                    if exp_product.odoo_product_id.type != 'product':
                        consumable_products.append(exp_product.odoo_product_id.default_code)
                    else:
                        if not msi:
                            product_stock_dict = {'sku': exp_product.magento_sku, 'qty': stock, 'is_in_stock': 1}
                            stock_data.append(product_stock_dict)
                        else:
                            stock_data.append({
                                'sku': exp_product.magento_sku,
                                'source_code': source_code,
                                'quantity': stock, 'status': 1})
                if consumable_products:
                    magento_product_obj.create_export_product_process_log(consumable_products, job)
            if stock_data and not msi:
                data = {'skuData': stock_data}
                api_url = "/V1/product/updatestock"
                magento_product_obj.call_export_product_stock_api(instance, api_url, data, job, 'PUT')
        return stock_data
