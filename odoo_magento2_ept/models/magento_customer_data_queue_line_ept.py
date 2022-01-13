# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods to store Customer Data queue line
"""
import time
import json
from datetime import timedelta, datetime
from odoo import models, fields
MAGENTO_CUSTOMER_DATA_QUEUE_EPT = "magento.customer.data.queue.ept"


class MagentoCustomerDataQueueLineEpt(models.Model):
    """
    Describes Customer Data Queue Line
    """
    _name = "magento.customer.data.queue.line.ept"
    _description = "Magento Customer Data Queue Line EPT"
    _rec_name = "magento_customer_id"
    magento_customer_data_queue_id = fields.Many2one(MAGENTO_CUSTOMER_DATA_QUEUE_EPT, ondelete="cascade")
    magento_instance_id = fields.Many2one(
        'magento.instance',
        string='Magento Instance',
        help="Customer imported from this Magento Instance."
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("failed", "Failed"),
        ("done", "Done"),
        ("cancel", "Cancelled")
    ], default="draft", copy=False)
    magento_customer_id = fields.Char(help="Id of imported customer.", copy=False)
    customer_id = fields.Many2one(
        "res.partner",
        copy=False,
        help="Customer created in Odoo."
    )
    customer_data = fields.Text(help="Data imported from Magento of current customer.", copy=False)
    processed_at = fields.Datetime(
        help="Shows Date and Time, When the data is processed",
        copy=False
    )
    magento_customer_common_log_lines_ids = fields.One2many(
        "common.log.lines.ept",
        "magento_customer_data_queue_line_id",
        help="Log lines created against which line."
    )

    def create_import_customer_queue_line(self, customers, magento_instance, customer_queue_data):
        """
        Creates an imported customer queue line
        :param customers: Items received from Magento
        :param magento_instance: Instance of Magento
        :return: True
        """
        customer_queue = customer_queue_data.get('customer_queue')
        total_customer_queues = customer_queue_data.get('total_customer_queues')
        count = customer_queue_data.get('count')
        for customer in customers:
            magento_customer_id = customer.get('id', False)
            if not customer_queue:
                customer_queue = self.magento_create_customer_queue(magento_instance)
                total_customer_queues += 1
            data = json.dumps(customer)
            customer_queue_line_values = {
                'magento_customer_id': magento_customer_id,
                'magento_instance_id': magento_instance and magento_instance.id or False,
                'customer_data': data,
                'magento_customer_data_queue_id': customer_queue and customer_queue.id or False,
                'state': 'draft',
            }
            self.create(customer_queue_line_values)
            self._cr.commit()
            count = count + 1
            if count == 50:
                count = 0
                customer_queue = False
        customer_queue_data.update({'customer_queue': customer_queue, 'count': count, 'total_customer_queues': total_customer_queues})
        return customer_queue_data

    def magento_create_customer_queue(self, magento_instance):
        """
        Creates Imported Magento Customer queue
        :param magento_instance: Instance of Magento
        :return: Magento Customer Data queue object
        """
        customer_queue_vals = {
            'magento_instance_id': magento_instance and magento_instance.id or False,
            'state': 'draft',
        }
        customer_queue_data = self.env[MAGENTO_CUSTOMER_DATA_QUEUE_EPT].create(
            customer_queue_vals
        )
        return customer_queue_data

    def auto_import_customer_queue_data(self):
        """
        This method used to process synced magento customer data in batch of 50 queue lines.
        This method is called from cron job.
        """
        customer_queue_ids = []

        magento_import_customer_queue_obj = self.env[MAGENTO_CUSTOMER_DATA_QUEUE_EPT]
        query = """select queue.id from magento_customer_data_queue_line_ept as queue_line
                   inner join magento_customer_data_queue_ept as queue on queue_line.magento_customer_data_queue_id = queue.id
                   where queue_line.state='draft' and queue.is_action_require = 'False' 
                   ORDER BY queue_line.create_date ASC"""
        self._cr.execute(query)
        customer_data_queue_list = self._cr.fetchall()
        for result in customer_data_queue_list:
            customer_queue_ids.append(result[0])
        if customer_queue_ids:
            customer_queues = magento_import_customer_queue_obj.browse(list(set(customer_queue_ids)))
            self.process_customer_queue_and_post_message(customer_queues)
        return True

    def process_customer_queue_and_post_message(self, customer_queues):
        """
        This method is used to post a message if the queue is process more than 3 times otherwise
        it calls the child method to process the order queue line.
        :param customer_queues: Magento import customer queue object
        """

        start = time.time()
        customer_queue_process_cron_time = customer_queues.magento_instance_id.get_magento_cron_execution_time(
            "odoo_magento2_ept.magento_ir_cron_to_process_customer_queue_data")
        for customer_queue in customer_queues:
            customer_queue_lines = customer_queue.customer_queue_line_ids
            # For counting the queue crashes for the queue.
            customer_queue.queue_process_count += 1
            if customer_queue.queue_process_count > 3:
                customer_queue.is_action_require = True
                note = "<p>Attention %s queue is processed 3 times you need to process it manually.</p>" % customer_queue.name
                customer_queue.message_post(body=note)
                return True
            self._cr.commit()
            customer_queue_lines.process_import_customer_queue_data()
            if time.time() - start > customer_queue_process_cron_time - 60:
                return True
        return True

    def process_import_customer_queue_data(self):
        """
        This method processes order queue lines.
        """
        partner_obj = self.env['res.partner']
        country_dict = {}
        state_dict = {}
        customer_dict = {}
        customer_queue = self.magento_customer_data_queue_id
        queue_id = self.magento_customer_data_queue_id
        customer_total_queue = queue_id.customer_queue_line_total_record
        if queue_id:
            log_book_id = self.create_update_magento_customer_queue_log(queue_id)
            self.env.cr.execute(
                """update magento_customer_data_queue_ept set is_process_queue = False 
                where is_process_queue = True and id = %s""" % queue_id.id)
            self._cr.commit()
            for customer_queue_line in self:
                customer_dict, country_dict, state_dict = partner_obj.import_specific_customer(
                    customer_queue_line, country_dict, state_dict, customer_dict)
                queue_id.is_process_queue = False
            if not log_book_id.log_lines:
                log_book_id.sudo().unlink()
            if log_book_id and log_book_id.log_lines:
                queue_id.customer_common_log_book_id = log_book_id
                queue_common_log_book_id = queue_id.customer_common_log_book_id
                if queue_common_log_book_id and not queue_common_log_book_id.log_lines:
                    queue_id.customer_common_log_book_id.sudo().unlink()
        return True

    def create_update_magento_customer_queue_log(self, queue_id):
        """
        Log book record exit for the queue, then use that existing
        Or else create new log record for that queue.
        :param queue_id:
        :return: log book record
        """
        if queue_id.customer_common_log_book_id:
            log_book_id = queue_id.customer_common_log_book_id
        else:
            model_id = self.env['common.log.lines.ept'].get_model_id('res.partner')
            log_book_id = self.env["common.log.book.ept"].create({
                'type': 'import',
                'module': 'magento_ept',
                'model_id': model_id,
                'res_id': queue_id.id,
                'magento_instance_id': queue_id.magento_instance_id.id
            })
        return log_book_id
