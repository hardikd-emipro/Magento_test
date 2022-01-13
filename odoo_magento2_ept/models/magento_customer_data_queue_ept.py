# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for Magento import customer data queue.
"""
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.addons.odoo_magento2_ept.models.api_request import req, create_search_criteria
from odoo.addons.odoo_magento2_ept.python_library.php import Php

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'


class MagentoCustomerDataQueueEpt(models.Model):
    """
    Describes Magento Customer Data Queue
    """
    _name = "magento.customer.data.queue.ept"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Magento Customer Data Queue EPT"
    name = fields.Char(help="Sequential name of imported customer.", copy=False)
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Magento Instance',
        help="Customer imported from this Magento Instance."
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_completed', 'Partially Completed'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], default='draft', copy=False, help="Status of Customer Data Queue", compute="_compute_queue_state", store=True)
    customer_common_log_book_id = fields.Many2one(
        "common.log.book.ept",
        help="Related Log book which has all logs for current queue."
    )
    magento_customer_common_log_lines_ids = fields.One2many(
        related="customer_common_log_book_id.log_lines",
        help="Log lines of Common log book for particular customer queue"
    )
    customer_queue_line_ids = fields.One2many(
        "magento.customer.data.queue.line.ept",
        "magento_customer_data_queue_id",
        help="Customer data queue line ids"
    )
    customer_queue_line_total_record = fields.Integer(
        string='Total Records',
        compute='_compute_customer_queue_line_record',
        help="Returns total number of order data queue lines"
    )
    customer_queue_line_draft_record = fields.Integer(
        string='Draft Records',
        compute='_compute_customer_queue_line_record',
        help="Returns total number of draft order data queue lines"
    )
    customer_queue_line_fail_record = fields.Integer(
        string='Fail Records',
        compute='_compute_customer_queue_line_record',
        help="Returns total number of Failed order data queue lines"
    )
    customer_queue_line_done_record = fields.Integer(
        string='Done Records',
        compute='_compute_customer_queue_line_record',
        help="Returns total number of done order data queue lines"
    )
    customer_queue_line_cancel_record = fields.Integer(
        string='Cancel Records',
        compute='_compute_customer_queue_line_record',
        help="Returns total number of cancel order data queue lines"
    )
    is_process_queue = fields.Boolean('Is Processing Queue', default=False)
    running_status = fields.Char(default="Running...")
    is_action_require = fields.Boolean(default=False)
    queue_process_count = fields.Integer(string="Queue Process Times",
                                         help="It is used know queue how many time processed")

    @api.depends('customer_queue_line_ids.state')
    def _compute_queue_state(self):
        """
        Computes state from different states of queue lines.
        """
        for record in self:
            if record.customer_queue_line_total_record == record.customer_queue_line_done_record + record.customer_queue_line_cancel_record:
                record.state = "completed"
            elif record.customer_queue_line_total_record == record.customer_queue_line_draft_record:
                record.state = "draft"
            elif record.customer_queue_line_total_record == record.customer_queue_line_fail_record:
                record.state = "failed"
            else:
                record.state = "partially_completed"

    @api.depends('customer_queue_line_ids.state')
    def _compute_customer_queue_line_record(self):
        """
        This will calculate total, draft, failed and done orders from Magento.
        """
        for customer_queue in self:
            customer_queue.customer_queue_line_total_record = len(customer_queue.customer_queue_line_ids)
            customer_queue.customer_queue_line_draft_record = len(
                customer_queue.customer_queue_line_ids.filtered(lambda x: x.state == 'draft')
            )
            customer_queue.customer_queue_line_fail_record = len(
                customer_queue.customer_queue_line_ids.filtered(lambda x: x.state == 'failed')
            )
            customer_queue.customer_queue_line_done_record = len(
                customer_queue.customer_queue_line_ids.filtered(lambda x: x.state == 'done')
            )
            customer_queue.customer_queue_line_cancel_record = len(
                customer_queue.customer_queue_line_ids.filtered(lambda x: x.state == 'cancel')
            )

    def create(self, vals):
        """
        Creates a sequence for Customer Data Queue
        :param vals: values to create Customer Data Queue
        :return: MagentoCustomerDataQueueEpt Object
        """
        sequence_id = self.env.ref('odoo_magento2_ept.seq_customer_queue_data').ids
        if sequence_id:
            record_name = self.env['ir.sequence'].browse(sequence_id).next_by_id()
        else:
            record_name = '/'
        vals.update({'name': record_name or ''})
        return super(MagentoCustomerDataQueueEpt, self).create(vals)

    def magento_create_customer_data_queues(self, **kwargs):
        """
        Import magento customers and stores them as a bunch of 50 orders queue.
        :param instance: Instance of Magento
        """
        customer_queue_line_obj = self.env["magento.customer.data.queue.line.ept"]
        magento_instance = kwargs.get('magento_instance')
        website_ids = magento_instance.magento_website_ids
        customer_queue_data = {'customer_queue': False, 'count': 0, 'total_customer_queues': 0}
        for website_id in website_ids:
            customer_page_count = magento_instance.magento_import_customer_current_page
            # Get Filters for search customers
            filters = self.magento_get_search_filters_ept(website_id, **kwargs)
            response = self.get_customer_api_response_from_magento(magento_instance, filters, customer_page_count)
            if response.get('total_count') == 0 or not response.get('items'):
                magento_instance.magento_import_customer_current_page = 1
                continue
            customer_queue_data = customer_queue_line_obj.create_import_customer_queue_line(
                response.get('items', []), magento_instance, customer_queue_data)
            total_imported_products = customer_page_count * 200
            customer_page_count += 1
            magento_instance.magento_import_customer_current_page = customer_page_count
            if total_imported_products <= response.get('total_count'):
                magento_instance.magento_import_customer_current_page = customer_page_count
            else:
                magento_instance.magento_import_customer_current_page = 1
            while total_imported_products <= response.get('total_count'):
                response = self.get_customer_api_response_from_magento(magento_instance, filters, customer_page_count)
                if not response.get('items'):
                    magento_instance.magento_import_customer_current_page = 1
                    break
                customer_queue_data = customer_queue_line_obj.create_import_customer_queue_line(
                    response.get('items', []), magento_instance, customer_queue_data)
                total_imported_products = customer_page_count * 200
                customer_page_count += 1
                magento_instance.magento_import_customer_current_page = customer_page_count
                self._cr.commit()
        return customer_queue_data

    @staticmethod
    def magento_get_search_filters_ept(website_id, **kwargs):
        """
        Create dictionary for required filters params for search customers from API.
        :param website_id: magento.website()
        :param kwargs: dict()
        :return: dict()
        """
        # Find last import date from magento instance if not found then pass None in from_date.
        # last_partner_import_date = kwargs.get('magento_instance').last_partner_import_date
        # if not last_partner_import_date:
        last_partner_import_date = None
        from_date = kwargs.get('start_date', None)
        to_date = kwargs.get('end_date', None)
        return {
            'from_date': from_date if from_date else last_partner_import_date,
            'to_date': to_date if to_date else datetime.now(),
            'website_id': website_id.magento_website_id
        }

    def get_customer_api_response_from_magento(self, magento_instance, filters, customer_page_count):
        search_criteria = self.create_search_criteria_for_import_partner(filters, customer_page_count)
        que_str = Php.http_build_query(search_criteria)
        try:
            api_url = '/V1/customers/search?%s' % que_str
            response = req(magento_instance, api_url)
        except Exception as error:
            raise UserError("Error while requesting import customer : %s" % error)
        return response

    @staticmethod
    def create_search_criteria_for_import_partner(customer_filters, customer_current_page):
        """
        Based on customer filters it will create a search criteria for import partner.
        :param customer_filters: Dictionary of filters
        :param customer_current_page: Define current page for import customer via API
        :return: filters
        """
        filters = {}
        if customer_filters.get('from_date') is not None:
            from_date = customer_filters.get('from_date')
            filters.setdefault('updated_at', {})
            filters['updated_at']['from'] = from_date.strftime(MAGENTO_DATETIME_FORMAT)
        if customer_filters.get('to_date'):
            to_date = customer_filters.get('to_date')
            filters.setdefault('updated_at', {})
            filters['updated_at']['to'] = to_date.strftime(MAGENTO_DATETIME_FORMAT)
        filters.setdefault('website_id', {})
        filters['website_id']['in'] = customer_filters.get('website_id')
        filters = create_search_criteria(filters)
        filters['searchCriteria']['pageSize'] = 200
        filters['searchCriteria']['currentPage'] = customer_current_page
        return filters
