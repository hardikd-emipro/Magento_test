# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods to store sync/ Import product queue line
"""
import json
import time
from datetime import timedelta, datetime
from odoo import models, fields
SYNC_IMPORT_MAGENTO_PRODUCT_QUEUE = "sync.import.magento.product.queue"


class SyncImportMagentoProductQueueLine(models.Model):
    """
    Describes sync/ Import product Queue Line
    """
    _name = "sync.import.magento.product.queue.line"
    _description = "Sync/ Import Product Queue Line"
    _rec_name = "product_sku"
    sync_import_magento_product_queue_id = fields.Many2one(
        SYNC_IMPORT_MAGENTO_PRODUCT_QUEUE,
        ondelete="cascade"
    )
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Instance',
        help="Products imported from or Synced to this Magento Instance."
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("failed", "Failed"),
        ("done", "Done"),
        ("cancel", "Cancelled")
    ], default="draft", copy=False)
    product_sku = fields.Char(help="SKU of imported product.", copy=False)
    product_data = fields.Text(help="Product Data imported from magento.", copy=False)
    processed_at = fields.Datetime(
        help="Shows Date and Time, When the data is processed",
        copy=False
    )
    import_product_common_log_lines_ids = fields.One2many(
        "common.log.lines.ept",
        "import_product_queue_line_id",
        help="Log lines created against which line."
    )
    do_not_update_existing_product = fields.Boolean(
        string="Do not update existing Products?",
        help="If checked and Product(s) found in odoo/magento layer, then not update the Product(s)"
    )

    def create_import_specific_product_queue_line(
            self,
            items,
            instance,
            product_queue_data,
            do_not_update_product = True
    ):
        """
        Creates a product data queue line and splits product queue line after 50 orders.
        :param items: product data received from magento
        :param instance: instance of magento
        :param product_queue_data: If True, product queue is already there.
        """
        product_sku = items.get('sku', False)
        product_queue = product_queue_data.get('product_queue')
        count = product_queue_data.get('count')
        total_product_queues = product_queue_data.get('total_product_queues')
        if not product_queue:
            product_queue = self.magento_create_product_queue(instance)
            total_product_queues += 1
        product_queue_line_values = {}
        data = json.dumps(items)
        product_queue_line_values.update({
            'product_sku': product_sku,
            'magento_instance_id': instance and instance.id or False,
            'product_data': data,
            'sync_import_magento_product_queue_id': product_queue and product_queue.id or False,
            'state': 'draft',
            'do_not_update_existing_product': do_not_update_product
        })
        self.create(product_queue_line_values)
        count = count + 1
        if count == 50:
            count = 0
            product_queue = False
        product_queue_data.update({
            'product_queue': product_queue,
            'count': count,
            'total_product_queues': total_product_queues
        })
        return product_queue_data

    def magento_create_product_queue(self, instance):
        """
        This method used to create a product queue as per the split requirement of the
        queue. It is used for process the queue manually.
        :param instance: instance of Magento
        """
        product_queue_vals = {
            'magento_instance_id': instance and instance.id or False,
            'state': 'draft'
        }
        product_queue_data_id = self.env[SYNC_IMPORT_MAGENTO_PRODUCT_QUEUE].create(product_queue_vals)
        return product_queue_data_id

    def auto_import_magento_product_queue_data(self):
        """
        This method used to process synced magento product data in batch of 50 queue lines.
        This method is called from cron job.
        """
        product_queue_ids = []
        magento_import_product_queue_obj = self.env[SYNC_IMPORT_MAGENTO_PRODUCT_QUEUE]
        query = """select queue.id from sync_import_magento_product_queue_line as queue_line
        inner join sync_import_magento_product_queue as queue on queue_line.sync_import_magento_product_queue_id = queue.id
        where queue_line.state='draft' and queue.is_action_require = 'False'
        ORDER BY queue_line.create_date ASC"""
        self._cr.execute(query)
        product_data_queue_list = self._cr.fetchall()
        for result in product_data_queue_list:
            product_queue_ids.append(result[0])
        if product_queue_ids:
            product_queues = magento_import_product_queue_obj.browse(list(set(product_queue_ids)))
            self.process_product_queue_and_post_message(product_queues)
        return True

    def process_product_queue_and_post_message(self, product_queues):
        """
        This method is used to post a message if the queue is process more than 3 times otherwise
        it calls the child method to process the product queue line.
        :param product_queues: Magento import product queue object
        """
        start = time.time()
        product_queue_process_cron_time = product_queues.magento_instance_id.get_magento_cron_execution_time(
            "odoo_magento2_ept.ir_cron_parent_to_process_product_queue_data")
        for product_queue in product_queues:
            product_data_queue_line_ids = product_queue.import_product_queue_line_ids

            # For counting the queue crashes for the queue.
            product_queue.queue_process_count += 1
            if product_queue.queue_process_count > 3:
                product_queue.is_action_require = True
                note = "<p>Attention %s queue is processed 3 times you need to process it manually.</p>" % product_queue.name
                product_queue.message_post(body=note)
                return True
            self._cr.commit()
            product_data_queue_line_ids.process_import_product_queue_data()
            if time.time() - start > product_queue_process_cron_time - 60:
                return True
        return True

    def process_import_product_queue_data(self):
        """
        This method processes product queue lines.
        """
        magento_product_obj = self.env['magento.product.product']
        magento_pr_sku = {}
        product_count = 1
        queue_id = self.sync_import_magento_product_queue_id
        product_total_queue = queue_id.import_product_queue_line_total_record
        if queue_id:
            log_book_id = self.create_update_magento_product_queue_log(queue_id)
            self.env.cr.execute(
                """update sync_import_magento_product_queue set is_process_queue = False 
                where is_process_queue = True and id = %s""" % queue_id.id)
            self._cr.commit()
            if not self.magento_instance_id.import_product_category:
                # check product category set in the instance or not
                # if the category is not set then create log line
                # set the state as Failed
                message = 'You are trying to "Import Product" \n ' \
                          "But Still, you didn't set the " \
                          "'Import Product Category' for %s Instance." % (self.magento_instance_id.name)
                log_book_id.add_log_line(message, False, queue_id.id,
                                         "import_product_queue_line_id")
                self.write({'state': 'failed'})
                return True
            for product_queue_line in self:
                magento_pr_sku, product_count, product_total_queue = magento_product_obj.create_magento_product_in_odoo(
                    product_queue_line.magento_instance_id, product_queue_line, magento_pr_sku,
                    product_count, product_total_queue, log_book_id
                )
                queue_id.is_process_queue = False
            if not log_book_id.log_lines:
                log_book_id.unlink()
            if log_book_id and log_book_id.log_lines:
                queue_id.import_product_common_log_book_id = log_book_id
                queue_common_log_book_id = queue_id.import_product_common_log_book_id
                if queue_common_log_book_id and not queue_common_log_book_id.log_lines:
                    queue_id.import_product_common_log_book_id.unlink()
        return True

    def create_update_magento_product_queue_log(self, queue_id):
        if queue_id.import_product_common_log_book_id:
            log_book_id = queue_id.import_product_common_log_book_id
        else:
            model_id = self.env['common.log.lines.ept'].get_model_id('magento.product.product')
            log_book_id = self.env["common.log.book.ept"].create({
                'type': 'import',
                'module': 'magento_ept',
                'model_id': model_id,
                'res_id': queue_id.id,
                'magento_instance_id': queue_id.magento_instance_id.id
            })
        return log_book_id
