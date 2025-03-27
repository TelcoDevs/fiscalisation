from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
from datetime import datetime, timedelta
import logging
import json

TIMEOUT = 15 

_logger = logging.getLogger(__name__)

class FiscalDevice(models.Model):
    _name = 'fiscal.device'
    _description = 'Fiscal Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Device Name', required=True)
    company_id = fields.Many2one(
        'res.company', 
        required=True, 
        default=lambda self: self.env.company
    )
    device_id = fields.Integer(string='Device ID', required=True)
    device_serial = fields.Char(string='Device Serial', required=True)
    activation_key = fields.Char(string='Activation Key', required=True)
    base_url = fields.Char(
        string='API Base URL', 
        default='https://fiscal-demo.telco.co.zw', 
        required=True
    )
    access_token = fields.Char(string='Access Token', copy=False)
    refresh_token = fields.Char(string='Refresh Token', copy=False)
    token_expiry = fields.Datetime(string='Token Expiry')
    is_day_open = fields.Boolean(string='Day Open', tracking=True)

    _sql_constraints = [
        ('company_device_unique', 
         'unique(company_id, device_id)', 
         'Device ID must be unique per company!'),
    ]

    def _refresh_token_if_needed(self):
        """Check and refresh token if expired"""
        self.ensure_one()
        if not self.token_expiry or datetime.now() > fields.Datetime.from_string(self.token_expiry):
            self._get_new_token()

    def _get_new_token(self):
        """Acquire new JWT token from API"""
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/devices/token",
                json={
                    "device_serial": self.device_serial,
                    "activation_key": self.activation_key
                },
                timeout=10
            )
            _logger.info(f'Token response: {response.json()}')
            response.raise_for_status()
            token_data = response.json()
            
            _logger.info("Token data: %s", token_data)
            
            if not all(k in token_data for k in ('access_token', 'refresh_token', 'expires_in')):
                raise UserError(_('Invalid API response structure'))
            
            self.write({
                'access_token': token_data['access_token'],
                'refresh_token': token_data['refresh_token'],
                'token_expiry': fields.Datetime.to_string(
                    datetime.now() + timedelta(seconds=token_data['expires_in'])
                )
            })
        except requests.exceptions.RequestException as e:
            _logger.error("Authentication failed: %s", str(e))
            raise UserError(_('Authentication failed: %s') % e)
    
    def action_manual_token_refresh(self):
        """Manual token refresh with user feedback"""
        self.ensure_one()
        try:
            self._get_new_token()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Token refreshed successfully'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to refresh token: %s') % e,
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def _cron_refresh_tokens(self):
        """Scheduled token refresh for all active devices"""

        devices = self.search([
            ('device_serial', '!=', False),
            ('activation_key', '!=', False),
            ('base_url', '!=', False)
        ])
        
        success_count = 0
        error_count = 0
        error_messages = []
        
        for device in devices:
            try:
                # Refresh 5 minutes before expiration
                expiration_buffer = fields.Datetime.to_string(
                    datetime.now() + timedelta(minutes=5)
                )
                if not device.token_expiry or device.token_expiry < expiration_buffer:
                    device._get_new_token()
                    success_count += 1
            except Exception as e:
                error_count += 1
                error_msg = f"Device {device.name} ({device.id}) failed: {str(e)}"
                error_messages.append(error_msg)
                _logger.error(error_msg)
                # Send error notification to responsible users
                device.message_post(
                    body=error_msg,
                    subject=_("Token Refresh Failed"),
                    partner_ids=device.company_id.user_ids.partner_id.ids
                )

        # Log summary
        _logger.info(
            "Fiscal token refresh completed: %d successes, %d errors",
            success_count, error_count
        )
        
        # # Send summary email if errors
        # if error_count > 0:
        #     self._send_error_summary(error_messages)
            
        return True
    
    def _api_request(self, endpoint, method='POST', payload=None):
        """
        Handle API requests with automatic token refresh
        Args:
            endpoint (str): API endpoint to call
            method (str): HTTP method (default: POST)
            payload (dict): Request payload
        Returns:
            dict: API response
        Raises:
            UserError: For any communication errors
        """
        self.ensure_one()
        self._refresh_token_if_needed()
        
        try:
            _logger.debug("Making API request to %s%s", self.base_url, endpoint)
            response = requests.request(
                method,
                f"{self.base_url}{endpoint}",
                headers=self._get_auth_headers(),
                json=payload,
                timeout=TIMEOUT
            )
            _logger.info(_(f'Submit Response: {response}'))
            _logger.info(_(f'Submit Response: {response.json()}'))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_details = {
                'code': 'UNKNOWN',
                'message': _("Unknown error occurred"),
                'status': e.response.status_code
            }
            validation_errors = []

            try:
                error_response = e.response.json()
                _logger.error("API Error Details: %s", error_response)

                # Handle array of validation errors
                if isinstance(error_response, list):
                    for err in error_response:
                        field_path = " > ".join(str(part) for part in err.get('loc', []))
                        expected = err.get('ctx', {}).get('expected', '')
                        validation_errors.append(
                            _("Field: %(field)s\nError: %(msg)s\nExpected: %(expected)s\nReceived: %(input)s") % {
                                'field': field_path,
                                'msg': err.get('msg', ''),
                                'expected': expected,
                                'input': err.get('input', '')
                            }
                        )
                    error_details['message'] = "\n\n".join(validation_errors)
                else:
                    # Handle single error object
                    error_details.update({
                        'code': error_response.get('errorCode', 'UNKNOWN'),
                        'message': error_response.get('detail', 
                                error_response.get('title', _("Unknown error occurred")))
                    })

            except json.JSONDecodeError:
                error_details.update({
                    'code': 'INVALID_RESPONSE',
                    'message': _("Server returned invalid response format")
                })

            raise UserError(
                _("Fiscalisation Failed (Code: %(code)s)\n%(message)s") % {
                    'code': error_details['code'],
                    'message': error_details['message']
                }
            ) from e
    
    def _get_auth_headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }
    
    def action_open_day(self):
        self.ensure_one()
        response = self._api_request('/api/v1/day/open')
        return self._show_notification(_('Day opened successfully'))
    
    def action_close_day(self):
        self.ensure_one()
        response = self._api_request('/api/v1/day/close')
        # self.is_day_open = False
        return self._show_notification(_('Day closed successfully'))

    