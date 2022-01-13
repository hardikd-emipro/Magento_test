# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes fields and methods for create/ update sale order
"""
import json
import pytz
import time
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req, create_search_criteria
from ..python_library.php import Php
from dateutil import parser
utc = pytz.utc

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
SALE_ORDER_LINE = 'sale.order.line'


class SaleOrder(models.Model):
    """
    Describes fields and methods for create/ update sale order
    """
    _inherit = 'sale.order'

    def _get_magento_order_status(self):
        """
        Compute updated_in_magento of order from the pickings.
        """
        for order in self:
            if order.magento_instance_id:
                pickings = order.picking_ids.filtered(lambda x: x.state != "cancel")
                stock_moves = order.order_line.move_ids.filtered(lambda x: not x.picking_id and x.state == 'done')
                if pickings:
                    outgoing_picking = pickings.filtered(
                        lambda x: x.location_dest_id.usage == "customer")
                    if all(outgoing_picking.mapped("is_exported_to_magento")):
                        order.updated_in_magento = True
                        continue
                if stock_moves:
                    order.updated_in_magento = True
                    continue
                order.updated_in_magento = False
                continue
            order.updated_in_magento = False

    def _search_magento_order_ids(self, operator, value):
        query = """select so.id from stock_picking sp
                    inner join sale_order so on so.procurement_group_id=sp.group_id                   
                    inner join stock_location on stock_location.id=sp.location_dest_id and stock_location.usage='customer'
                    where sp.is_exported_to_magento %s true and sp.state != 'cancel'
                    """ % operator
        if operator == '=':
            query += """union all
                    select so.id from sale_order as so
                    inner join sale_order_line as sl on sl.order_id = so.id
                    inner join stock_move as sm on sm.sale_line_id = sl.id
                    where sm.picking_id is NULL and sm.state = 'done' and so.magento_instance_id notnull"""
        self._cr.execute(query)
        results = self._cr.fetchall()
        order_ids = []
        for result_tuple in results:
            order_ids.append(result_tuple[0])
        order_ids = list(set(order_ids))
        return [('id', 'in', order_ids)]

    magento_instance_id = fields.Many2one(
        'magento.instance',
        string="Magento Instance",
        help="This field relocates Magento Instance"
    )
    magento_order_id = fields.Char(string="Magento order Ids", help="Magento Order Id")
    magento_website_id = fields.Many2one(
        "magento.website",
        string="Magento Website",
        help="Magento Website"
    )
    magento_order_reference = fields.Char(
        string="Magento Orders Reference",
        help="Magento Order Reference"
    )
    store_id = fields.Many2one(
        'magento.storeview',
        string="Magento Storeview",
        help="Magento_store_view"
    )
    is_exported_to_magento_shipment_status = fields.Boolean(
        string="Is Order exported to Shipment Status",
        help="Is exported to Shipment Status"
    )
    magento_payment_method_id = fields.Many2one(
        'magento.payment.method',
        string="Magento Payment Method",
        help="Magento Payment Method"
    )
    magento_shipping_method_id = fields.Many2one(
        'magento.delivery.carrier',
        string="Magento Shipping Method",
        help="Magento Shipping Method"
    )
    order_transaction_id = fields.Char(
        string="Magento Orders Transaction ID",
        help="Magento Orders Transaction ID"
    )
    updated_in_magento = fields.Boolean(
        string="Order fulfilled in magento", compute="_get_magento_order_status", search="_search_magento_order_ids",
        copy=False
    )

    _sql_constraints = [('_magento_sale_order_unique_constraint',
                         'unique(magento_order_id,magento_instance_id,magento_order_reference)',
                         "Magento order must be unique")]

    def _cancel_order_exportable(self):
        """
        this method will check order is cancel in odoo or not, and invoice is exported or not.
        And shipment done in magento or not
        :return:
        """
        if (self.invoice_ids and True in self.invoice_ids.mapped('is_exported_to_magento')) or \
                (self.picking_ids and self.picking_ids.filtered(
                    lambda x: x.state == 'done' and x.is_exported_to_magento).ids):
            self.is_cancel_order_exportable = True
        else:
            self.is_cancel_order_exportable = False

    is_cancel_order_exportable = fields.Boolean(string="Is Invoice exportable", compute='_cancel_order_exportable',
                                                store=False)

    @api.model
    def check_price_list_for_order_exit(
            self, order_response, skip_order, log_book_id, order_data_queue_line_id
    ):
        """
        This method is used to check price list is exist or not in odoo.
        When import order from Magento to Odoo.
        :param order_response: Order Response received from Magento
        :param skip_order: True if any error else False
        :param log_book_id: Common Log book object
        :param order_data_queue_line_id: order data queue line id
        :return: Product price list object or skip order
        """
        currency_obj = self.env['res.currency']
        pricelist_obj = self.env['product.pricelist']
        order_currency = order_response.get('order_currency_code')
        order_ref = order_response.get('increment_id')
        currency_id = currency_obj.with_context(active_test=False). \
            search([('name', '=', order_currency)], limit=1)
        if not currency_id.active:
            currency_id.write({'active': True})
        price_list = pricelist_obj.search([('currency_id', '=', currency_id.id)])
        if price_list:
            price_list = price_list[0]
        elif not price_list or price_list.currency_id != currency_id:
            skip_order = True
            message = _("Order {} was skipped, as no pricelist was found for currency {}. "
                        "We recommend synchronizing metadata.Please go to Magento2 connector -> Configuration -> "
                        "Instance -> select Instance -> Click on 'Syncronize Metadata'".format(order_ref,
                                                                                               currency_id.name))
            log_book_id.add_log_line(message, order_ref,
                                     order_data_queue_line_id,
                                     "magento_order_data_queue_line_id")
        return price_list, skip_order

    def get_magento_shipping_method(
            self, magento_instance, order_response, log_book_id, order_data_queue_line_id
    ):
        """
        This method is used to get shipping method.
        if shipping method not found it will create(base on carrier_code) new shipping method.
        :param magento_instance: Instance of Magento
        :param order_response: Order Response received from Magento
        :param log_book_id: Common Log book object
        :param order_data_queue_line_id: Order data queue line object
        :return:
        """
        magento_delivery_carrier_obj = self.env['magento.delivery.carrier']
        delivery_carrier_obj = self.env["delivery.carrier"]
        order_reference = order_response.get('increment_id')
        magento_carrier = skip_order = False
        shipping = order_response.get('extension_attributes').get('shipping_assignments')
        shipping_method = shipping[0].get('shipping').get('method') or False
        message = ""
        if shipping_method:
            magento_carrier = magento_delivery_carrier_obj.search([
                ('carrier_code', '=', shipping_method), ('magento_instance_id', '=', magento_instance.id)
            ], limit=1)
            if not magento_carrier:
                magento_instance.import_delivery_method()
                magento_carrier = magento_delivery_carrier_obj.search([
                    ('carrier_code', '=', shipping_method), ('magento_instance_id', '=', magento_instance.id)
                ], limit=1)
                if not magento_carrier:
                    skip_order = True
                    message = _("Order {} was skipped because when importing order the delivery "
                                "method {} could not find in the Magento.".format(order_reference, shipping_method))
        if skip_order:
            log_book_id.add_log_line(message, order_reference,
                                     order_data_queue_line_id,
                                     "magento_order_data_queue_line_id")
            return skip_order
        if magento_carrier:
            delivery_carrier = delivery_carrier_obj.search([('magento_carrier', '=', magento_carrier.id)], limit=1)
            if not delivery_carrier:
                default_product = self.env.ref('odoo_magento2_ept.product_product_shipping')
                product = magento_instance.shipping_product_id or default_product
                delivery_carrier_obj.create({
                    'name': magento_carrier.carrier_label, 'product_id': product.id,
                    'magento_carrier': magento_carrier.id
                })
        return skip_order

    def cancel_order_from_magento(self):
        """
        this method will call while sale order cancel from webhook
        :return:
        """
        log_msg = ""
        result = False
        try:
            result = super(SaleOrder, self).action_cancel()
        except Exception as error:
            log_msg = error
        if not result:
            message = "Order {} could not be cancelled in Odoo via webhook. \n".format(self.magento_order_reference) + str(log_msg)
            model_id = self.env['common.log.lines.ept'].sudo().get_model_id('sale.order')
            self.env['common.log.book.ept'].sudo().create({
                'type': 'import',
                'module': 'magento_ept',
                'model_id': model_id,
                'res_id': self.id,
                'magento_instance_id': self.magento_instance_id.id,
                'log_lines': [(0, 0, {
                    'message': message,
                    'order_ref': self.name,
                })]
            })
        return True

    def cancel_order_in_magento(self):
        """
        This method use for cancel order in magento.
        @return: result
        """
        result = super(SaleOrder, self).action_cancel()
        magento_order_id = self.magento_order_id
        if magento_order_id:
            magento_instance = self.magento_instance_id
            try:
                api_url = '/V1/orders/%s/cancel' % magento_order_id
                result = req(magento_instance, api_url, 'POST')
            except Exception:
                raise UserError("Error while requesting cancel order")
        return result

    def _prepare_invoice(self):
        """
        This method is used for set necessary value(is_magento_invoice,
        is_exported_to_magento,magento_instance_id) in invoice.
        :return:
        """
        invoice_vals = super(SaleOrder, self)._prepare_invoice()
        if self.magento_payment_method_id:
            invoice_vals['magento_payment_method_id'] = self.magento_payment_method_id.id
        if self.magento_instance_id:
            invoice_vals.update({
                'magento_instance_id': self.magento_instance_id.id,
                'is_magento_invoice': True,
                'is_exported_to_magento': False
            })
        return invoice_vals

    def mgento_order_convert_date(self, order_response):
        """ This method is used to convert the order date in UTC and formate("%Y-%m-%d %H:%M:%S").
            :param order_response: Order response
        """
        if order_response.get("created_at", False):
            order_date = order_response.get("created_at", False)
            date_order = parser.parse(order_date).astimezone(utc).strftime("%Y-%m-%d %H:%M:%S")
        else:
            date_order = time.strftime("%Y-%m-%d %H:%M:%S")
            date_order = str(date_order)

        return date_order

    def create_magento_sales_order_ept(
            self, magento_instance_id, orders, magento_product_sku, magento_invoice_customer,
            magento_delivery_customer, order_count, order_total_queue, log_book_id
    ):
        """
        This method create orders into Odoo.
        :param magento_instance_id: instance of Magento
        :param orders: orders dictionary received from Magento API
        :param magento_product_sku: Dictionary of Magento products
        :param magento_invoice_customer: Dictionary of Magento invoice customer
        :param magento_delivery_customer: Dictionary of Magento delivery customer
        :param order_count: Order count variable for commit after 10 orders
        :param order_total_queue: Total number of order in a queue
        :param log_book_id: common log book object
        :return: Inserted orders dictionary
        """
        country_dict = state_dict = {}
        for order_dict in orders:
            order_response = json.loads(order_dict.order_data)
            order_ref = order_response['increment_id']
            if not order_ref:
                continue

            existing_order = self.search([
                ('magento_instance_id', '=', magento_instance_id.id), ('magento_order_reference', '=', order_ref)
            ])
            if existing_order:
                order_dict.write({'state': 'done', 'processed_at': datetime.now(), 'sale_order_id': existing_order.id})
                order_total_queue -= 1
                continue
            if magento_instance_id:
                magento_order, skip_order = self.get_magento_order_details_and_create_sale_order(
                    magento_instance_id, order_dict, order_response, log_book_id, magento_product_sku,
                    magento_invoice_customer, magento_delivery_customer, state_dict, country_dict)
                if skip_order:
                    # here we set queue line as fail state,
                    # because warehouse is not set in website
                    order_dict.write({'state': 'failed', 'processed_at': datetime.now()})
                    magento_order and magento_order.sudo().unlink()
                    continue
                self.process_sale_order_workflow_based_on_status(order_response, magento_order, log_book_id)
                order_count += 1
                order_total_queue -= 1
                order_dict, order_count = self.check_more_order_queue_exists(order_count, order_total_queue, order_dict)
                order_dict.write({
                    'state': 'done', 'processed_at': datetime.now(),
                    'magento_order_id': magento_order.magento_order_reference,
                    'sale_order_id': magento_order.id # save sale_order_id for new order.
                })
                self._cr.commit()
        return magento_product_sku, magento_invoice_customer, magento_delivery_customer, order_count, order_total_queue

    def validate_magento_order(
            self, order_response, magento_instance_id, order_ref, log_book_id, order_dict, skip_order):
        date_order = self.mgento_order_convert_date(order_response)
        if str(magento_instance_id.import_order_after_date) > date_order:
            message = _("There is a configuration mismatch in the import of order {}. The order receive date is {}. "
                        "Please check the date set in the configuration in Magento2 Connector -> Configuration "
                        "-> Setting -> Select Instance -> 'Import Order After Date'.".format(order_ref, date_order))
            skip_order = True
        elif 'is_invoice' not in order_response.get('extension_attributes'):
            message = _("Order {} was skipped. Please ensure that the Emipro APIchange extension is installed in "
                        "your Magento store. Please refer to the use guide for instructions on how to download "
                        "and install the Emipro APIchange extension.".format(order_ref))
            skip_order = True
        if skip_order:
            log_book_id.add_log_line(message, order_ref,
                                     order_dict.id,
                                     "magento_order_data_queue_line_id")
        return skip_order

    def get_magento_order_details_and_create_sale_order(
            self, magento_instance_id, order_dict, order_response, log_book_id, magento_product_sku,
            magento_invoice_customer, magento_delivery_customer, state_dict, country_dict):
        """
        Create/ update Magento payment options, financial status, products,
         shipping details, customers, pricelists.
         Prepare Magento order values.
        :param magento_instance_id: Magento instance id
        :param order_dict: magento order data queue line object
        :param order_response: response received from Magento
        :param log_book_id: common log book object
        :param magento_product_sku: Magento product SKU
        :param magento_invoice_customer: dictionary for invoice customer
        :param magento_delivery_customer: dictionary for delivery customer
        :param state_dict: dictionary for state
        :param country_dict: dictionary for country
        :return: orcer values dictionary, skip_order
        """
        magento_order = False
        skip_order = False
        order_ref = order_response['increment_id']
        skip_order = self.validate_magento_order(
            order_response, magento_instance_id, order_ref, log_book_id, order_dict, skip_order)
        if not skip_order:
            skip_order = self.check_payment_shipping_and_products_of_order(
                order_dict.id, order_response, magento_instance_id, log_book_id, magento_product_sku, skip_order)
        price_list = False
        if not skip_order:
            price_list, skip_order = self.check_price_list_for_order_exit(
                order_response, skip_order, log_book_id, order_dict.id)
        if not skip_order:
            skip_order, partner_dict = self.env['res.partner'].create_or_update_magento_customer(
                magento_instance_id, order_response, magento_invoice_customer,
                magento_delivery_customer, state_dict, country_dict, skip_order, log_book_id, order_dict.id)
        if not skip_order:
            # Prepare Sale Order Values
            order_values, skip_order = self.create_magento_sales_order_vals(
                partner_dict, order_response, magento_instance_id, price_list, log_book_id, order_dict.id)
        if not skip_order:
            magento_order = self.create(order_values)
            skip_order = self.create_magento_sale_order_line(
                order_response, magento_instance_id, magento_order, log_book_id, order_dict)
        return magento_order, skip_order

    def process_sale_order_workflow_based_on_status(self, order_response, magento_order, log_book_id):
        """
        Call sale order workflow based on magento order status
        :param order_response: order response received from Magento
        :param magento_order: sale order object
        :param log_book_id: common log book object
        """
        auto_work_flow_obj = self.env['sale.workflow.process.ept']
        if order_response.get('status') == 'complete' or \
                (order_response.get('status') == 'processing' and
                 order_response.get('extension_attributes').get('is_shipment')):
            magento_order.auto_workflow_process_id.with_context(
                log_book_id=log_book_id.id).shipped_order_workflow_ept(magento_order)
        else:
            auto_work_flow_obj.with_context(
                log_book_id=log_book_id.id).auto_workflow_process_ept(
                magento_order.auto_workflow_process_id.id, [magento_order.id])
        if order_response.get('status') == 'complete' or \
                (order_response.get('status') == 'processing' and
                 order_response.get('extension_attributes').get('is_invoice')) and \
                magento_order.invoice_ids:
            # Here the magento order is complete state or
            # processing state with invoice so invoice is already created
            # So Make the Export invoice as true to hide Export invoice button from invoice.
            magento_order.invoice_ids.write({'is_exported_to_magento': True})

    def check_more_order_queue_exists(self, order_count, order_total_queue, order_dict):
        """
        Check more product queue items exists
        :param order_count: incremental count of order queue line
        :param order_total_queue: total order queue line
        :param order_dict: magento order data queue line object
        :return: order_count, order_dict
        """
        if order_count > 10 or (0 < order_count <= 10 and order_total_queue == 0):
            self._cr.commit()
            order_count = 1
            order_dict.magento_order_data_queue_id.is_process_queue = True
        return order_dict, order_count

    def check_payment_shipping_and_products_of_order(
            self, order_data_queue_line_id, order_response, magento_instance_id,
            log_book_id, magento_product_sku, skip_order):
        """
        Check Payment method, payment term, shipping method and create/ update product
        :param order_data_queue_line_id: order data queue line id
        :param order_response: order dictionary received from Magento API
        :param magento_instance_id: Instance of Magento
        :param log_book_id: common log book object or False
        :param magento_product_sku: Magento product dictionary
        :param skip_order: True/False
        :return: skip order and job
        """
        magento_product = self.env['magento.product.product']
        order_ref = order_response['increment_id']
        payment_method = order_response['payment'].get('method')
        skip_order, message = self.check_magento_payment_method_configuration(
            magento_instance_id, order_response, payment_method, skip_order)
        if skip_order:
            log_book_id.create_order_log_lines(message, order_ref, order_data_queue_line_id)
            return skip_order
        skip_order = self.get_magento_shipping_method(
            magento_instance_id, order_response, log_book_id, order_data_queue_line_id
        )
        if skip_order:
            return skip_order
        order_lines = order_response['items']
        skip_order = magento_product.create_or_update_product_in_magento(
            order_lines, magento_instance_id, magento_product_sku, order_ref, order_data_queue_line_id, log_book_id
        )
        return skip_order

    @staticmethod
    def get_magento_financial_status(order_status, is_invoice, is_shipment):
        """
        Get Financial Status Dictionary.
        :param order_status: Order status received from Magento.
        :param is_invoice: Order is invoiced.
        :param is_shipment: Order is Shipped.
        :return: Financial Status dictionary
        """
        financial_status_code = financial_status_name = ''
        if order_status == "pending":
            financial_status_code = 'not_paid'
            financial_status_name = 'Pending Orders'
        elif order_status == "processing" and is_invoice and not is_shipment:
            financial_status_code = 'processing_paid'
            financial_status_name = 'Processing orders with Invoice'
        elif order_status == "processing" and is_shipment and not is_invoice:
            financial_status_code = 'processing_unpaid'
            financial_status_name = 'Processing orders with Shipping'
        elif order_status == "complete":
            financial_status_code = 'paid'
            financial_status_name = 'Completed Orders'
        return financial_status_code, financial_status_name

    def search_order_financial_status(self, order_response, magento_instance, payment_option):
        """
        Search order Financial status.
        :param order_response: Response received from Magento.
        :param magento_instance: Magento Instance.
        :param payment_option: Magento Order Payment Method
        :return: Financial Status object, Financial Status Name
        """
        is_invoice = order_response.get('extension_attributes').get('is_invoice')
        is_shipment = order_response.get('extension_attributes').get('is_shipment')
        financial_status_code, financial_status_name = self.get_magento_financial_status(
            order_response.get('status'), is_invoice, is_shipment)
        workflow_config = self.env['magento.financial.status.ept'].search(
            [('magento_instance_id', '=', magento_instance.id),
             ('payment_method_id', '=', payment_option.id),
             ('financial_status', '=', financial_status_code)])
        return workflow_config, financial_status_name

    @staticmethod
    def check_order_is_processing_and_shipped_and_invoiced(order_response):
        """
        Check order is in processing state and invoice and shipment is done or not.
        :param order_response: order response received from Magento
        :return: skip_order, message
        """
        is_invoice = order_response.get('extension_attributes').get('is_invoice')
        is_shipment = order_response.get('extension_attributes').get('is_shipment')
        if not is_invoice and not is_shipment and order_response.get('status') == 'processing':
            message = _("Order {} was skipped, Order status is processing, but the order is neither " \
                      "invoice nor shipped.".format(order_response.get('increment_id')))
        elif order_response.get('status') not in ['pending','processing','complete']:
            message = "Order {} was skipped due to financial status not found of order status {}.\n " \
                      "Currently the Magento2 Odoo Connector supports magento default order status" \
                      " such as 'Pending', 'Processing' and 'Completed'.\n" \
                      "The connector does not support the magento2 custom order status {}. .".format(
                order_response.get('increment_id'), order_response.get('status'), order_response.get('status'))
        else:
            message = "Order {} was skipped because the order is partially invoiced and partially shipped.\n " \
                      "Magento order status Processing: Processing means that orders have either been" \
                      " invoiced or shipped, but not both.\n In this, we are receiving " \
                      "order in which it is partially invoiced and partially shipped.".format(
                order_response.get('increment_id'))
        return True, message

    def check_magento_payment_method_configuration(
            self, magento_instance, order_response, payment_method, skip_order):
        """
        Check Configuration All Configuration of Payment Methods
        :param magento_instance: Magento Instance Object
        :param order_response: Order Response received from Magento.
        :param payment_method: Order Payment Method.
        :param skip_order: True/ False
        :return: skip_order (boolean)
        """
        payment_option = magento_instance.payment_method_ids.filtered(
            lambda x: x.payment_method_code == payment_method)
        order_ref = order_response['increment_id']
        message = ''
        import_rule = payment_option.import_rule
        max_days = payment_option.days_before_cancel
        amount_paid = order_response.get('payment').get('amount_paid', False)
        payment_name = payment_option and payment_option.payment_method_name or ''
        workflow_config, financial_status_name = self.search_order_financial_status(
            order_response, magento_instance, payment_option)
        if not workflow_config and financial_status_name == "":
            skip_order, message = self.check_order_is_processing_and_shipped_and_invoiced(order_response)
        elif not workflow_config:
            skip_order = True
            message = _("- No automatic order process workflow configuration was found for this order {}.\n"
                        "- Based on the combination of Payment Gateway (such as Bank Transfer, etc.)"
                        " and Financial Status (such as Pending Orders, Completed Orders, etc.) "
                        "the system attempts to determine the workflow. \n - In this order, "
                        "Payment Gateway is '{}' and Financial Status is {} Orders. \n"
                        "- Automatic order process workflow can be configured under the"
                        " Magento -> Configuration > Financial Status.".format(
                order_response.get('increment_id'), payment_name, financial_status_name))
        elif not workflow_config.auto_workflow_id and financial_status_name != "":
            skip_order = True
            message = _("Order {} was skipped because the auto workflow configuration was not found"
                        " for payment method - '{}' and financial status - {} Orders.".format(
                order_ref, payment_name, financial_status_name))
        elif not workflow_config.payment_term_id and financial_status_name != "":
            skip_order = True
            message = _("Order {} was skipped because Payment Term was not found "
                        "for payment method - {} and financial status - {} Orders.".format(
                order_ref, payment_method, financial_status_name))
        elif max_days:
            order_date = datetime.strptime(order_response.get('created_at'), '%Y-%m-%d %H:%M:%S')
            if order_date + timedelta(days=max_days) < datetime.now():
                skip_order = True
                message = _("Order '{}' with payment method '{}' was skipped because it is {} days before. "
                            "You can change the configuration from Magento2 Connector -> Configuration -> "
                            "Payment Methods -> Select the payment method {} -> Import Past Orders of X days.".format(
                    order_ref, payment_name, max_days, payment_name))
        elif import_rule == 'never':
            skip_order = True
            message = _("Order {} was skipped because payment method {} import rule is set 'never'.\n "
                        "Please check configuration in the Magento2 connector ->  Configuration -> Payment Methods"
                        " -> Select the payment method {} -> Import Rule.".format(order_ref, payment_method,
                                                                                  payment_method))
        elif not amount_paid and import_rule == 'paid':
            skip_order = True
            message = _("Order {} was skipped because payment method {} import rule is set 'Paid'.\n "
                        "But the order payment status is unpaid. Please check configuration "
                        "in the Magento2 connector ->  Configuration -> Payment Methods"
                        " -> Select the payment method {} -> Import Rule.".format(order_ref, payment_method,
                                                                                  payment_method))
        return skip_order, message

    def create_magento_sales_order_vals(self, partner_dict, order_response,
                                        magento_instance_id, price_list, log_book_id, order_data_queue_line_id):
        """
        Prepare dictionary for Magento sale order
        :param partner_dict: partner invoice address and delivery address dictionary
        :param order_response: order dictionary received from Magento API
        :param magento_instance_id: instance of Magento
        :param price_list: Product price list object
        :return: Dictionary of sale order values
        """
        skip_order = False
        shipping = order_response.get('extension_attributes').get('shipping_assignments')
        shipping_method = shipping[0].get('shipping').get('method') or False
        shipping_carrier = magento_instance_id.shipping_method_ids.filtered(lambda x: x.carrier_code == shipping_method)
        delivery_method = shipping_carrier.delivery_carrier_ids.filtered(
            lambda x: x.magento_carrier_code == shipping_method
        )
        payment_method = order_response['payment'].get('method')
        payment_option = magento_instance_id.payment_method_ids.filtered(
            lambda x: x.payment_method_code == payment_method)
        store_id = order_response.get('store_id')
        store_view = magento_instance_id.magento_website_ids.store_view_ids.filtered(
            lambda x: x.magento_storeview_id == str(store_id)
        )
        if not store_view.magento_website_id.warehouse_id.id:
            skip_order = True
            message = _("Order {} was skipped because warehouse is not set for the website {}. "
                        "Please configure it from Magento2 Connector -> Configuration -> Setting -> "
                        "Magento websites.".format(order_response['increment_id'], store_view.magento_website_id.name))
            log_book_id.add_log_line(message, order_response['increment_id'],
                                               order_data_queue_line_id, "magento_order_data_queue_line_id")
            return {}, skip_order
        order_values = self.prepare_order_vals_dict(
            magento_instance_id, partner_dict, order_response, price_list,
            payment_option, store_view, delivery_method
        )
        order_values = self.create_sales_order_vals_ept(order_values)
        order_values = self.update_order_vals_dict(
            order_values, magento_instance_id, store_view, order_response, shipping_carrier, payment_option
        )
        return order_values, skip_order

    def prepare_order_vals_dict(
            self, magento_instance, partner_dict, order_response, price_list,
            payment_option, store_view, delivery_method
    ):
        """
        Prepare dictionary of order values
        :param magento_instance: Magento Instance object
        :param partner_dict: Dictionary of partners
        :param order_response: Response received from Magento.
        :param price_list: Product price list object
        :param payment_option: Magento payment method object
        :param store_view: Magento store view object
        :param delivery_method: Delivery carrier object
        :return: Dictionary of order values
        """
        financial_status, financial_status_name = self.search_order_financial_status(
            order_response, magento_instance, payment_option)
        workflow_process_id = False
        payment_term_id = False
        if financial_status and financial_status.auto_workflow_id:
            workflow_process_id = financial_status.auto_workflow_id
            payment_term_id = financial_status.payment_term_id
        ordervals = {
            'company_id': magento_instance.company_id.id,
            'partner_id': partner_dict.get('partner'),
            'partner_invoice_id': partner_dict.get('invoice_partner'),
            'partner_shipping_id': partner_dict.get('shipping_partner'),
            'warehouse_id': store_view.magento_website_id.warehouse_id.id,
            'picking_policy': workflow_process_id and workflow_process_id.picking_policy or False,
            'date_order': order_response.get('created_at', False),
            'pricelist_id': price_list and price_list.id or False,
            'team_id': store_view and store_view.team_id and store_view.team_id.id or False,
            'payment_term_id': payment_term_id and payment_term_id.id or False,
            'carrier_id': delivery_method and delivery_method.id or False,
            'client_order_ref': order_response.get('increment_id')
        }
        return ordervals

    def update_order_vals_dict(
            self, ordervals, magento_instance, store_view, order_response, shipping_carrier, payment_option
    ):
        """
        Update dictionary of order values
        :param ordervals: Dictionary of order values
        :param magento_instance: Magento Instance object
        :param store_view: Magento Store view object
        :param order_response: Response received from Magento.
        :param shipping_carrier: Magento delivery carrier object
        :param payment_option: Magento payment method object
        :return:
        """
        order_ref = order_response.get('increment_id')
        financial_status, financial_status_name = self.search_order_financial_status(
            order_response, magento_instance, payment_option)
        workflow_process_id = False
        if financial_status.auto_workflow_id:
            workflow_process_id = financial_status.auto_workflow_id.id
        magento_payment_method_id = False
        if payment_option and payment_option.id:
            magento_payment_method_id = payment_option.id
        payment_additional_info = order_response.get('extension_attributes').get('payment_additional_info') if \
            order_response.get('extension_attributes').get('payment_additional_info') else False
        transaction_id = False
        if payment_additional_info:
            for payment_info in payment_additional_info:
                if payment_info.get('key') == 'transaction_id':
                    transaction_id = payment_info.get('value')
        storeview_id = magento_website = False
        if store_view:
            storeview_id = store_view.id
            magento_website = store_view.magento_website_id.id
        ordervals.update({
            'magento_instance_id': magento_instance.id,
            'magento_website_id': magento_website,
            'store_id': storeview_id,
            'auto_workflow_process_id': workflow_process_id,
            'magento_payment_method_id': magento_payment_method_id,
            'magento_shipping_method_id': shipping_carrier.id,
            'is_exported_to_magento_shipment_status': False,
            'magento_order_id': order_response.get('items')[0].get('order_id'),
            'magento_order_reference': order_ref,
            'order_transaction_id': transaction_id
        })
        if store_view and not store_view.is_use_odoo_order_sequence:
            name = "%s%s" % (store_view and store_view.sale_prefix or '', order_ref)
            ordervals.update({"name": name})
        return ordervals

    def create_magento_sale_order_line(self, order_response, instance, magento_order, log_book_id, order_dict):
        """
        Create shipping order line and order discount line and sale order line.
        :param order_response: order dictionary received from Magento API
        :param instance: instance of Magento
        :param magento_order: sale order object
        """
        skip_order, sale_order_lines = self.env[SALE_ORDER_LINE].\
            magento_create_sale_order_line(instance, order_response, magento_order, log_book_id, order_dict)
        if not skip_order:
            skip_order = self.create_shipping_order_line(order_response, magento_order, log_book_id, order_dict)
            if not skip_order:
                skip_order = self.create_discount_order_line(order_response, magento_order, log_book_id, order_dict)
        return skip_order

    def create_shipping_order_line(self, order_response, magento_order, log_book_id, order_dict):
        """
        Create Shipping order line.
        :param order_response: Response received from Magento.
        :param magento_order: Sale order object
        :return:
        """
        sale_order_line_obj = self.env[SALE_ORDER_LINE]
        shipping_amount_incl = float(order_response.get('shipping_incl_tax', 0.0))
        shipping_amount_excl = float(order_response.get('shipping_amount', 0.0))
        if shipping_amount_incl or shipping_amount_excl:
            account_tax_obj = self.env['account.tax']
            default_product = self.env.ref('odoo_magento2_ept.product_product_shipping')
            shipping_product = magento_order.magento_instance_id.shipping_product_id or default_product
            tax_id = False
            extension_attributes = order_response.get('extension_attributes')
            is_tax_included, tax_percent = self.check_shipping_has_tax_included_and_percent(extension_attributes)
            price = shipping_amount_incl if is_tax_included else shipping_amount_excl
            shipping_line = sale_order_line_obj.create_sale_order_line_vals(
                order_response, price, shipping_product, magento_order
            )
            shipping_line.update({'is_delivery': True})
            if tax_percent:
                tax_id = account_tax_obj.get_tax_from_rate(rate=float(tax_percent), is_tax_included = is_tax_included)
                if tax_id and not tax_id.active:
                    skip_order = True
                    message = _("Order {} was skipped because the shipping tax {}% was not found. "
                                "The connector is unable to create new tax {}%, kindly check the tax {}% has been "
                                "archived?".format(order_response['increment_id'], tax_id.name, tax_id.name,
                                                   tax_id.name))
                    log_book_id.add_log_line(message, order_response['increment_id'],
                                             order_dict.id, "magento_order_data_queue_line_id")
                    return skip_order
                if not tax_id:
                    name = '%s %% ' % (tax_percent)
                    tax_id = account_tax_obj.sudo().create({
                        'name': name,
                        'description': name,
                        'amount_type': 'percent',
                        'price_include': is_tax_included,
                        'amount': float(tax_percent),
                        'type_tax_use': 'sale',
                    })
            if tax_id:
                shipping_line.update({
                    'tax_id': [(6, 0, tax_id.ids)]
                })
            sale_order_line_obj.create(shipping_line)

    def create_discount_order_line(self, order_response, magento_order, log_book_id, order_dict):
        """
        Create discount order line.
        :param order_response: Response received from Magento.
        :param magento_order: Sale order object
        :return:
        """
        sale_order_line_obj = self.env[SALE_ORDER_LINE]
        account_tax_obj = self.env['account.tax']
        discount_amount = float(order_response.get('discount_amount') or 0.0) or False
        if discount_amount:
            tax_id = False
            default_product = self.env.ref('odoo_magento2_ept.magento_product_product_discount')
            discount_product = magento_order.magento_instance_id.discount_product_id or default_product
            discount_line = sale_order_line_obj.create_sale_order_line_vals(
                order_response, discount_amount, discount_product, magento_order
            )
            is_tax_included, tax_percent = self.check_discount_has_tax_included_and_percent(order_response)
            if tax_percent:
                tax_id = account_tax_obj.get_tax_from_rate(rate=float(tax_percent), is_tax_included = is_tax_included)
                if tax_id and not tax_id.active:
                    skip_order = True
                    message = _("Order {} was skipped because the discount tax {}% was not found. "
                                "The connector is unable to create new tax {}%, kindly check the tax {}% has been "
                                "archived?".format(order_response['increment_id'], tax_id.name, tax_id.name,
                                                   tax_id.name))
                    log_book_id.add_log_line(message, order_response['increment_id'],
                                             order_dict.id, "magento_order_data_queue_line_id")
                    return skip_order
                if not tax_id:
                    name = '%s %% ' % (tax_percent)
                    tax_id = account_tax_obj.sudo().create({
                        'name': name,
                        'description': name,
                        'amount_type': 'percent',
                        'price_include': is_tax_included,
                        'amount': float(tax_percent),
                        'type_tax_use': 'sale',
                    })
            if tax_id:
                discount_line.update({
                    'tax_id': [(6, 0, tax_id.ids)]
                })
            sale_order_line_obj.create(discount_line)

    @staticmethod
    def check_discount_has_tax_included_and_percent(order_response):
        """
        Check order tax applied is including/ excluding and tax percent.
        :param order_response: response received from order.
        :return: True/False
        """
        is_tax_included = True
        tax_percent = False
        extension_attributes = order_response.get('extension_attributes')
        if extension_attributes and "apply_discount_on_prices" in extension_attributes:
            apply_discount_on_prices = extension_attributes.get('apply_discount_on_prices')
            if apply_discount_on_prices == 'excluding_tax':
                is_tax_included = False
        for order_items in order_response.get('items'):
            tax_percent = order_items.get('tax_percent') if 'tax_percent' in order_items.keys() else False
            break
        return is_tax_included, tax_percent

    @staticmethod
    def check_shipping_has_tax_included_and_percent(extension_attributes):
        """
        Check order tax applied is including/ excluding and tax percent.
        :param extension_attributes: extension attributes received from order.
        :return: True/False
        """
        is_tax_included = True
        tax_percent = False
        if "apply_shipping_on_prices" in extension_attributes:
            apply_shipping_on_prices = extension_attributes.get('apply_shipping_on_prices')
            if apply_shipping_on_prices == 'excluding_tax':
                is_tax_included = False
        if "item_applied_taxes" in extension_attributes:
            for order_res in extension_attributes.get("item_applied_taxes"):
                if order_res.get('type') == "shipping" and order_res.get('applied_taxes'):
                    # shipping_tax_dict = order_res.get('applied_taxes')[0]
                    # if shipping_tax_dict:
                    #     tax_percent = shipping_tax_dict.get('percent')
                    for tax in order_res.get('applied_taxes', list()):
                        tax_percent += tax.get('percent', 0)
        return is_tax_included, tax_percent
