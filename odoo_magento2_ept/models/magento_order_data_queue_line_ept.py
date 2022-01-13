# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods to store Order Data queue line
"""
import json
import time
from datetime import timedelta, datetime
from odoo import models, fields
MAGENTO_ORDER_DATA_QUEUE_EPT = "magento.order.data.queue.ept"
SALE_ORDER = 'sale.order'


class MagentoOrderDataQueueLineEpt(models.Model):
    """
    Describes Order Data Queue Line
    """
    _name = "magento.order.data.queue.line.ept"
    _description = "Magento Order Data Queue Line EPT"
    _rec_name = "magento_order_id"

    magento_order_data_queue_id = fields.Many2one(MAGENTO_ORDER_DATA_QUEUE_EPT, ondelete="cascade")
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Magento Instance',
        help="Order imported from this Magento Instance."
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("failed", "Failed"),
        ("done", "Done"),
        ("cancel", "Cancelled")
    ], default="draft", copy=False)
    magento_order_id = fields.Char(help="Id of imported order.", copy=False)
    sale_order_id = fields.Many2one(
        "sale.order",
        copy=False,
        help="Order created in Odoo."
    )
    order_data = fields.Text(help="Data imported from Magento of current order.", copy=False)
    processed_at = fields.Datetime(
        help="Shows Date and Time, When the data is processed",
        copy=False
    )
    magento_order_common_log_lines_ids = fields.One2many(
        "common.log.lines.ept",
        "magento_order_data_queue_line_id",
        help="Log lines created against which line."
    )

    def open_sale_order(self):
        """
        call this method while click on > Order Data Queue line > Sale Order smart button
        :return: Tree view of the odoo sale order
        """
        return {
            'name': 'Sale Order',
            'type': 'ir.actions.act_window',
            'res_model': SALE_ORDER,
            'view_type': 'form',
            'view_mode': 'tree,form',
            'domain': [('id', '=', self.sale_order_id.id)]
        }
        
    def create_import_order_queue_line(self, items, magento_instance, order_queue_data):
        """
        Creates an imported orders queue line
        :param items: Items received from Magento
        :param magento_instance: Instance of Magento
        :param order_queue_data: Dictionary of order queue and count
        :return: order queue data dictionary
        """
        order_queue = order_queue_data.get('order_queue')
        total_order_queues = order_queue_data.get('total_order_queues')
        count = order_queue_data.get('count')
        for order_id in items:
            magento_order_ref = order_id.get('increment_id', False)
            if not order_queue:
                order_queue, count = self.magento_create_order_queue(magento_instance)
                total_order_queues += 1
            order_queue_line_vals = {}
            data = json.dumps(order_id)
            order_queue_line_vals.update({
                'magento_order_id': magento_order_ref,
                'magento_instance_id': magento_instance and magento_instance.id or False,
                'order_data': data,
                'magento_order_data_queue_id': order_queue and order_queue.id or False,
                'state': 'draft',
            })
            self.create(order_queue_line_vals)
            self._cr.commit()
            count = count + 1
            if count == 50:
                count = 0
                order_queue = False
        order_queue_data.update({'order_queue': order_queue, 'count': count, 'total_order_queues': total_order_queues})
        return order_queue_data

    def magento_create_order_queue(self, magento_instance):
        """
        Creates Imported Magento Orders queue
        :param magento_instance: Instance of Magento
        :return: Magento Order Data queue object
        """
        # Here search order queue having below 50 order queue line, then add queue line in that queue
        # Or else create new order queue
        queue_line_count = 0
        order_data_queue_obj = self.env[MAGENTO_ORDER_DATA_QUEUE_EPT].\
            search([('state', '=', 'draft'), ('magento_instance_id', '=', magento_instance.id)]).\
            filtered(lambda x: x.order_queue_line_total_record and x.order_queue_line_total_record < 50)
        order_queue_data_id = order_data_queue_obj[0] if order_data_queue_obj else False
        if order_queue_data_id:
            queue_line_count = order_queue_data_id.order_queue_line_total_record
            return order_queue_data_id, queue_line_count
        else:
            order_queue_vals = {
                'magento_instance_id': magento_instance and magento_instance.id or False,
                'state': 'draft',
            }
            order_queue_data_id = order_data_queue_obj.create(order_queue_vals)
            return order_queue_data_id, queue_line_count

    def auto_import_order_queue_data(self):
        """
        This method used to process synced magento order data in batch of 50 queue lines.
        This method is called from cron job.
        """
        order_queue_ids = []
        magento_import_order_queue_obj = self.env[MAGENTO_ORDER_DATA_QUEUE_EPT]
        query = """select queue.id from magento_order_data_queue_line_ept as queue_line
                inner join magento_order_data_queue_ept as queue on queue_line.magento_order_data_queue_id = queue.id
                where queue_line.state='draft' and queue.is_action_require = 'False'
                ORDER BY queue_line.create_date ASC"""
        self._cr.execute(query)
        order_data_queue_list = self._cr.fetchall()
        for result in order_data_queue_list:
            order_queue_ids.append(result[0])
        if order_queue_ids:
            order_queues = magento_import_order_queue_obj.browse(list(set(order_queue_ids)))
            self.process_order_queue_and_post_message(order_queues)
        return True

    def process_order_queue_and_post_message(self, order_queues):
        """
        This method is used to post a message if the queue is process more than 3 times otherwise
        it calls the child method to process the order queue line.
        :param order_queues: Magento import order queue object
        """
        start = time.time()
        order_queue_process_cron_time = order_queues.magento_instance_id.get_magento_cron_execution_time(
            "odoo_magento2_ept.magento_ir_cron_parent_to_process_order_queue_data")
        for order_queue in order_queues:
            order_data_queue_line_ids = order_queue.order_data_queue_line_ids

            # For counting the queue crashes for the queue.
            order_queue.queue_process_count += 1
            if order_queue.queue_process_count > 3:
                order_queue.is_action_require = True
                note = "<p>Attention %s queue is processed 3 times you need to process it manually.</p>" % order_queue.name
                order_queue.message_post(body=note)
                return True
            self._cr.commit()
            order_data_queue_line_ids.process_import_magento_order_queue_data()
            if time.time() - start > order_queue_process_cron_time - 60:
                return True
        return True

    def process_import_magento_order_queue_data(self):
        """
        This method processes order queue lines.
        """
        sale_order_obj = self.env[SALE_ORDER]
        magento_prod = {}
        inv_cust = {}
        del_cust = {}
        order = 1
        queue_id = self.magento_order_data_queue_id
        order_total_queue = queue_id.order_queue_line_total_record
        if queue_id:
            log_book_id = self.create_update_magento_order_queue_log(queue_id)
            self.env.cr.execute(
                """update magento_order_data_queue_ept set is_process_queue = False 
                where is_process_queue = True and id = %s""" % queue_id.id)
            self._cr.commit()
            for order_queue_line in self:
                magento_prod, inv_cust, del_cust, order, order_total_queue = sale_order_obj.create_magento_sales_order_ept(
                    order_queue_line.magento_instance_id, order_queue_line, magento_prod,
                    inv_cust, del_cust, order, order_total_queue, log_book_id
                )
                queue_id.is_process_queue = False
            if not log_book_id.log_lines:
                log_book_id.sudo().unlink()
            if log_book_id and log_book_id.log_lines:
                queue_id.order_common_log_book_id = log_book_id
                queue_common_log_book_id = queue_id.order_common_log_book_id
                if queue_common_log_book_id and not queue_common_log_book_id.log_lines:
                    queue_id.order_common_log_book_id.sudo().unlink()
        return True

    def create_update_magento_order_queue_log(self, queue_id):
        """
        Log book record exit for the queue, then use that existing
        Or else create new log record for that queue.
        :param queue_id:
        :return: log book record
        """
        if queue_id.order_common_log_book_id:
            log_book_id = queue_id.order_common_log_book_id
        else:
            model_id = self.env['common.log.lines.ept'].get_model_id(SALE_ORDER)
            log_book_id = self.env["common.log.book.ept"].create({
                'type': 'import',
                'module': 'magento_ept',
                'model_id': model_id,
                'res_id': queue_id.id,
                'magento_instance_id': queue_id.magento_instance_id.id
            })
        return log_book_id
