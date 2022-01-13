# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for Export shipment information.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req
STOCK_PICKING = 'stock.picking'


class StockPicking(models.Model):
    """
    Describes methods for Export shipment information.
    """
    _inherit = STOCK_PICKING
    _description = 'Stock Picking'

    is_magento_picking = fields.Boolean(
        string='Magento Picking?',
        help="If checked, It is Magento Picking"
    )
    related_backorder_ids = fields.One2many(
        comodel_name=STOCK_PICKING,
        inverse_name='backorder_id',
        string="Related backorders",
        help="This field relocates related backorders"
    )

    magento_website_id = fields.Many2one(
        compute="_compute_set_magento_info",
        comodel_name="magento.website",
        readonly=True,
        string="Website",
        help="Magento Websites"
    )
    storeview_id = fields.Many2one(
        compute="_compute_set_magento_info",
        comodel_name="magento.storeview",
        readonly=True,
        string="Storeview",
        help="Magento Store Views"
    )
    is_exported_to_magento = fields.Boolean(
        string="Exported to Magento?",
        help="If checked, Picking is exported to Magento"
    )
    magento_instance_id = fields.Many2one(
        'magento.instance',
        'Magento Instance',
        help="This field relocates magento instance"
    )
    magento_shipping_id = fields.Char(string="Magento Shipping Ids", help="Magento Shipping Ids")
    max_no_of_attempts = fields.Integer(string='Max NO. of attempts', default=0)
    magento_message = fields.Char(string="Picking Message")
    magento_inventory_source = fields.Many2one(
        'magento.inventory.locations', string='Magento Inventory Sources',
        domain="[('magento_instance_id','=',magento_instance_id)]")
    is_msi_enabled = fields.Boolean(related='magento_instance_id.is_multi_warehouse_in_magento')

    def shipment_exportable(self):
        """
        set is_shipment_exportable true or false based on some condition
        :return:
        """
        module_obj = self.env['ir.module.module']
        purchase_module = module_obj.sudo().search([('name', '=', 'purchase'),
                                                    ('state', '=', 'installed')])
        # if (self.location_dest_id.id == self.env.ref('stock.stock_location_customers').id) \
        #         and \
        #         (purchase_module and self.purchase_id and
        #          self.sale_id.magento_instance_id.is_export_dropship_picking)\
        #         or (not purchase_module and self.sale_id):
            # check purchase module is installed or not and it it's installed then
            # picking is purchase's picking & is_export_dropship_picking is True
            # or
            # purchase is not installed and that picking is SO's picking
        if (self.location_dest_id.id == self.env.ref('stock.stock_location_customers').id) \
                and \
                ((purchase_module and not self.purchase_id and self.sale_id) or (not purchase_module and self.sale_id)):
            self.is_shipment_exportable = True
        else:
            self.is_shipment_exportable = False

    is_shipment_exportable = fields.Boolean(string="Is Shipment exportable", compute='shipment_exportable',
                                                store=False)

    def _compute_set_magento_info(self):
        """
        Computes Magento Information
        :return:
        """
        for record in self:
            if record.sale_id.magento_order_id:
                record.magento_website_id = record.sale_id.magento_website_id
                record.storeview_id = record.sale_id.store_id
            else:
                record.magento_website_id = False
                record.storeview_id = False

    def create_job_log_book(self, instance):
        """
        create job record
        :param instance: magento instance
        :return: job
        """
        common_log_book_obj = self.env['common.log.book.ept']
        common_log_lines_obj = self.env['common.log.lines.ept']
        model_id = common_log_lines_obj.get_model_id(STOCK_PICKING)
        job = common_log_book_obj.create({
            'type': 'import',
            'module': 'magento_ept',
            'model_id': model_id,
            'res_id': self.id,
            'magento_instance_id': instance
        })
        return job

    def export_ship_in_magento(self, picking, job):
        """
        picking wise export shipment details.
        :param picking: stock picking record
        :param job: job
        :return: job
        """
        order_item = []
        for move in picking.move_lines:
            if move.sale_line_id and move.sale_line_id.magento_sale_order_line_ref:
                order_item_id = move.sale_line_id.magento_sale_order_line_ref
                qty_delivered = move.quantity_done
                # only ship those qty with is done in picking. Not for whole order qty done
                order_item.append({
                    'orderItemId': order_item_id,
                    'qty': qty_delivered
                })
        track_numbers = self.add_tracking_number(picking)
        values = {
            "items": order_item,
            "tracks": track_numbers or []
        }
        if self.is_msi_enabled and self.magento_inventory_source:
            values.update({
                "arguments": {
                    "extension_attributes": {
                        "source_code": self.magento_inventory_source.magento_location_code
                    }
                }
            })
        try:
            api_url = '/V1/order/{}/ship/'.format(picking.sale_id.magento_order_id)
            response = req(picking.magento_instance_id, api_url, 'POST', values)
        except Exception:
            order_name = picking.sale_id.name
            picking.write({
                "max_no_of_attempts": picking.max_no_of_attempts + 1,
                "magento_message": _("The request could not be satisfied while export this Shipment."
                                     "\nPlease check Process log %s") % (job.name)
            })
            message = _("The request could not be satisfied and shipment couldn't be created in Magento for "
                        "Sale Order : %s & Picking : %s due to any of the following reasons.\n"
                        "1. A picking can't be created when an order has a status of 'On Hold/Canceled/Closed'\n"
                        "2. A picking can't be created without products. Add products and try again.\n"
                        "3. The shipment information has not been exported due to either missing carrier or tracking number details.\n"
                        "4. In case you are using Magento multi-inventory sources, "
                        "ensure that you have selected the appropriate warehouse location for the shipment in Odoo. "
                        "The warehouse location must be listed as one of the inventory sources set up in Magento for the product. "
                        "Please go to Magento2 Odoo Connector > Configuration > Magento Inventory location > Select Magento location name > set Export Shipment location\n"
                        "The order does not allow an shipment to be created") % (order_name, picking.name)
            job.write({
                'log_lines': [(0, 0, {
                    'message': message,
                    'order_ref': order_name,
                })]
            })
            return job
        if response:
            picking.write({
                'magento_shipping_id': int(response),
                'is_exported_to_magento': True
            })
        return job

    def export_shipment_to_magento(self, magento_instance):
        """
        This method is used for exporting shipments from odoo to magento.
        :param magento_instance: Instance of Magento
        :return:
        """
        pickings = self.search([
            ('is_exported_to_magento', '=', False),
            ('state', 'in', ['done']),
            ('magento_instance_id', 'in', magento_instance.ids),
            ('location_dest_id', '=', self.env.ref('stock.stock_location_customers').id),
            ('max_no_of_attempts', '<=', 3)
        ])
        job = self.create_job_log_book(magento_instance.id)
        module_obj = self.env['ir.module.module']
        purchase_module = module_obj.sudo().search([('name', '=', 'purchase'),
                                               ('state', '=', 'installed')])
        for picking in pickings:
            # if purchase_module and picking.purchase_id and picking.magento_instance_id and \
            #         not picking.magento_instance_id.is_export_dropship_picking:
            if purchase_module and picking.purchase_id:
                # check purchase module is installed or not
                # if installed then picking is purchase's picking
                # and is_export_dropship_picking set  as False then skip that picking to export in Magento
                continue
            job = self.export_ship_in_magento(picking, job)
        if not job.log_lines:
            job.sudo().unlink()

    @staticmethod
    def add_tracking_number(picking):
        """
        Add new Tracking Number for Picking.
        :param picking: Stock Picking Object
        :return:
        """
        if picking.carrier_id and not picking.carrier_id.magento_carrier_code:
            message = ('You are trying to "Export Shipment Information" '
                            "\nBut Still, you didn't set the Magento "
                            "Carrier Code for '%s' Delivery Method") % (str(picking.carrier_id.name))
            raise UserError(message)

        tracking_numbers = []
        package_ids = picking.package_ids
        magento_carrier_code = picking.carrier_id.magento_carrier_code or ''
        magento_carrier_title = picking.carrier_id.magento_carrier.magento_carrier_title or ''
        if package_ids:
            for package in package_ids:
                trackno = {'carrierCode': magento_carrier_code,
                           'title': magento_carrier_title,
                           'trackNumber': package.tracking_no if package.tracking_no else picking.carrier_tracking_ref or ''}
                tracking_numbers.append(trackno)
        else:
            if picking.carrier_tracking_ref:
                trackno = {'carrierCode': magento_carrier_code,
                           'title': magento_carrier_title,
                           'trackNumber': picking.carrier_tracking_ref or ''}
                tracking_numbers.append(trackno)
        return tracking_numbers

    def export_shipment_in_magento(self):
        """
        Allow Single picking to export from the picking form view
        :return:
        """
        job = self.create_job_log_book(self.magento_instance_id.id)
        job = self.export_ship_in_magento(self, job)
        if not job.log_lines:
            job.sudo().unlink()
