# -*- coding: utf-8 -*-
"""For Odoo Magento2 Connector Module"""
from odoo import models, api


class AccountTaxCode(models.Model):
    """Inherited account tax model to calculate tax."""
    _inherit = 'account.tax'

    def get_tax_from_rate(self, rate, is_tax_included=False):
        """
        This method,base on rate it find tax in odoo.
        @return : Tax_ids
        @author: Haresh Mori on dated 10-Dec-2018
        """
        tax_ids = self.with_context(active_test=False).search(
            [('price_include', '=', is_tax_included),
             ('type_tax_use', 'in', ['sale']),
             ('amount', '>=', rate - 0.001),
             ('amount', '<=', rate + 0.001)])
        if tax_ids:
            return tax_ids[0]
        # try to find a tax with less precision
        tax_ids = self.with_context(active_test=False).search(
            [('price_include', '=', is_tax_included),
             ('type_tax_use', 'in', ['sale']),
             ('amount', '>=', rate - 0.01),
             ('amount', '<=', rate + 0.01)])
        if tax_ids:
            return tax_ids[0]
        return False
