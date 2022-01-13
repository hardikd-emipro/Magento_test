# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for Magento import order data queue.
"""
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req, create_search_criteria
from ..python_library.php import Php

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
MAGENTO_ORDER_DATA_QUEUE_LINE_EPT = "magento.order.data.queue.line.ept"


class MagentoOrderDataQueueEpt(models.Model):
    """
    Describes Magento Order Data Queue
    """
    _name = "magento.order.data.queue.ept"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Magento Order Data Queue EPT"
    name = fields.Char(help="Sequential name of imported order.", copy=False)
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Magento Instance',
        help="Order imported from this Magento Instance."
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_completed', 'Partially Completed'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], default='draft', copy=False, help="Status of Order Data Queue", compute="_compute_queue_state", store=True)
    order_common_log_book_id = fields.Many2one(
        "common.log.book.ept",
        help="Related Log book which has all logs for current queue."
    )
    magento_order_common_log_lines_ids = fields.One2many(
        related="order_common_log_book_id.log_lines",
        help="Log lines of Common log book for particular order queue"
    )
    order_data_queue_line_ids = fields.One2many(
        MAGENTO_ORDER_DATA_QUEUE_LINE_EPT,
        "magento_order_data_queue_id",
        help="Order data queue line ids"
    )
    order_queue_line_total_record = fields.Integer(
        string='Total Records',
        compute='_compute_order_queue_line_record',
        help="Returns total number of order data queue lines"
    )
    order_queue_line_draft_record = fields.Integer(
        string='Draft Records',
        compute='_compute_order_queue_line_record',
        help="Returns total number of draft order data queue lines"
    )
    order_queue_line_fail_record = fields.Integer(
        string='Fail Records',
        compute='_compute_order_queue_line_record',
        help="Returns total number of Failed order data queue lines"
    )
    order_queue_line_done_record = fields.Integer(
        string='Done Records',
        compute='_compute_order_queue_line_record',
        help="Returns total number of done order data queue lines"
    )
    order_queue_line_cancel_record = fields.Integer(
        string='Cancel Records',
        compute='_compute_order_queue_line_record',
        help="Returns total number of cancel order data queue lines"
    )
    is_process_queue = fields.Boolean('Is Processing Queue', default=False)
    running_status = fields.Char(default="Running...")
    is_action_require = fields.Boolean(default=False)
    queue_process_count = fields.Integer(string="Queue Process Times",
                                         help="It is used know queue how many time processed")

    @api.depends('order_data_queue_line_ids.state')
    def _compute_queue_state(self):
        """
        Computes state from different states of queue lines.
        """
        for record in self:
            if record.order_queue_line_total_record == record.order_queue_line_done_record + record.order_queue_line_cancel_record:
                record.state = "completed"
            elif record.order_queue_line_total_record == record.order_queue_line_draft_record:
                record.state = "draft"
            elif record.order_queue_line_total_record == record.order_queue_line_fail_record:
                record.state = "failed"
            else:
                record.state = "partially_completed"

    @api.depends('order_data_queue_line_ids.state')
    def _compute_order_queue_line_record(self):
        """
        This will calculate total, draft, failed and done orders from Magento.
        """
        for order_queue in self:
            order_queue.order_queue_line_total_record = len(order_queue.order_data_queue_line_ids)
            order_queue.order_queue_line_draft_record = len(
                order_queue.order_data_queue_line_ids.filtered(lambda x: x.state == 'draft')
            )
            order_queue.order_queue_line_fail_record = len(
                order_queue.order_data_queue_line_ids.filtered(lambda x: x.state == 'failed')
            )
            order_queue.order_queue_line_done_record = len(
                order_queue.order_data_queue_line_ids.filtered(lambda x: x.state == 'done')
            )
            order_queue.order_queue_line_cancel_record = len(
                order_queue.order_data_queue_line_ids.filtered(lambda x: x.state == 'cancel')
            )

    def create(self, vals):
        """
        Creates a sequence for Ordered Data Queue
        :param vals: values to create Ordered Data Queue
        :return: MagentoOrderDataQueueEpt Object
        """
        sequence_id = self.env.ref('odoo_magento2_ept.seq_order_queue_data').ids
        if sequence_id:
            record_name = self.env['ir.sequence'].browse(sequence_id).next_by_id()
        else:
            record_name = '/'
        vals.update({'name': record_name or ''})
        return super(MagentoOrderDataQueueEpt, self).create(vals)

    def magento_create_order_data_queues(self, magento_instance, start_date, end_date, is_wizard=False):
        """
        Import magento orders and stores them as a bunch of 50 orders queue.
        :param magento_instance: Instance of Magento
        :param start_date: Import Order Start Date
        :param end_date: Import Order End Date
        :param is_wizard: True if import order is performed via operation wizard else False
        """
        order_data_queue_line = self.env[MAGENTO_ORDER_DATA_QUEUE_LINE_EPT]
        bus_bus_obj = self.env['bus.bus']
        order_queue_data = {'order_queue': False, 'count': 0, 'total_order_queues': 0}
        active_user_id = self.env.user.id
        magento_order_count = magento_instance.active_user_ids.filtered(lambda x: x.user_id.id == active_user_id)
        if is_wizard:
            order_page_count = 1
        else:
            order_page_count = magento_order_count.magento_import_order_page_count
        response = self.get_orders_api_response_from_magento(magento_instance, end_date, start_date, order_page_count)
        if response.get('messages', False) and response.get('messages', False).get('error'):
            raise UserError(_('We are getting internal server errors while receiving the response from Magento.'
                              ' This can be due to the following reasons.\n'
                              '1. Permission issues\n'
                              '2. Memory Limitation\n'
                              '3. Third Party Plugin issue.\n %s', (response.get('messages').get('error')[0].get('message'),)))
        if response.get('total_count') == 0:
            if not is_wizard:
                magento_order_count.magento_import_order_page_count = 1
            else:
                message = "No orders Found between %s and %s for %s" % (
                    datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S').date(),
                    datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').date(), magento_instance.name)
                bus_bus_obj.sendone((self._cr.dbname, 'res.partner', self.env.user.partner_id.id),
                                    {'type': 'simple_notification', 'title': 'Magento Connector',
                                     'message': message, 'sticky': False, 'warning': True})
        if response.get('items'):
            order_queue_data = order_data_queue_line.create_import_order_queue_line(
                response.get('items'), magento_instance, order_queue_data)
            total_imported_orders = order_page_count * 100
            order_page_count += 1
            while total_imported_orders <= response.get('total_count'):
                response = self.get_orders_api_response_from_magento(
                    magento_instance, end_date, start_date, order_page_count)
                if response.get('items'):
                    order_queue_data = order_data_queue_line.create_import_order_queue_line(
                        response.get('items'), magento_instance, order_queue_data
                    )
                    total_imported_orders = order_page_count * 100
                    if not is_wizard:
                        magento_order_count.magento_import_order_page_count += 1
                    order_page_count += 1
                    self._cr.commit()
            if not is_wizard:
                magento_order_count.magento_import_order_page_count = 1
        return order_queue_data

    def get_orders_api_response_from_magento(self, instance, end_date, start_date, order_page_count):
        filters = {}
        filters.update({'from_date': start_date, 'to_date': end_date})
        search_criteria = self.create_search_criteria_for_import_order(
            filters, instance.import_magento_order_status_ids.mapped('status'))
        search_criteria['searchCriteria']['pageSize'] = 100
        search_criteria['searchCriteria']['currentPage'] = order_page_count
        query_string = Php.http_build_query(search_criteria)
        try:
            api_url = '/V1/orders?%s' % query_string
            response = req(instance, api_url)
        except Exception as error:
            raise UserError(_("Error while requesting orders {}".format(error)))
        return response

    def import_specific_order(self, instance, order_reference_lists):
        """
        Creates order queues when import sale orders from Magento.
        :param instance: current instance of Magento
        :param order_reference_lists:  Dictionary of Order References
        :return:
        """
        order_data_queue_line = self.env[MAGENTO_ORDER_DATA_QUEUE_LINE_EPT]
        order_queue_data = {'order_queue': False, 'count': 0, 'total_order_queues': 0}
        order_statuses = ['new', 'processing', 'complete'] #instance.import_magento_order_status_ids.mapped('status')
        for order_reference in order_reference_lists:
            filters = {'increment_id': order_reference}
            search_criteria = create_search_criteria(filters)
            query_string = Php.http_build_query(search_criteria)
            try:
                api_url = '/V1/orders?%s' % query_string
                response = req(instance, api_url)
            except Exception as error:
                raise UserError(_("Error while requesting Orders - %s", str(error)))
            if response.get('items') and response.get('items')[0].get('state') in order_statuses:
                order_queue_data = order_data_queue_line.create_import_order_queue_line(
                    response.get('items'), instance, order_queue_data
                )
        return order_queue_data

    def create_search_criteria_for_import_order(self, import_order_filter, magento_order_status):
        """
        Create Search Criteria to import orders from Magento.
        :param import_order_filter: Dictionary for filters
        :param magento_order_status: order status to be imported
        :return: Dictionary of filters
        """
        import_order_filters = {}
        if import_order_filter.get('from_date') is not None:
            from_date = import_order_filter.get('from_date')
            import_order_filters.setdefault('updated_at', {})
            import_order_filters['updated_at']['from'] = from_date
        if import_order_filter.get('to_date'):
            to_date = import_order_filter.get('to_date')
            import_order_filters.setdefault('updated_at', {})
            import_order_filters['updated_at']['to'] = to_date
        import_order_filters.setdefault('state', {})
        import_order_filters['state']['in'] = magento_order_status
        import_order_filters = create_search_criteria(import_order_filters)
        return import_order_filters
