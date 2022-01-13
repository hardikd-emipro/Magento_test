# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for sync/ Import product queues.
"""
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req, create_search_criteria
from ..python_library.php import Php


class SyncImportMagentoProductQueue(models.Model):
    """
    Describes sync/ Import product queues.
    """
    _name = "sync.import.magento.product.queue"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Sync/ Import Product Queue"

    name = fields.Char(help="Sequential name of imported/ Synced products.", copy=False)
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Instance',
        help="Product imported from or Synced to this Magento Instance."
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partially_completed', 'Partially Completed'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], default='draft', copy=False, help="Status of Order Data Queue", compute="_compute_queue_state", store=True)
    import_product_common_log_book_id = fields.Many2one(
        "common.log.book.ept",
        help="Related Log book which has all logs for current queue."
    )
    import_product_common_log_lines_ids = fields.One2many(
        related="import_product_common_log_book_id.log_lines",
        help="Log lines of Common log book for particular product queue"
    )
    import_product_queue_line_ids = fields.One2many(
        "sync.import.magento.product.queue.line",
        "sync_import_magento_product_queue_id",
        help="Sync/ Import product queue line ids"
    )
    import_product_queue_line_total_record = fields.Integer(
        string='Total Records',
        compute='_compute_product_queue_line_record',
        help="Returns total number of Sync/Import product queue lines"
    )
    import_product_queue_line_draft_record = fields.Integer(
        string='Draft Records',
        compute='_compute_product_queue_line_record',
        help="Returns total number of draft Sync/Import product queue lines"
    )
    import_product_queue_line_fail_record = fields.Integer(
        string='Fail Records',
        compute='_compute_product_queue_line_record',
        help="Returns total number of Failed Sync/Import product queue lines"
    )
    import_product_queue_line_done_record = fields.Integer(
        string='Done Records',
        compute='_compute_product_queue_line_record',
        help="Returns total number of done Sync/Import product queue lines"
    )
    import_product_queue_line_cancel_record = fields.Integer(
        string='Cancel Records',
        compute='_compute_product_queue_line_record',
        help="Returns total number of cancel Sync/Import product queue lines"
    )
    is_process_queue = fields.Boolean('Is Processing Queue', default=False)
    running_status = fields.Char(default="Running...")
    is_action_require = fields.Boolean(default=False)
    queue_process_count = fields.Integer(string="Queue Process Times",
                                         help="it is used know queue how many time processed")

    @api.depends('import_product_queue_line_ids.state')
    def _compute_queue_state(self):
        """
        Computes state from different states of queue lines.
        """
        for record in self:
            if record.import_product_queue_line_total_record == record.import_product_queue_line_done_record + record.import_product_queue_line_cancel_record:
                record.state = "completed"
            elif record.import_product_queue_line_total_record == record.import_product_queue_line_draft_record:
                record.state = "draft"
            elif record.import_product_queue_line_total_record == record.import_product_queue_line_fail_record:
                record.state = "failed"
            else:
                record.state = "partially_completed"

    def _compute_product_queue_line_record(self):
        """
        This will calculate total, draft, failed and done products sync/import from Magento.
        """
        for product_queue in self:
            product_queue.import_product_queue_line_total_record = len(
                product_queue.import_product_queue_line_ids
            )
            product_queue.import_product_queue_line_draft_record = len(
                product_queue.import_product_queue_line_ids.filtered(lambda x: x.state == 'draft')
            )
            product_queue.import_product_queue_line_fail_record = len(
                product_queue.import_product_queue_line_ids.filtered(lambda x: x.state == 'failed')
            )
            product_queue.import_product_queue_line_done_record = len(
                product_queue.import_product_queue_line_ids.filtered(lambda x: x.state == 'done')
            )
            product_queue.import_product_queue_line_cancel_record = len(
                product_queue.import_product_queue_line_ids.filtered(lambda x: x.state == 'cancel')
            )

    @api.model
    def create(self, vals):
        """
        Creates a sequence for Ordered Data Queue
        :param vals: values to create Ordered Data Queue
        :return: SyncImportMagentoProductQueue Object
        """
        sequence_id = self.env.ref('odoo_magento2_ept.magento_seq_import_product_queue_data').ids
        if sequence_id:
            record_name = self.env['ir.sequence'].browse(sequence_id).next_by_id()
        else:
            record_name = '/'
        vals.update({'name': record_name or ''})
        return super(SyncImportMagentoProductQueue, self).create(vals)

    @staticmethod
    def _get_product_search_filter(**kwargs):
        filters = {
            'updated_at': {
                'to': kwargs.get('to_date')
            },
            'status': 1,
            'type_id': {
                'in': kwargs.get('product_type')
            }
        }
        if kwargs.get('from_date'):
            filters.get('updated_at', dict()).update({'from': kwargs.get('from_date')})
        return filters

    def create_sync_import_product_queues(
            self,
            instance,
            from_date,
            to_date,
            do_not_update_product = True
    ):
        """
        Creates product queues when sync/ import products from Magento.
        :param instance: current instance of Magento
        :param from_date:  Sync product start from this date
        :param to_date: Sync product end to this date
        :return:
        """
        filters = {
            'updated_at': {'from': from_date, 'to': to_date},
            'status': 1
        }
        # First call the searchCriteria with configurable product type and then simple
        # To map simple product with configurable properly. So we get configurable product first.
        # And then after get the call the searchCriteria with the simple product type.
        product_types = ['configurable', 'simple']
        product_queue_data = {'product_queue': False, 'count': 0, 'total_product_queues': 0}
        for product_type in product_types:
            filters = self._get_product_search_filter(from_date=from_date, to_date=to_date,
                                                      product_type=product_type)
            response = self.get_products_api_response_from_magento(instance, filters)
            if response.get('total_count') == 0:
                # instance.magento_import_product_page_count = 1
                continue
            if response.get('items'):
                product_skus = []
                total_imported_products, product_queue_data = self.import_product_in_queue_line(response, instance, product_skus, product_queue_data, do_not_update_product)
                while total_imported_products <= response.get('total_count'):
                    response = self.get_products_api_response_from_magento(instance, filters)
                    product_skus = []
                    total_imported_products, product_queue_data = self.import_product_in_queue_line(response, instance, product_skus,
                                                                           product_queue_data, do_not_update_product)
                    self._cr.commit()
            instance.magento_import_product_page_count = 1
        return product_queue_data

    def import_product_in_queue_line(self, response, instance, product_skus, product_queue_data, do_not_update_product):
        """
        Add only 50 line in single queue,
        and after that increase the instance's magento import product page count
        :param response: product response form the magento
        :param instance: magento instance
        :param product_skus: sku array
        :param product_queue_data:
        :return: total imported products and product queue data
        """
        for product in response.get('items'):
            if not product.get('sku') in product_skus:
                product_skus.append(product.get('sku'))
        product_queue_data = self.import_specific_product(instance, product_skus, do_not_update_product, product_queue_data)
        total_imported_products = instance.magento_import_product_page_count * 50
        instance.magento_import_product_page_count += 1
        return total_imported_products, product_queue_data

    def get_products_api_response_from_magento(self,instance, filters):
        search_criteria = create_search_criteria(filters)
        search_criteria['searchCriteria']['pageSize'] = 50
        search_criteria['searchCriteria']['currentPage'] = instance.magento_import_product_page_count
        query_string = Php.http_build_query(search_criteria)
        try:
            api_url = '/V1/products?%s' % query_string
            response = req(instance, api_url)
        except Exception as error:
            raise UserError(_("Error while requesting products {}".format(error)))
        return response

    def import_specific_product(
            self,
            instance,
            product_sku_lists,
            do_not_update_product,
            product_queue_data=False
    ):
        """
        Creates product queues when sync/ import products from Magento.
        :param instance: current instance of Magento
        :param product_sku_lists:  Dictionary of Product SKUs
        :param product_queue_data:  Dictionary of Product Queue Data or False
        :return:
        """
        product_queue_line = self.env["sync.import.magento.product.queue.line"]
        if not product_queue_data:
            product_queue_data = {'product_queue': False, 'count': 0, 'total_product_queues': 0}
        log_line_id = []
        for product_sku in product_sku_lists:
            try:
                sku = Php.quote_sku(product_sku)
                api_url = '/V1/products/%s' % sku
                response = req(instance, api_url)
            except Exception as error:
                if len(product_sku_lists) > 1:
                    log_line = self.env['common.log.lines.ept'].create({
                        'message': 'Magento Product Not found for SKU %s' % product_sku,
                        'default_code': product_sku
                    })
                    log_line_id.append(log_line.id)
                    continue
                else:
                    raise UserError(_("Error while requesting products" + str(error)))
            if response:
                product_queue_data = product_queue_line.create_import_specific_product_queue_line(
                    response,
                    instance,
                    product_queue_data,
                    do_not_update_product
                )
        if log_line_id:
            self.create_log_of_missing_sku(instance, product_queue_data, log_line_id)
        return product_queue_data

    def create_log_of_missing_sku(self, instance, product_queue_data, log_line_id):
        """
        create common log record for the missing SKU.
        :param instance:
        :param product_queue_data:
        :param log_line_id:
        :return:
        """
        model_id = self.env['common.log.lines.ept'].get_model_id('sync.import.magento.product.queue')
        product_queue = product_queue_data.get('product_queue')
        log_book_id = self.env['common.log.book.ept'].create({
            'type': 'import',
            'module': 'magento_ept',
            'model_id': model_id,
            'res_id': product_queue.id if product_queue else False,
            'magento_instance_id': instance.id,
            "log_lines": [(6, 0, log_line_id)]
        })
        if product_queue:
            product_queue.import_product_common_log_book_id = log_book_id