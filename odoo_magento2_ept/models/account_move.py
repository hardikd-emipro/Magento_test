# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for account move
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req

ACCOUNT_MOVE = 'account.move'
_logger = logging.getLogger("MagentoAccountMove")

class AccountInvoice(models.Model):
    """
    Describes fields and methods to import and export invoices of Magento.
    """
    _inherit = ACCOUNT_MOVE

    magento_payment_method_id = fields.Many2one(
        'magento.payment.method',
        string="Magento Payment Method",
        help="Magento Payment Method"
    )
    is_magento_invoice = fields.Boolean(
        string="Magento Invoice?",
        help="If True, It is Magento Invoice"
    )
    is_exported_to_magento = fields.Boolean(
        string='Exported to Magento',
        help='Exported to Magento',
        copy=False
    )
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string="Instance",
        help="This field relocates Magento Instance"
    )
    magento_invoice_id = fields.Char(string="Magento Invoice")
    max_no_of_attempts = fields.Integer(string='Max NO. of attempts', default = 0)
    magento_message = fields.Char(string="Invoice Message")


    def export_invoice_to_magento(self, magento_instance):
        """
        This method is used to export invoices into Magento.
        :param magento_instance: Instance of Magento.
        """
        common_log_book_obj = self.env['common.log.book.ept']
        common_log_lines_obj = self.env['common.log.lines.ept']
        invoices = self.search([
            ('is_magento_invoice', '=', True),
            ('is_exported_to_magento', '=', False),
            ('magento_instance_id', 'in', magento_instance.ids),
            ('state', 'in', ['posted']),
            ('max_no_of_attempts', '<=', 3)
        ])
        model_id = common_log_lines_obj.get_model_id(ACCOUNT_MOVE)
        log_book_id = common_log_book_obj.create({
            'type': 'export',
            'module': 'magento_ept',
            'model_id': model_id,
            'res_id': self.id,
            'magento_instance_id': magento_instance.id
        })
        for invoice in invoices:
            if (invoice.magento_payment_method_id.create_invoice_on == 'in_payment_paid' and invoice.payment_state in ['in_payment', 'paid']) or \
                    (invoice.magento_payment_method_id.create_invoice_on == 'open' and invoice.payment_state not in ['in_payment', 'paid']):
                self.call_export_invoice_api(invoice, log_book_id)
        if not log_book_id.log_lines:
            log_book_id.sudo().unlink()

    def export_invoice_in_magento(self):
        """
        Export specific invoice in Magento through API
        """
        self.ensure_one()
        common_log_book_obj = self.env['common.log.book.ept']
        common_log_lines_obj = self.env['common.log.lines.ept']
        instance = self.magento_instance_id
        model_id = common_log_lines_obj.get_model_id(ACCOUNT_MOVE)
        log_book_id = common_log_book_obj.create({
            'type': 'export',
            'module': 'magento_ept',
            'model_id': model_id,
            'res_id': self.id,
            'magento_instance_id': instance.id
        })
        if (self.magento_payment_method_id.create_invoice_on == 'in_payment_paid' and self.payment_state in ['in_payment', 'paid']) or \
                (self.magento_payment_method_id.create_invoice_on == 'open' and self.payment_state not in ['in_payment', 'paid']):
            invoice = self
            self.call_export_invoice_api(invoice, log_book_id)
        else:
            #Raise the UserError while the respected Payment method
            #configuration for Create Invoice on Magento
            #and invoice state both are different
            raise UserError("Can't Export Invoice \n"
                            "Your Configuration for the 'Create Invoice on Magento' is '%s' "
                            "For the '%s' payment method. And current invoice state is '%s'\n"
                            "Please check the Configuration and try it again" % (self.magento_payment_method_id.create_invoice_on,
                                                                                 self.magento_payment_method_id.payment_method_name,
                                                                                 self.state))
        if not log_book_id.log_lines:
            log_book_id.sudo().unlink()

    @staticmethod
    def call_export_invoice_api(invoice, log_book_id):
        """
        Export All invoices in Magento through API
        """
        sale_orders = invoice.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
        sale_order = sale_orders and sale_orders[0]
        order_item = []
        response = False
        for invoice_line in invoice.invoice_line_ids:
            item = {}
            sale_lines = invoice_line.sale_line_ids
            item_id = False
            if sale_lines:
                item_id = sale_lines[0].magento_sale_order_line_ref
            if item_id:
                item.setdefault("order_item_id", item_id)
                item.setdefault("qty", invoice_line.quantity)
                order_item.append(item)
        invoice_name = invoice.name
        data = {
            "items": order_item,
            "notify": invoice.magento_instance_id.invoice_done_notify_customer
        }
        try:
            api_url = '/V1/order/%s/invoice' % sale_order.magento_order_id
            response = req(invoice.magento_instance_id, api_url, 'POST', data)
        except Exception:
            invoice.write({
                "max_no_of_attempts" : invoice.max_no_of_attempts + 1,
                "magento_message" : _("The request could not be satisfied while export this invoice."
                                    "\nPlease check Process log %s") % (log_book_id.name)
            })
            message = _("The request could not be satisfied and an invoice couldn't be created in Magento for "
                        "Sale Order : %s & Invoice : %s due to any of the following reasons.\n"
                        "1. An invoice can't be created when an order has a status of 'On Hold/Canceled/Closed'\n"
                        "2. An invoice can't be created without products. Add products and try again. "
                        "The order does not allow an invoice to be created") % (sale_order.name, invoice_name)
            log_book_id.write({
                'log_lines': [(0, 0, {'message': message, 'order_ref': sale_order.name})]
            })
        if response:
            invoice.write({'magento_invoice_id': int(response), 'is_exported_to_magento': True})

    @staticmethod
    def _prepare_line_values(line, item_id, items):
        """
        This method is set the values of the order items values
        :task_id : 173739
        -------------------
        :param line: credit line
        :param item_id: magento.order.line -> magento_item_id
        :return: dict(order_item_id, qty)
        """
        for item in items:
            if item.get('order_item_id') == item_id:
                item.update({
                    'qty': item.get('qty') + line.quantity
                })
                return dict()
        return {
            "order_item_id": item_id,
            "qty": line.quantity,
        }

    @staticmethod
    def _calculate_discount(line):
        return round((line.price_unit * line.quantity) * line.discount / 100, 2)

    @staticmethod
    def _calculate_tax(line, discount=0):
        tax = 0
        if line.tax_ids:
            tax = line.price_total - line.price_subtotal
        return round(tax, 2)

    def _prepare_line_data(self):
        """
        This method is used to prepare items data's
        :task_id: 173739
        -------------------
        :param: True if refund process online
        :return: list of dictionary
        """
        items = list()
        product_ids = self._get_shipping_discount_product_ids()
        credit_lines = self.invoice_line_ids.filtered(
            lambda l: l.product_id.id and l.product_id.id not in product_ids)
        for line in credit_lines:
            item_id = line.sale_line_ids.magento_sale_order_line_ref
            values = self._prepare_line_values(line, item_id, items)
            if values:
                items.append(values)
        return items

    def _get_shipping_discount_product_ids(self, product='all'):
        ids = list()
        instance = self.invoice_line_ids.mapped('sale_line_ids.order_id.magento_instance_id')
        if product == 'all' or product == 'discount':
            if instance.discount_product_id:
                ids.append(instance.discount_product_id.id)
            else:
                try:
                    rounding = self.env.ref('odoo_magento2_ept.magento_product_product_discount')
                    ids.append(rounding.id)
                except Exception as error:
                    _logger.error(error)
        # --START--
        # [ADD][MAYURJ][25.05.2021]
        # Shipping TAX & Discount is not affecting at Magento.
        if product == 'all' or product == 'ship':
            if instance.shipping_product_id:
                ids.append(instance.shipping_product_id.id)
            else:
                try:
                    ship = self.env.ref('odoo_magento2_ept.product_product_shipping')
                    ids.append(ship.id)
                except Exception as error:
                    _logger.error(error)
        # --OVER--
        return ids

    def _get_payload_values(self, refund_type, return_stock, order):
        """
        This method is used to prepare the request data that will
        :Task_id: 173739
        -----------------
        :param: refund_type: possible values ('online', 'offline')
        :param: return_stock: True, if customer want to back item to stock.
        :param: order: sale order object
        :return: dict(values)
        """
        values = dict()
        ship_charge = self._get_shipping_charge()
        if order.magento_order_id:
            items = self._prepare_line_data()
            values = self._prepare_order_payload(items=items, ship_charge=ship_charge,
                                                 refund_type=refund_type,
                                                 return_stock=return_stock)
        return values

    @staticmethod
    def _prepare_order_payload(**kwargs):
        is_online, item_ids = False, list()
        if kwargs.get('refund_type') == 'online':
            is_online = True
        if kwargs.get('return_stock'):
            item_ids = [item.get('order_item_id') for item in kwargs.get('items')]
        return {
            'items': kwargs.get('items'),
            'is_online': is_online,
            'notify': True,
            'arguments': {
                'shipping_amount': kwargs.get('ship_charge', dict()).get('ship_price', 0),
            },
            'extension_attributes': {
                'return_to_stock_items': item_ids
            }
        }

    def _get_shipping_charge(self):
        """
        This method used to calculate the shipping charges
        :return: dict()
        """
        tax = discount = subtotal = price = 0.0
        product_id = self._get_shipping_discount_product_ids('ship')
        line = self.invoice_line_ids.filtered(lambda l: l.product_id.id in product_id)
        if line:
            discount = self._calculate_discount(line)
            tax = self._calculate_tax(line, discount)
            subtotal = line.price_subtotal
            price = line.price_unit
        return {
            'ship_discount': discount,
            'ship_tax': tax,
            'ship_price_incl_discount': subtotal,
            'ship_price': price,
        }

    def _create_log_process(self, success):
        """
        This method is used to create the log of the credit memo
        :task_id: 173739
        :param: result: response of the magento CreditMemo api request
        :return: True
        """
        log = self.env['magento.process.log'].create_process_log(self.magento_instance_id,
                                                                 'credit_memo')
        log_line_obj = self.env['magento.process.log.line']
        if success:
            message = "Credit Memo : {} has been refunded successfully".format(self.number)
        else:
            message = "Error While in refund process, Credit Memo : {}".format(self.number)
        log_line_obj.create_process_log_line(log, message)
        return True

    def action_create_credit_memo(self, refund_type, return_stock):
        """
        This method is responsible for creation of the CreditMemo
        :task_id : 173739
        -------------------
        :param refund_type: possible values (online/offline)
        :param return_stock: bool
        :return: bool(True/False)
        """
        instance = self.magento_instance_id
        parent_id = self.reversed_entry_id
        if instance and not self.is_exported_to_magento and parent_id:
            order = parent_id.invoice_line_ids.mapped('sale_line_ids.order_id')
            if order:
                values = self._get_payload_values(refund_type, return_stock, order)
                # Offline Refund API Endpoint
                request_path = '/V1/order/{}/refund'.format(order.magento_order_id)
                if refund_type == 'online':
                    invoice_id = self._get_magento_invoice_id(order.magento_order_id, instance)
                    if not invoice_id:
                        message = "For Order #{} Invoice are not created at Magento. " \
                                  "Refund are only possible if invoice is already created at " \
                                  "Magento.".format(order.client_order_ref)
                        raise UserError(_(message))
                    # Online Refund API Endpoint
                    request_path = '/V1/invoice/{}/refund'.format(invoice_id)
                result = req(instance, request_path, 'POST', data=values)
                if result:
                    self.write({'is_exported_to_magento': True})
                else:
                    raise UserError(_('Could not create credit memo at Magento!!'))
        return True

    @staticmethod
    def _get_magento_invoice_id(magento_id, instance):
        """
        This method help to build the url path for the ONLINE REFUND
        :task_id : 173739
        -------------------
        :param magento_id: magento oder id
        :param instance: Magento instance
        :return: Magento Invoice Id
        """
        path = "/V1/invoices?" \
               "searchCriteria[filter_groups][0][filters][0][field]=order_id&" \
               "searchCriteria[filter_groups][0][filters][0][value]={}&" \
               "searchCriteria[filter_groups][0][filters][0][condition_type]=eq".format(magento_id)
        result = req(instance, path, 'GET')
        invoice_id = False
        if result and result.get('items'):
            # FIXME: Need to handle the case when one order has multiple invoices at Magento
            invoice_id = result.get('items')[0].get('entity_id')
        return invoice_id

    @api.model
    def _refund_cleanup_lines(self, lines):
        """
        This method inherited to store the sale_line_ids value in Many2many field.
        :param lines: invoice line
        :return: result
        """
        result = super(AccountInvoice, self)._refund_cleanup_lines(lines)
        for i, line in enumerate(lines):
            for name, field in line._fields.items():
                if name == 'sale_line_ids':
                    result[i][2][name] = [(6, 0, line[name].ids)]
        return result