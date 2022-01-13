# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""
from odoo import models, fields, api, _
from datetime import datetime
MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
import json

class SaleOrderLine(models.Model):
    """
    Describes Sale order line
    """
    _inherit = 'sale.order.line'

    magento_sale_order_line_ref = fields.Char(
        string="Magento Sale Order Line Reference",
        help="Magento Sale Order Line Reference"
    )

    @api.model
    def magento_create_sale_order_line(self, magento_instance, order_response, magento_order, log_book_id, order_dict):
        """
        This method used for create a sale order line.
        :param magento_instance: Instance of Magento
        :param order_response: Order response received from Magento
        :param magento_order: Order Id
        :return: Sale order Lines
        """
        magento_product = self.env['magento.product.product']
        sale_lines_response = order_response.get('items')
        sale_order_lines = []
        skip_order = False
        store_id = order_response.get('store_id')
        store_view = magento_instance.magento_website_ids.store_view_ids.filtered(
            lambda x: x.magento_storeview_id == str(store_id)
        )
        tax_calculation_method = store_view and store_view.magento_website_id.tax_calculation_method
        for item in sale_lines_response:
            if item.get('product_type') in ['bundle', 'configurable']:
                continue
            product_id = item.get('product_id')
            product_sku = item.get('sku')
            order_item_id = item.get('item_id')
            # Start the code to get the custom option title and custom option value title from the Extension attribute.
            description = self.get_custom_option_title(order_item_id, order_response)
            # Over the code to get the custom option title and custom option value title from the Extension attribute.
            item_price = self.calculate_order_item_price(tax_calculation_method, item)
            magento_product = magento_product.search([
                '|', ('magento_product_id', '=', product_id),
                ('magento_sku', '=', product_sku),
                ('magento_instance_id', '=', magento_instance.id)
            ], limit=1)
            if not magento_product:
                product_obj = self.env['product.product'].search([('default_code', '=', product_sku)])
                if not product_obj:
                    continue
                elif len(product_obj) > 1:
                    skip_order = True
                    message = _("An order {} was skipped because the ordered product {} exists multiple "
                                "times in Odoo.".format(order_response['increment_id'], product_sku))
                    log_book_id.add_log_line(message, order_response['increment_id'],
                                             order_dict.id, "magento_order_data_queue_line_id")
                    return skip_order, []
                odoo_product = product_obj
            else:
                odoo_product = magento_product.odoo_product_id
            custom_options = ''
            if description:
                product_name = "Custom Option for Product" \
                               " : %s \n" % odoo_product.name
                custom_options = product_name + description
            sale_order_line = self.with_context(custom_options=custom_options).create_sale_order_line_vals(
                item, item_price, odoo_product, magento_order)
            order_line = self.create(sale_order_line)
            sale_order_lines.append(order_line)
            if description:
                product_name = "Custom Option for Product" \
                               " : %s \n" % odoo_product.name
                description = product_name + description
                order_line_obj = self.create_order_line_note(description, magento_order.id)
                sale_order_lines.append(order_line_obj)
        return skip_order, sale_order_lines

    @staticmethod
    def calculate_order_item_price(tax_calculation_method, item):
        """
        Calculate order item price based on tax calculation method configurations.
        :param tax_calculation_method: Tax calculation method (Including/ Excluding)
        :param item: order item received from Magento
        :return: order item price
        """
        if tax_calculation_method == 'including_tax':
            price = item.get('parent_item').get('price_incl_tax') if "parent_item" in item else item.get(
                'price_incl_tax')
        else:
            price = item.get('parent_item').get('price') if "parent_item" in item else item.get(
                'price')
        original_price = item.get('parent_item').get('original_price') if "parent_item" in item else item.get(
            'original_price')
        item_price = price if price != original_price else original_price
        return item_price

    def create_order_line_note(self, description, magento_order_id):
        """
        Add custom option value and it's title list as a sale order line note.
        :param description:
        :param magento_order_id:
        :return: sale order line object
        """
        order_line_obj = self.env['sale.order.line'].create({
            'name': description,
            'display_type': 'line_note',
            'product_id': False,
            'product_uom_qty': 0,
            'product_uom': False,
            'price_unit': 0,
            'order_id': magento_order_id,
            'tax_id': False,
        })
        return order_line_obj

    def get_custom_option_title(self, order_item_id, order_response):
        """
        :param product_id: Product ID
        :param order_response: Order REST API response
        :return: Merge all the custom option value and prepare the string per
         order item if the item having the custom option in sale order.
        Set that string in the sale order line.
        """
        description = ""
        extension_attributes = order_response.get("extension_attributes")
        ept_option_title = extension_attributes.get('ept_option_title')
        if ept_option_title:
            for custom_opt_itm in ept_option_title:
                custom_opt = json.loads(custom_opt_itm)
                if order_item_id == int(custom_opt.get('order_item_id')):
                    for option_data in custom_opt.get('option_data'):
                        description += option_data.get('label') + " : " + option_data.get('value') + "\n"
        return description

    def create_sale_order_line_vals(
            self, order_line_dict, price_unit, odoo_product=False, magento_order=False
    ):
        """
        Create Sale Order Line Values
        :param order_line_dict:  Magento sale order line object
        :param price_unit: price unit object
        :param odoo_product: odoo product object
        :param magento_order: Magento order object
        :return:
        """
        order_qty = float(order_line_dict.get('qty_ordered', 1.0))
        magento_sale_order_line_ref = order_line_dict.get('parent_item_id') or order_line_dict.get('item_id')
        uom_id = False
        if odoo_product and odoo_product.uom_id.id:
            uom_id = odoo_product and odoo_product.uom_id.id
        order_line_vals = {
            'order_id': magento_order.id,
            'product_id': odoo_product and odoo_product.id or False,
            'company_id': magento_order.company_id.id,
            'name': order_line_dict.get('name'),
            'description': odoo_product.name or (magento_order and magento_order.name),
            'product_uom': uom_id,
            'order_qty': order_qty,
            'price_unit': price_unit,
        }
        order_line_vals = self.create_sale_order_line_ept(order_line_vals)
        order_line_vals.update({
            'magento_sale_order_line_ref': magento_sale_order_line_ref
        })
        return order_line_vals
