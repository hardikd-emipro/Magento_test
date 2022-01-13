# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req


class MagentoProductCategory(models.Model):
    _name = "magento.product.category"
    _description = 'Magento Product Category'
    _rec_name = 'complete_category_name'

    @api.depends('name', 'magento_parent_id.complete_category_name')
    def _compute_complete_name(self):
        for category in self:
            if category.magento_parent_id:
                category.complete_category_name = '%s / %s' % \
                                                  (category.magento_parent_id.complete_category_name, category.name)
            else:
                category.complete_category_name = category.name

    name = fields.Char("Name")
    instance_id = fields.Many2one(
        'magento.instance',
        'Magento Instance',
        ondelete="cascade",
        help="This field relocates magento instance"
    )
    category_id = fields.Char(
        string="Magento ID",
        help="Magento ID"
    )
    magento_parent_id = fields.Many2one(
        'magento.product.category',
        'Magento Category',
        help="Magento Parent Category ID",
        ondelete='cascade'
    )
    magento_child_ids = fields.One2many(comodel_name='magento.product.category', inverse_name='magento_parent_id',
                                        string='Magento Child Categories')
    is_anchor = fields.Boolean(
        string='Anchor?',
        help="The Is Anchor display setting for categories allows a category to 'inherit'"
             " and display all products from its child categories. When Is Anchor is set to 'Yes',"
             " products assigned to child categories will be combined and displayed in the parent "
             "category along with any products directly assigned to it.",
        default=True
    )
    is_active = fields.Boolean(
        string='Is Active?',
        help="Enable the category by choosing Yes for Is Active field.",
        default=True
    )
    complete_category_name = fields.Char(
        string="Category Name",
        help="Category Name",
        compute="_compute_complete_name"
    )
    active = fields.Boolean(string="Status", default=True)

    def get_all_category(self, instance):
        all_category_data = self.get_all_magento_product_category(instance)
        self.create_magento_category_in_odoo(instance, all_category_data)

    def create_magento_category_in_odoo(self, instance, product_category_data):
        """
        Create the category list in odoo
        :param instance:
        :param product_category_data:
        :return:
        """
        magento_id = product_category_data.get('id')
        parent_id = product_category_data.get('parent_id')
        sub_categories = product_category_data.get('children_data') or []
        magento_category = self.search([('category_id', '=', magento_id),
                                        ('instance_id', '=', instance.id)])
        magento_parent_category = self
        if parent_id != 0:
            magento_parent_category = self.search([('category_id', '=', parent_id),
                                                   ('instance_id', '=', instance.id)])
        if parent_id != 0 and not magento_parent_category and not magento_category:
            parent_category_data = self.get_all_magento_product_category(instance, parent_id)
            new_category = self.create_magento_category_in_odoo(instance, parent_category_data)
            vals = self.magento_category_vals(instance, product_category_data, new_category)
        else:
            if not magento_category:
                vals = self.magento_category_vals(instance, product_category_data,
                                                  magento_parent_category)
        if magento_category:
            new_category = magento_category
        else:
            new_category = self.create(vals)
        for sub_category in sub_categories:
            new_category = self.create_magento_category_in_odoo(instance, sub_category)
        return new_category

    def magento_category_vals(self, instance, data, parent_category):
        """
        Prepare the category vals
        :param instance: Magento Instance
        :param data: Data
        :param parent_category: Parent Category record
        :return:
        """
        category_dict = {}
        category_data = self.get_all_magento_product_category(instance, data.get('id'))
        category_dict.update({
            'category_id' : category_data.get('id'),
            'name' : category_data.get('name'),
            'magento_parent_id' : parent_category.id,
            'is_active': category_data.get('is_active'),
            'instance_id' : instance.id})
        return category_dict

    def get_all_magento_product_category(self, instance, category_id=None):
        """
        Get all the Magento product category using API
        :param instance: Instance record
        :param category_id:
        :return:
        """
        url = '/V1/categories'
        if category_id:
            url = url + "/%s" % category_id
        try:
            category_data = req(instance, url)
        except Exception as error:
            raise UserError(_("Error while requesting Product Category" + str(error)))
        return category_data

