# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes product import export process.
"""
from odoo import fields, models, api, _
from odoo.exceptions import UserError

MAGENTO_INSTANCE = 'magento.instance'
MAGENTO_PRODUCT_TEMPLATE = 'magento.product.template'
EXPORT_PRODUCT_LOG = 'Export Product Log'
IR_ACTIONS_ACT_WINDOW = 'ir.actions.act_window'
COMMON_LOG_BOOK_EPT = 'common.log.book.ept'
TREE_FORM = 'tree,form'


class MagentoExportProductEpt(models.TransientModel):
    """
    Describes Magento Process for import/ export operations
    """
    _name = 'magento.export.product.ept'
    _description = 'Magento Export Product Ept'

    magento_instance_ids = fields.Many2many(MAGENTO_INSTANCE, string="Instances",
                                            help="This field relocates Magento Instance")
    attribute_set_id = fields.Many2one('magento.attribute.set', string='Attribute Set', help="Magento Attribute Sets")
    magento_is_set_image = fields.Boolean(string="Set Image ?", default=False)
    magento_is_set_price = fields.Boolean(string="Set Price ?", default=False)
    magento_update_price = fields.Boolean(string="Update Price ?", default=False)
    magento_update_image = fields.Boolean(string="Update Image ?", default=False)
    magento_publish = fields.Selection([
        ('publish', 'Publish'), ('unpublish', 'Unpublish')],
        string="Publish In Website ?",
        help="If select publish then Publish the product in website "
             "and If the select unpublish then Unpublish the product from website")
    magento_update_basic_details = fields.Boolean(string="Update Basic Details ?", default=False)
    magento_update_description = fields.Boolean(string="Update Product Description/Short Description ?", default=False)
    description_config_value = fields.Boolean(string="Allow Product Description/Short Description?")

    @api.model
    def default_get(self, field_list):
        """
        based on the global configuration of the sale description set
        the value in description_config_value
        :param field_list:
        :return:
        """
        res = super(MagentoExportProductEpt, self).default_get(field_list)
        global_product_description = self.env["ir.config_parameter"].sudo().get_param(
            "odoo_magento2_ept.set_magento_sales_description")
        res.update({'description_config_value': global_product_description})

        return res

    @api.onchange('attribute_set_id')
    def onchange_attribute_set_id(self):
        """
        Set domain for site ids when change attribute sets.
        """
        magento_product_tmpl_obj = self.env[MAGENTO_PRODUCT_TEMPLATE]
        magento_template_ids = self.env.context.get('active_ids', [])
        if magento_template_ids:
            magento_product_templates = magento_product_tmpl_obj.search([('id', 'in', magento_template_ids)])
            magento_instances = magento_product_templates.magento_instance_id
            attribute_sets = self.env['magento.attribute.set'].search([('instance_id', 'in', magento_instances.ids)])
        return {'domain': {'attribute_set_id': [('id', 'in', attribute_sets.ids)]}}

    def process_export_products_in_magento(self):
        """
        export new product in magento
        :return:
        """
        magento_template_ids = self.env.context.get('active_ids', [])

        if not self.magento_is_set_price and not self.magento_publish and\
                not self.magento_is_set_image and not self.attribute_set_id:
            raise UserError(_("Please select any of the above operation to export product"))

        if not magento_template_ids:
            raise UserError(_("Please select some products to Export to Magento Store."))

        if magento_template_ids and len(magento_template_ids) > 80:
            raise UserError(_("Error:\n- System will not export more then 80 Products at a "
                              "time.\n- Please select only 80 product for export."))

        magento_instance_obj = self.env[MAGENTO_INSTANCE]
        magento_product_tmpl_obj = self.env[MAGENTO_PRODUCT_TEMPLATE]
        instances = magento_instance_obj.search([('active', '=', True)])
        magento_product_templates = magento_product_tmpl_obj.search([
            ('id', 'in', magento_template_ids), ('sync_product_with_magento', '=', False)])

        log = []
        for instance in instances:
            magento_templates = self.get_magento_product_template_by_instance(magento_product_templates, instance)
            if not magento_templates:
                continue
            common_log_id = self.magento_create_log_book(instance)
            for magento_tmpl in magento_templates:
                attribute_set_id = self.attribute_set_id if self.attribute_set_id else magento_tmpl.attribute_set_id
                magento_product_tmpl_obj.export_products_in_magento(
                    instance, magento_tmpl, self.magento_is_set_price, self.magento_publish,
                    self.magento_is_set_image, attribute_set_id, common_log_id)

            if common_log_id and not common_log_id.log_lines:
                common_log_id.unlink()
            else:
                log.append(common_log_id.id)
        if log:
            return {
                'name': EXPORT_PRODUCT_LOG,
                'type': IR_ACTIONS_ACT_WINDOW,
                'res_model': COMMON_LOG_BOOK_EPT,
                'view_type': 'form',
                'view_mode': TREE_FORM,
                'domain': [('id', 'in', log)],
            }

        return {
            'effect': {
                'fadeout': 'slow',
                'message': " 'Export Product(s) in Magento' Process Completed Successfully! {}".format(""),
                'img_url': '/web/static/src/img/smile.svg',
                'type': 'rainbow_man',
            }
        }

    def process_update_products_in_magento(self):
        """
        update existing product in magento
        :return:
        """
        update_ids = self.env.context.get('active_ids', [])
        update_img = self.magento_update_image
        update_price = self.magento_update_price
        basic_details = self.magento_update_basic_details
        update_description = self.magento_update_description

        if not update_img and not update_price and not basic_details and not update_description:
            raise UserError(_("Please select any of the above operation to update the product."))

        if not update_ids:
            raise UserError(_("Please select some products to Update in Magento Store."))

        if update_ids and len(update_ids) > 80:
            raise UserError(_("Error:\n- System will not update more then 80 Products at a "
                              "time.\n- Please select only 50 product for update."))

        magento_instance_obj = self.env[MAGENTO_INSTANCE]
        magento_product_tmpl_obj = self.env[MAGENTO_PRODUCT_TEMPLATE]

        instances = magento_instance_obj.search([('active', '=', True)])
        magento_product_templates = magento_product_tmpl_obj.search([('id', 'in', update_ids),
                                                                     ('sync_product_with_magento', '=', True)])

        log = []
        for instance in instances:
            common_log_id = self.magento_create_log_book(instance)
            not_synced_magento_product_templates = magento_product_tmpl_obj.search([
                ('id', 'in', update_ids), ('sync_product_with_magento', '=', False),
                ('magento_instance_id', '=', instance.id)])
            for magento_tmpl in not_synced_magento_product_templates:
                common_log_id.write({
                    'log_lines': [(0, 0, {
                        'message': 'You were trying to update the Product. But still,'
                                   ' this product was not created in Magento. '
                                   'Please Perform the "Export Product In Magento" Operation first for this Product.',
                        'default_code': magento_tmpl.magento_sku
                    })]
                })
            magento_templates = self.get_magento_product_template_by_instance(magento_product_templates, instance)
            if magento_templates:
                magento_product_tmpl_obj.update_products_in_magento_ept(instance, magento_templates,
                                                                        update_img, update_price, basic_details,
                                                                        common_log_id, update_description)

            if common_log_id and not common_log_id.log_lines:
                common_log_id.unlink()
            else:
                log.append(common_log_id.id)

        if log:
            return {
                'name': EXPORT_PRODUCT_LOG,
                'type': IR_ACTIONS_ACT_WINDOW,
                'res_model': COMMON_LOG_BOOK_EPT,
                'view_type': 'form',
                'view_mode': TREE_FORM,
                'domain': [('id', 'in', log)],
            }

        return {
            'effect': {
                'fadeout': 'slow',
                'message': " 'Export Product(s) in Magento' Process Completed Successfully! {}".format(""),
                'img_url': '/web/static/src/img/smile.svg',
                'type': 'rainbow_man',
            }
        }

    def export_stock_in_magento_ept(self):
        """
        Update Product stock in magento
        :return:
        """
        stock_update_ids = self.env.context.get('active_ids', [])
        magento_product_obj = self.env['magento.product.product']
        if not stock_update_ids:
            raise UserError(_("Please select some products to Update Stock in Magento Store."))

        if stock_update_ids and len(stock_update_ids) > 80:
            raise UserError(_("Error:\n- System will not update stock more then 80 Products at a "
                              "time.\n- Please select only 80 product for update stock."))

        magento_instance_obj = self.env[MAGENTO_INSTANCE]
        instances = magento_instance_obj.search([('active', '=', True)])
        magento_product_tmpl_obj = self.env[MAGENTO_PRODUCT_TEMPLATE]
        log = []
        magento_product_templates = magento_product_tmpl_obj.search([('id', 'in', stock_update_ids),
                                                                     ('sync_product_with_magento', '=', True)])

        magento_product_product = self.env['magento.product.product']
        prod_obj = self.env['product.product']
        magento_inventory_locations_obj = self.env['magento.inventory.locations']
        for instance in instances:
            stock_data = []
            common_log_id = self.magento_create_log_book(instance)
            not_synced_magento_product_templates = magento_product_tmpl_obj.search([
                ('id', 'in', stock_update_ids), ('sync_product_with_magento', '=', False),
                ('magento_instance_id', '=', instance.id)])
            for magento_tmpl in not_synced_magento_product_templates:
                common_log_id.write({
                    'log_lines': [(0, 0, {
                        'message': 'You were trying to update the Product Stock. But still,'
                                   ' this product was not created in Magento. '
                                   'Please Perform the "Export Product In Magento" Operation first for this Product.',
                        'default_code': magento_tmpl.magento_sku
                    })]
                })
            magento_templates = self.get_magento_product_template_by_instance(magento_product_templates, instance)
            if magento_templates:
                product_product_ids = magento_templates.magento_product_ids.mapped('odoo_product_id')

                if instance.magento_version in ['2.1', '2.2'] or not instance.is_multi_warehouse_in_magento:
                    if not instance.warehouse_ids:
                        raise UserError(_("Please select Export Stock Warehouse for %s instance.") % instance.name)
                    export_product_stock = magento_product_product. \
                        get_magento_product_stock_ept(instance, product_product_ids.ids,
                                                      prod_obj, instance.warehouse_ids)
                    if export_product_stock:
                        magento_product_tmpl_obj.export_stock_in_magento(export_product_stock, instance, common_log_id, [])
                else:
                    inventory_locations = magento_inventory_locations_obj.search([
                        ('magento_instance_id', '=', instance.id), ('active', '=', True)
                    ])
                    for magento_location in inventory_locations:
                        export_stock_locations = magento_location.mapped('export_stock_warehouse_ids')
                        if not export_stock_locations:
                            raise UserError(_("Please select Export Stock Warehouse "
                                              "for %s location.") % magento_location.name)
                        export_product_stock = magento_product_product. \
                            get_magento_product_stock_ept(instance,
                                                          product_product_ids.ids,
                                                          prod_obj,
                                                          export_stock_locations)
                        if export_product_stock:
                            stock_data = magento_product_tmpl_obj. \
                                export_stock_in_magento(export_product_stock, instance,
                                                        common_log_id, stock_data,
                                                        source_code=magento_location.magento_location_code,
                                                        msi=True)
                    if stock_data:
                        data = {'sourceItems': stock_data}
                        api_url = "/V1/inventory/source-items"
                        magento_product_obj.call_export_product_stock_api(instance, api_url, data, common_log_id,
                                                                          'POST')
            if common_log_id and not common_log_id.log_lines:
                common_log_id.unlink()
            else:
                log.append(common_log_id.id)
        if log:
            return {
                'name': EXPORT_PRODUCT_LOG,
                'type': IR_ACTIONS_ACT_WINDOW,
                'res_model': COMMON_LOG_BOOK_EPT,
                'view_type': 'form',
                'view_mode': TREE_FORM,
                'domain': [('id', 'in', log)],
            }

        return {
            'effect': {
                'fadeout': 'slow',
                'message': " 'Update Product stocks(s) in Magento' Process Completed Successfully! {}".format(""),
                'img_url': '/web/static/src/img/smile.svg',
                'type': 'rainbow_man',
            }
        }

    def magento_create_log_book(self, instance):
        """
        Create Log Book record for export product template.
        :param instance: Magento Instance object
        :return: log book record
        """
        model_id = self.env['common.log.lines.ept'].get_model_id(MAGENTO_PRODUCT_TEMPLATE)
        log_book_id = self.env["common.log.book.ept"].create({
            'type': 'export',
            'module': 'magento_ept',
            'model_id': model_id,
            'magento_instance_id': instance.id
        })
        return log_book_id

    @staticmethod
    def get_magento_product_template_by_instance(magento_product_templates, instance):
        """
        Search
        :param magento_product_templates:
        :param instance:
        :return:
        """
        return magento_product_templates.filtered(lambda x: x.magento_instance_id == instance)
