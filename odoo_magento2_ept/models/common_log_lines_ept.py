# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes new fields and methods for common log lines
"""
from odoo import models, fields


class CommonLogLineEpt(models.Model):
    """
    Describes common log book line
    """
    _inherit = "common.log.lines.ept"

    magento_order_data_queue_line_id = fields.Many2one(
        "magento.order.data.queue.line.ept",
        "Order Queue Line"
    )
    import_product_queue_line_id = fields.Many2one(
        "sync.import.magento.product.queue.line",
        "Product Queue Line"
    )
    magento_customer_data_queue_line_id = fields.Many2one(
        "magento.customer.data.queue.line.ept",
        "Customer Queue Line")
