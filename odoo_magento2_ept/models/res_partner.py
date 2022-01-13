# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for importing magento customers into Odoo.
"""
import json
import logging
from datetime import datetime
from odoo import models, fields, api, _

MAGENTO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
MAGENTO_RES_PARTNER_EPT = 'magento.res.partner.ept'
_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_magento_customer = fields.Boolean(
        string="Is Magento Customer?",
        help="Used for identified that the customer is imported from Magento store.")

    magento_instance_id = fields.Many2one('magento.instance', string='Instance',
                                          help="This field relocates magento instance")
    magento_website_id = fields.Many2one("magento.website", string="Magento Website",
                                         help="Magento Website")
    magento_customer_id = fields.Char(string="Magento Customer", help="Magento Customer Id")
    address_id = fields.Char(string="Address", help="Address Id")
    magento_res_partner_ids = fields.One2many(
        "magento.res.partner.ept",
        inverse_name="partner_id",
        string='Magento Customers',
        help='This relocates Magento Customers'
    )

    @api.model
    def update_partner_in_magento_res_partner(self):
        magento_instances = self.env['magento.instance'].search([])
        if magento_instances:
            for magento_instance in magento_instances:
                magento_partners = self.search([('magento_instance_id', '=', magento_instance.id),
                                                ('is_magento_customer', '=', False)])
                for magento_partner in magento_partners:
                    magento_partner.write({'is_magento_customer': True})
                    if magento_partner.magento_customer_id and magento_partner.magento_customer_id != "Guest Customer":
                        self.search_and_create_magento_res_partner(magento_partner,
                                                                   magento_instance)
        return True

    def search_and_create_magento_res_partner(self, magento_partner, magento_instance):
        magento_partner_obj = self.env[MAGENTO_RES_PARTNER_EPT]
        partner = magento_partner_obj.search([
            ('magento_customer_id', '=', magento_partner.magento_customer_id),
            ('magento_instance_id', '=', magento_instance.id)], limit=1)
        if not partner:
            magento_partner_vals = {
                'magento_instance_id': magento_instance.id,
                'magento_customer_id': magento_partner.magento_customer_id,
                'magento_website_id': magento_partner.magento_website_id.id,
                'address_id': magento_partner.address_id,
                'partner_id': magento_partner.id
            }
            magento_partner_obj.create(magento_partner_vals)

    def import_specific_customer(self, customer_queue_line, country_dict, state_dict,
                                 magento_customer):
        """
        Search Customers with magento customer id, if not found then search from email and website id
        If customer found in Odoo then update magento instance and customer id otherwise create new customer.
        :param customer_queue_line: Customer Queue line
        :param country_dict:  Dictionary of Country
        :param state_dict: Dictionary of State
        :param magento_customer: Magento Customer Dictionary
        :return: magento_customer, country_dict, state_dict
        """
        magento_partner_obj = self.env[MAGENTO_RES_PARTNER_EPT]
        magento_instance = customer_queue_line.magento_instance_id
        customer_response = json.loads(customer_queue_line.customer_data)
        if customer_response.get('vat_id'):
            vat_number = customer_response.get('vat_id')
        else:
            vat_number = customer_response.get('taxvat')
        website_id = magento_instance.magento_website_ids.filtered(
            lambda l: l.magento_website_id == str(customer_response.get('website_id'))).id or False
        partner_name = "%s %s" % (
            customer_response.get('firstname'), customer_response.get('lastname'))
        partner_name = self._remove_special_chars_from_field(partner_name)
        partner_vals = {
            'name': partner_name,
            'email': customer_response.get('email'), 'type': 'contact',
            'vat': vat_number, 'is_magento_customer': True}
        magento_partner = magento_partner_obj.search(
            [('magento_customer_id', '=', customer_response.get('id')),
             ('magento_instance_id', '=', magento_instance.id)], limit=1)
        if not magento_partner:
            partner = self.search([('email', '=', customer_response.get('email'))], limit=1)
            if len(partner) > 1:
                partner = self.search([('parent_id', '=', False)], limit=1)
            if not partner:
                partner = self.create(partner_vals)
            magento_partner_vals = {
                'magento_instance_id': magento_instance.id,
                'magento_customer_id': customer_response.get('id'),
                'magento_website_id': website_id
            }
            magento_partner = partner.create_magento_res_partner_ept(magento_partner_vals)
        magento_customer.update({customer_response.get('id'): magento_partner.partner_id})
        self.create_or_update_child_magento_customer(
            customer_response, state_dict, country_dict, magento_instance, magento_partner)
        customer_queue_line.write({
            'state': 'done', 'processed_at': datetime.now(),
            'magento_customer_id': magento_partner.id,
        })
        return magento_customer, country_dict, state_dict

    def create_magento_res_partner_ept(self, magento_partner_values):
        """
        Create Magento customer in layer
        :param magento_partner_values: dictionary for create magento customer
        :return: magento res partner object
        """
        magento_partner_obj = self.env[MAGENTO_RES_PARTNER_EPT]
        magento_partner_values.update({'partner_id': self.id})
        return magento_partner_obj.create(magento_partner_values)

    def create_or_update_child_magento_customer(self, item, state_dict, country_dict,
                                                magento_instance, magento_customer):
        """
        Create or update child invoice/ shipping partner.
        :param item: item received from Magento
        :param state_dict: Dictionary of state
        :param country_dict: Dictionary of country
        :param magento_instance: Magento Instance
        :param magento_customer: Magento Res partner object
        :return:
        """
        partner_id = magento_customer.partner_id.id
        website_id = magento_instance.magento_website_ids.filtered(
            lambda l: l.magento_website_id == str(item.get('website_id'))).id or False
        partner_arg = ({'is_faulty_customer':False})
        for customer_address in item.get('addresses', []):
            partner_values, magento_partner_values = self.prepare_customer_vals(
                state_dict, country_dict, magento_instance, customer_address, website_id, partner_arg, item=item)
            address_type = self.get_magento_partner_type_ept(customer_address)
            partner_values.update({'type': address_type})
            company = customer_address.get('company')
            _logger.info(json.dumps(partner_values))
            exist_partner = self.find_magento_partner_by_key(partner_values)
            if not exist_partner:
                self.create_non_existing_partner_ept(company, partner_id, partner_values,
                                                     magento_partner_values)
            else:
                self.update_existing_partner_ept(company, exist_partner, partner_values,
                                                 magento_partner_values, magento_customer)
            self._cr.commit()
        return True

    def create_non_existing_partner_ept(self, company, partner_id, partner_values,
                                        magento_partner_values):
        """
        Create New partner if not found in Odoo
        :param company: company id from magento response
        :param partner_id: res.partner()
        :param partner_values: dict()
        :param magento_partner_values: dict()
        :return: Boolean(True)
        """
        partner_values.pop('is_faulty_customer')
        partner_values.update({'parent_id': partner_id})
        if company:
            partner_values.pop('company_name')
        child_partner = self.create(partner_values)
        if company:
            child_partner.write({'company_name': company})
        child_partner.create_magento_res_partner_ept(magento_partner_values)
        return True

    def update_existing_partner_ept(self, company, exist_partner, partner_values,
                                    magento_partner_values, magento_customer):
        """
        Update missing information to existing odoo customer.
        :param company: magento company id
        :param exist_partner: res.partner
        :param partner_values: dict()
        :param magento_partner_values: dict()
        :param magento_customer: Boolean(True/ False)
        :return: Boolean (True)
        """
        if (exist_partner.company_name and company and exist_partner.company_name != company) or (
                not exist_partner.company_name and company):
            partner_values.update({'company_name': company})
            partner_values.pop('is_faulty_customer')
            child_partner = self.with_context(tracking_disable=True).create(partner_values)
            child_partner.create_magento_res_partner_ept(magento_partner_values)
        elif exist_partner.company_name and not company:
            partner_values.pop('is_faulty_customer')
            exist_partner.write(partner_values)
        if exist_partner and (not magento_customer or (
                magento_customer and magento_customer.address_id != magento_partner_values.get(
            'address_id'))):
            exist_partner.create_magento_res_partner_ept(magento_partner_values)
        return True

    @staticmethod
    def get_magento_partner_type_ept(customer_address):
        """
        Find Partner type for as per customer addresses in Magento.
        :param customer_address: dictionary
        :return: string
        """
        default_billing = customer_address.get('default_billing') or False
        default_shipping = customer_address.get('default_shipping') or False
        if default_billing:
            address_type = 'invoice'
        elif default_shipping:
            address_type = 'delivery'
        else:
            address_type = 'other'
        return address_type

    def prepare_customer_vals(self, state_dict, country_dict, magento_instance, customer_address,
                              website_id, partner_args, customer_id=False, item=False, ship=False):
        """
        This method prepares the customer vals
        :param ship:
        :param state_dict: State dictionary
        :param country_dict: Country dictionary
        :param magento_instance: Instance of Magento
        :param customer_address: Dictionary of customer Address
        :param website_id: Magento Website Id
        :param customer_id: Magento Customer Id or False
        :param item: Customer response received from Magento or False.
        :return: customer values dictionary
        """
        country, state = self.get_country_and_state_dict(country_dict, state_dict, customer_address)
        partner_name = "%s %s" % (
            customer_address.get('firstname'), customer_address.get('lastname'))
        partner_name = self._remove_special_chars_from_field(partner_name)
        streets = self.get_street_and_street2(customer_address.get('street'))
        if customer_address.get('vat_id'):
            vat_number = customer_address.get('vat_id')
        else:
            vat_number = customer_address.get('taxvat')
        partner_vals = {
            'name': partner_name,
            'street': streets.get('street', ''),
            'street2': streets.get('street2', ''),
            'city': customer_address.get('city', ''),
            'state_id': state.id if state else False,
            'country_id': country.id if country else False,
            'phone': customer_address.get('telephone', ''),
            'email': item.get('email') if item else customer_address.get('email'),
            'zip': customer_address.get('postcode', ''),
            'lang': magento_instance.lang_id.code,
            'vat': vat_number,
            'is_magento_customer': True,
            'is_faulty_customer':partner_args.get('faulty_customer')
        }
        magento_partner_values = {
            'address_id': customer_address.get('id') if item else customer_address.get('entity_id'),
            'magento_instance_id': magento_instance.id, 'magento_website_id': website_id,
            'magento_customer_id': item.get('id') if not customer_id and item else customer_id
        }
        if customer_address.get('company'):
            partner_vals.update({'company_name': customer_address.get('company')})
        return partner_vals, magento_partner_values

    def _remove_special_chars_from_field(self, partner_value):
        """
        Remove special Chars from end of the partner values
        :param partner_value: partner values
        :return: partner values
        """
        if partner_value[-1:] in "!#$%&()*+,-./:;<=>?@[\]^_`{|}~":
            partner_value = partner_value[:-1]
            self._remove_special_chars_from_field(partner_value)
        return partner_value

    @staticmethod
    def get_magento_customer_name_ept(item, customer_address):
        """
        Get Customer First Name and Last Name from respective dictionaries of addresses.
        :param item: address dict
        :param customer_address:
        :return: Partner Name String
        """
        if item:
            partner_name = "%s %s" % (item.get('firstname'), item.get('lastname'))
        else:
            partner_name = "%s %s" % (
                customer_address.get('firstname'), customer_address.get('lastname'))
        return partner_name

    def get_country_and_state_dict(self, country_dict, state_dict, customer_address):
        """
        Get state and country object from customer address.
        :param country_dict: Dictionary of Countries
        :param state_dict: Dictionary of states.
        :param customer_address: Customer address received from Magento.
        :return: Dictionary of state and country
        """
        country = country_dict.get(customer_address.get('country_id'))
        if not country:
            country = self.get_country(customer_address.get('country_id'))
            country_dict.update({customer_address.get('country_id'): country})
        # Get region_code from customer if region
        if type(customer_address.get('region')) is dict:
            region_code = customer_address.get('region').get('region_code', False)
        else:
            region_code = customer_address.get('region_code', False)
        state = state_dict.get(region_code)
        if not state and country:
            state = self.create_or_update_state_ept(country.code, region_code,
                                                    customer_address.get('postcode', False))
            state_dict.update({region_code: state})
        return country, state

    @staticmethod
    def get_street_and_street2(streets):
        """
        Find Street and street2 from customer address.
        :param streets: Customer address street
        :return: dictionary of street and street2
        """
        result = {}
        if streets:
            if len(streets) == 1:
                result = {'street': streets[0], 'street2': False}
            elif len(streets) == 2:
                result = {'street': streets[0], 'street2': streets[1]}
            elif len(streets) == 3:
                result = {
                    'street': streets[0] + ' , ' + streets[1],
                    'street2': streets[2]
                }
            elif len(streets) == 4:
                result = {
                    'street': streets[0] + ' , ' + streets[1],
                    'street2': streets[2] + ' , ' + streets[3]
                }
        return result

    def find_magento_partner_by_key(self, partner_values):
        """
        Find Partner by specific parameters
        :param partner_values: Partner values dictionary.
        :return: res partner object or False
        """
        key_list = ['name']
        if partner_values.get('street'):
            key_list.append('street')
        if partner_values.get('street2'):
            key_list.append('street2')
        if partner_values.get('city'):
            key_list.append('city')
        if partner_values.get('zip'):
            key_list.append('zip')
        if partner_values.get('phone'):
            key_list.append('phone')
        if partner_values.get('state_id'):
            key_list.append('state_id')
        if partner_values.get('country_id'):
            key_list.append('country_id')
        if partner_values.get('company_name'):
            key_list.append('company_name')
        exist_partner = self._find_partner_ept(partner_values, key_list)
        return exist_partner

    def create_or_update_magento_customer(self, magento_instance, response,
                                          magento_invoice_customer,
                                          magento_delivery_customer, state_dict, country_dict,
                                          skip_order, log_book_id, order_dict_id):
        """
        Create or update Magento Customer when create order into Odoo.
        :param magento_instance: Instance of Magento
        :param response: Response received from Magento
        :param magento_invoice_customer: dictionary of magento invoice customer
        :param magento_delivery_customer: dictionary of magento delivery customer
        :param state_dict: dictionary of state
        :param country_dict: dictionary of country
        :param skip_order: True if any error else False
        :param log_book_id: common log book object
        :param order_dict_id: order data queue id
        :return: partner dictionary and Log line
        """
        magento_partner_obj = self.env[MAGENTO_RES_PARTNER_EPT]
        customer = False
        faulty_customer = False
        customer_id = response.get('customer_id', False)
        magento_store = magento_instance.magento_website_ids.store_view_ids.filtered(
            lambda l: l.magento_storeview_id == str(response.get('store_id')))
        if customer_id:
            customer = magento_partner_obj.search([('magento_customer_id', '=', customer_id),
                                                   ('magento_instance_id', '=',
                                                    magento_instance.id)], limit=1)
        elif not response.get('customer_is_guest') and not customer_id:
            faulty_customer = {'customer_is_guest': True}
            response.update(faulty_customer)
            faulty_customer = True
            # customer = self.search_partner_by_email(response.get('customer_email'))
            # if not customer:
            #     customer = self.create_odoo_partner(response)
        if not customer_id and not response.get('customer_is_guest') and not customer:
            skip_order = True
            message = _("Order '{}' has been skipped to import in Odoo "
                        "because the customer Id does not found. \nThe possible reason is that "
                        "the customer might be deleted from the Magento store for email id: '{}' "
                        "and Customer name: '{} {}'".format(
                response.get('increment_id'), response.get('customer_email'),
                response.get('customer_firstname') or False,
                response.get('customer_lastname') or False))
            log_book_id.add_log_line(message, response.get('increment_id'),
                                     order_dict_id, "magento_order_data_queue_line_id")
            return skip_order, False
        partner_args = {'magento_invoice_customer': magento_invoice_customer,
                        'magento_delivery_customer': magento_delivery_customer,
                        'customer': customer,
                        'faulty_customer': faulty_customer,
                        'magento_instance': magento_instance,
                        'state_dict': state_dict,
                        'country_dict': country_dict,
                        'magento_store': magento_store}
        # If guest customer or customer id not found in existing invoice customers
        # or customer company name is different from response, then create or update invoice customer.
        invoice_partner = self.get_magento_sale_order_invoice_partner(response, partner_args)
        partner_args.update({'invoice_partner': invoice_partner})
        # If guest customer or customer id not found in existing delivery customers
        # or customer company name is different from response, then create or update delivery customer.
        skip_order, shipping_partner = self.get_magento_sale_order_shipping_partner(response,
                                                                                    partner_args,
                                                                                    order_dict_id=order_dict_id,
                                                                                    log_book_id=log_book_id,
                                                                                    skip_order=skip_order)
        if not skip_order:
            shipping_partner = shipping_partner.id if shipping_partner else invoice_partner.id
            partner = customer.partner_id.id if customer else invoice_partner.id
            partner_dict = {'partner': partner, 'invoice_partner': invoice_partner.id,
                            'shipping_partner': shipping_partner}
        else:
            partner_dict = False
        return skip_order, partner_dict

    def create_odoo_partner(response):
        return

    def get_magento_sale_order_shipping_partner(self, response, partner_args, order_dict_id,
                                                log_book_id, skip_order=False):
        """
        Find Shipping Partner from Odoo if not found then create it.
        :param response: dict()
        :param partner_args: dict()
        :param order_dict_id: order data queue id
        :param log_book_id: common log book object
        :param skip_order: True if any error else False
        :return: shipping partner id (integer)
        """
        extension_attributes = response.get('extension_attributes')
        customer_id = response.get('customer_id', False)
        guest_customer = response.get('customer_is_guest')
        shipping_assignments = extension_attributes.get('shipping_assignments')[0]
        ship_address_info = shipping_assignments.get('shipping').get('address') or False
        if not ship_address_info:
            shipping_partner = False
            skip_order = False
            # message = _("Order {} was skipped because shipping details was not set for the customer {} {} email id {}".format(
            #     response.get('increment_id'), response.get('customer_firstname') or False,
            #     response.get('customer_lastname') or False, response.get('customer_email')))
            # log_book_id.add_log_line(message, response.get('increment_id'),
            #                          order_dict_id,"magento_order_data_queue_line_id")
        else:
            ship_company_name = ship_address_info.get('company')
            if guest_customer or (customer_id and customer_id not in partner_args.get(
                    'magento_delivery_customer')) or \
                    (partner_args.get('customer').company_name and ship_company_name and
                     partner_args.get('customer').company_name != ship_company_name):
                # Prepare customer values from partner arguments
                partner_vals, magento_partner_values = self.prepare_customer_vals(
                    partner_args.get('state_dict'), partner_args.get('country_dict'),
                    partner_args.get('magento_instance'), ship_address_info,
                    partner_args.get('magento_store').magento_website_id.id, partner_args,
                    customer_id, ship=True)
                shipping_partner = self.create_or_update_delivery_partner(
                    partner_vals, magento_partner_values,
                    partner_args.get('magento_delivery_customer'),
                    partner_args.get('invoice_partner'), partner_args.get('customer'))
            else:
                shipping_partner = partner_args.get('magento_delivery_customer').get(customer_id)
        return skip_order, shipping_partner

    def get_magento_sale_order_invoice_partner(self, response, partner_args):
        """
        Find Invoice Partner from Odoo if not found then create it.
        :param response: dict()
        :param partner_args: dict()
        :return: invoice partner id (int)
        """
        guest_customer = response.get('customer_is_guest')
        customer_id = response.get('customer_id', False)
        bill_address_info = response.get('billing_address')
        bill_company_name = bill_address_info.get('company')
        if guest_customer or (
                customer_id and customer_id not in partner_args.get('magento_invoice_customer')) \
                or (partner_args.get('customer').partner_id.company_name and bill_company_name and
                    partner_args.get('customer').partner_id.company_name != bill_company_name):
            # Create/Update invoice Partner
            invoice_partner = False
            if bill_address_info:
                partner_vals, magento_partner_values = self.prepare_customer_vals(
                    partner_args.get('state_dict'), partner_args.get('country_dict'),
                    partner_args.get('magento_instance'), bill_address_info,
                    partner_args.get('magento_store').magento_website_id.id, partner_args, customer_id)
                invoice_partner = self.create_or_update_invoice_partner(
                    partner_vals, magento_partner_values, partner_args.get('magento_instance'),
                    partner_args.get('magento_invoice_customer'), partner_args.get('customer'))
        else:
            invoice_partner = partner_args.get('magento_invoice_customer').get(customer_id)
        return invoice_partner

    def create_or_update_invoice_partner(self, partner_vals, magento_partner_vals, instance,
                                         magento_invoice_customer, magento_customer):
        """
        Creates or update customer for particular Magento website.
        :param partner_vals: Dictionary of Partner values
        :param magento_partner_vals: Dictionary of Magento Partner values
        :param instance: instance of Magento
        :param magento_invoice_customer: Magento invoice customer dictionary
        :param magento_customer: magento res partner object
        :return: dictionary of invoice address and delivery address.
        """
        magento_customer_id = magento_partner_vals.get('magento_customer_id')
        company_name = partner_vals.get('company_name')
        partner_vals.update({'type': 'invoice'})
        if not magento_customer_id:
            invoice_partner = self.create_or_update_invoice_partner_for_guest_magento_customer(
                partner_vals, magento_partner_vals,
                company_name)
        else:
            invoice_partner = self.create_or_update_invoice_partner_for_magento_customer(
                partner_vals, magento_partner_vals, company_name, magento_customer)
        if magento_customer_id:
            magento_invoice_customer.update({magento_customer_id: invoice_partner})
        return invoice_partner

    def create_or_update_invoice_partner_for_guest_magento_customer(
            self, partner_vals, magento_partner_vals, company_name):
        """
        Create or update invoice partner for Magento Guest Customers.
        :param partner_vals: Dictionary of Partner values
        :param magento_partner_vals: Dictionary of Magento Partner values
        :param company_name: Company name received from Magento.
        :return: res partner object
        """
        _logger.info(json.dumps(partner_vals))
        exist_partner = self.find_magento_partner_by_key(partner_vals)
        if company_name:
            partner_vals.pop('company_name')
        if not exist_partner:
            if partner_vals.get('is_faulty_customer') == True:
                magento_partner_vals.update({'magento_customer_id': 'Customer Without Id'})
            else:
                magento_partner_vals.update({'magento_customer_id': 'Guest Customer'})
            partner_vals.pop('is_faulty_customer')
            exist_partner = self.create(partner_vals)
            exist_partner.create_magento_res_partner_ept(magento_partner_vals)
            self.magento_update_company_name_in_partner(exist_partner, company_name)
        elif (
                exist_partner.company_name and company_name and exist_partner.company_name != company_name) or (
                not exist_partner.company_name and company_name):
            partner_vals.pop('is_faulty_customer')
            exist_partner = self.with_context(tracking_disable=True).create(partner_vals)
            exist_partner.create_magento_res_partner_ept(magento_partner_vals)
            self.magento_update_company_name_in_partner(exist_partner, company_name)
        elif exist_partner.company_name and not company_name:
            partner_vals.pop('is_faulty_customer')
            exist_partner.write(partner_vals)
        invoice_partner = exist_partner
        return invoice_partner

    def create_or_update_invoice_partner_for_magento_customer(
            self, partner_vals, magento_partner_vals, company_name, magento_customer):
        """
        Create or update invoice type partner for Magento website.
        :param partner_vals: Dictionary of partner values
        :param magento_partner_vals: Dictionary of Magento Partner values
        :param company_name: company name received from Magento
        :param magento_customer: magento res partner object
        :return: res partner object
        """
        _logger.info(json.dumps(partner_vals))
        exist_partner = self.find_magento_partner_by_key(partner_vals)
        if exist_partner:
            if not exist_partner.is_magento_customer:
                exist_partner.write({'is_magento_customer': True})
            if not magento_customer:
                exist_partner.create_magento_res_partner_ept(magento_partner_vals)
            invoice_partner = exist_partner
        else:
            if company_name:
                partner_vals.pop('company_name')
            if magento_customer:
                partner_vals.update({'parent_id': magento_customer.partner_id.id})
            partner_vals.pop('is_faulty_customer')
            invoice_partner = self.with_context(tracking_disable=True).create(partner_vals)
            if not magento_customer or (
                    magento_customer and magento_customer.address_id != magento_partner_vals.get(
                'address_id')):
                invoice_partner.create_magento_res_partner_ept(magento_partner_vals)
            self.magento_update_company_name_in_partner(invoice_partner, company_name)
        return invoice_partner

    @staticmethod
    def magento_update_company_name_in_partner(partner, company_name):
        """
        Update company name in partner if available in response of API.
        :param partner: res.partner()
        :param company_name: string
        :return: boolean
        """
        if company_name:
            partner.write({'company_name': company_name})

    def create_or_update_delivery_partner(
            self, partner_vals, magento_partner_vals, magento_delivery_customer, invoice_partner,
            magento_customer):
        """
        Creates or update customer for particular Magento website.
        :param partner_vals: Dictionary of Partner values
        :param magento_partner_vals: Dictionary of Magento Partner values
        :param magento_delivery_customer: Magento delivery customer dictionary
        :param invoice_partner: invoice partner object
        :param magento_customer: magento res partner object
        :return: res.partner()
        """
        zip_code = partner_vals.get('zip_code')
        delivery = invoice_partner if \
            (invoice_partner and invoice_partner.name == partner_vals.get('name')
             and invoice_partner.street == partner_vals.get('street')
             and (not invoice_partner.street2 or invoice_partner.street2 == partner_vals.get(
                        'street2'))
             and invoice_partner.zip == zip_code and invoice_partner.city == partner_vals.get(
                        'city')
             and invoice_partner.country_id.id == partner_vals.get('country_id')
             and invoice_partner.state_id.id == partner_vals.get('state_id')) else None
        if not delivery:
            _logger.info(json.dumps(partner_vals))
            delivery = self.find_magento_partner_by_key(partner_vals)
            if delivery:
                if not delivery.is_magento_customer:
                    delivery.write({'is_magento_customer': True})
                if not magento_customer:
                    is_customer = self.env['magento.res.partner.ept'].search(
                        [('address_id', '=', magento_partner_vals.get('address_id')), (
                            'magento_instance_id', '=',
                            magento_partner_vals.get('magento_instance_id'))])
                    if is_customer and not magento_partner_vals.get('magento_customer_id'):
                        if partner_vals.get('is_faulty_customer') == True:
                            magento_partner_vals.update({'magento_customer_id': 'Customer Without Id'})
                        else:
                            is_customer.write({'magento_customer_id': 'Guest Customer'})
                    elif not is_customer and not magento_partner_vals.get('magento_customer_id'):
                        if partner_vals.get('is_faulty_customer') == True:
                            magento_partner_vals.update({'magento_customer_id': 'Customer Without Id'})
                        else:
                            magento_partner_vals.update({'magento_customer_id': 'Guest Customer'})
                    partner_vals.pop('is_faulty_customer')
                    delivery.create_magento_res_partner_ept(magento_partner_vals)
            else:
                partner_vals.pop('is_faulty_customer')
                delivery = self.create_delivery_partner(
                    partner_vals, magento_partner_vals, magento_customer, invoice_partner)
        magento_delivery_customer.update({partner_vals.get('magento_customer_id'): delivery})
        return delivery

    def create_delivery_partner(self, partner_vals, magento_partner_vals, magento_customer,
                                invoice_partner):
        """
        Create delivery type partner
        :param partner_vals: Dictionary of partner values
        :param magento_partner_vals: Dictionary of Magento Partner values
        :param magento_customer: magento res partner object
        :param invoice_partner: res partner object
        :return:
        """
        company_name = partner_vals.get('company_name')
        delivery = self.with_context(tracking_disable=True).create({
            'type': 'delivery',
            'parent_id': invoice_partner.id or False,
            **partner_vals,
        })
        if company_name:
            delivery.write({'company_name': company_name})
        if not magento_customer or (
                magento_customer and magento_customer.address_id != magento_partner_vals.get(
            'address_id')):
            delivery.create_magento_res_partner_ept(magento_partner_vals)
        return delivery
