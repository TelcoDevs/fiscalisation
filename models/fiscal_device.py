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
    
    # Existing fields
    name = fields.Char(string='Device Name', required=True, copy=False, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, tracking=True, copy=False)
    device_id = fields.Integer(string='Device ID', required=True, tracking=True)
    device_serial = fields.Char(string='Device Serial', required=True, tracking=True)
    activation_key = fields.Char(string='Activation Key', required=True, tracking=True)
    base_url = fields.Char(string='API Base URL', default='https://fiscal-demo.telco.co.zw', required=True, tracking=True)
    access_token = fields.Char(string='Access Token', copy=False)
    refresh_token = fields.Char(string='Refresh Token', copy=False)
    token_expiry = fields.Datetime(string='Token Expiry')
    is_day_open = fields.Boolean(string='Day Open', tracking=True)
    fiscal_day_status = fields.Char(string='Fiscal Day Status', readonly=True)
    last_receipt_global_no = fields.Integer(string='Last Global Receipt No', readonly=True)
    last_receipt_no = fields.Integer(string='Last Receipt No', readonly=True)
    fiscal_day_counters = fields.Json(string='Day Counters', readonly=True)
    fiscal_day_no = fields.Char(string='Fiscal Day No', readonly=True, copy=False)
    last_operation = fields.Datetime(string='Last Operation', readonly=True, copy=False)
    last_status_check = fields.Datetime(string='Last Status Check', readonly=True)
    
    # New error tracking fields
    last_error_code = fields.Char(string='Last Error Code', readonly=True)
    last_error_message = fields.Text(string='Last Error Message', readonly=True)
    last_error_status = fields.Integer(string='Last HTTP Status', readonly=True)

    _sql_constraints = [
        ('company_device_unique', 'unique(company_id, device_id)', 'Device ID must be unique per company!'),
    ]
    
    
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
                json={"device_serial": self.device_serial, "activation_key": self.activation_key},
                timeout=TIMEOUT
            )
            response.raise_for_status()
            token_data = response.json()
            
            if not all(k in token_data for k in ('access_token', 'refresh_token', 'expires_in')):
                raise UserError(_('Invalid API response structure'))
            
            self.write({
                'access_token': token_data['access_token'],
                'refresh_token': token_data['refresh_token'],
                'token_expiry': fields.Datetime.to_string(datetime.now() + timedelta(seconds=token_data['expires_in']))
            })
        except Exception as e:
            self._handle_api_error(e, _("Token refresh failed"))
            raise

    def _api_request(self, endpoint, method='POST', payload=None):
        """
        Enhanced API request handler with FDMS error structure support
        """
        self.ensure_one()
        self._refresh_token_if_needed()
        
        try:
            _logger.debug("API Request: %s %s", method, endpoint)
            response = requests.request(
                method,
                f"{self.base_url}{endpoint}",
                headers=self._get_auth_headers(),
                json=payload,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            error_data = self._parse_error_response(e)
            self._log_error_details(error_data, e.response.json() if e.response else None)
            raise UserError(self._format_error_message(error_data)) from e
            
        except requests.exceptions.RequestException as e:
            error_data = {
                'code': 'CONNECTION_FAILED',
                'message': _("Connection error: %s") % str(e),
                'operation_id': '',
                'status': 0
            }
            self._log_error_details(error_data)
            raise UserError(error_data['message']) from e

    def _parse_error_response(self, http_error):
        """Parse FDMS error response structure"""
        error_data = {
            'code': 'UNKNOWN',
            'message': _("Unknown error occurred"),
            'operation_id': '',
            'status': http_error.response.status_code
        }

        try:
            response_data = http_error.response.json()
            # Handle FDMSProblemDetails structure
            error_data.update({
                'code': response_data.get('errorCode', response_data.get('type', 'UNKNOWN')),
                'message': response_data.get('detail', response_data.get('title', error_data['message'])),
                'operation_id': response_data.get('operationID', ''),
                'status': response_data.get('status', http_error.response.status_code)
            })

            # Handle validation errors specifically
            if http_error.response.status_code == 422:
                error_data['message'] = self._parse_validation_errors(response_data)

        except json.JSONDecodeError:
            error_data.update({
                'code': 'INVALID_RESPONSE',
                'message': _("Server returned non-JSON response")
            })

        return error_data

    def _parse_validation_errors(self, response_data):
        """Process 422 validation errors"""
        error_map = {
            'DEVICE_NOT_FOUND': _("Device not registered in FDMS"),
            'INVALID_OPERATION_STATE': _("Device in invalid state for requested operation"),
            'MISSING_REQUIRED_FIELD': _("Required configuration missing in device"),
            'AUTH_TOKEN_EXPIRED': _("Authentication token has expired")
        }

        message_parts = [
            error_map.get(response_data.get('errorCode', ''), _("Validation error occurred")),
            response_data.get('detail', '')
        ]

        if 'errors' in response_data:
            for field, errors in response_data['errors'].items():
                message_parts.append(_("Field %(field)s: %(errors)s") % {
                    'field': field,
                    'errors': ", ".join(errors)
                })

        return "\n".join(message_parts)

    def _log_error_details(self, error_data, response_data=None):
        """Store error details in model fields"""
        self.write({
            'last_error_code': error_data['code'],
            'last_error_message': error_data['message'],
            'last_error_status': error_data['status'],
            'last_status_check': fields.Datetime.now(),
        })

    def _format_error_message(self, error_data):
        """Generate user-friendly error message"""
        return _(
            "FDMS Error [%(code)s]\n"
            "Status: %(status)d\n"
            "Operation ID: %(operation_id)s\n"
            "Message: %(message)s"
        ) % {
            'code': error_data['code'],
            'status': error_data['status'],
            'operation_id': error_data['operation_id'] or _('None provided'),
            'message': error_data['message']
        }

    def _get_auth_headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

    # Existing actions with enhanced error handling
    def action_open_day(self):
        self.ensure_one()
        try:
            response = self._api_request('/api/v1/day/open')
            self.write({
                'fiscal_day_no': str(response['fiscalDayNo']),
                'is_day_open': True,
                'last_operation': fields.Datetime.now()
            })
            return self._show_notification(
                _('Day Opened Successfully'),
                _('New fiscal day number: %s') % response['fiscalDayNo']
            )
        except UserError as e:
            return self._show_notification(_('Day Open Failed'), str(e), is_error=True)
    
    def action_close_day(self):
        self.ensure_one()
        response = self._api_request('/api/v1/day/close')
        self.is_day_open = False
        return self._show_notification(_('Day closed successfully'))

    def action_check_status(self):
        """Manual status check triggered by button"""
        self.ensure_one()
        try:
            # Change method to POST
            response = self._api_request('/api/v1/status', method='POST')  # Changed to POST
            self._process_status_response(response)
            return self._show_notification(
                _('Status Check Successful'),
                _('Device status updated successfully')
            )
        except UserError as e:
            return self._show_notification(
                _('Status Check Failed'),
                str(e),
                is_error=True
            )
            
    @api.model
    def cron_check_device_status(self):
        """Enhanced cron job with error isolation"""
        devices = self.search([('active', '=', True)])
        for device in devices:
            try:
                response = device._api_request('/api/v1/status', method='GET')
                device._process_status_response(response)
                _logger.info("Status check succeeded for %s", device.name)
            except Exception as e:
                _logger.error("Status check failed for %s: %s", device.name, str(e))
                device.message_post(
                    body=_("Automatic status check failed: %s") % str(e),
                    subject=_("Status Check Error"),
                    partner_ids=device.company_id.user_ids.partner_id.ids
                )

    # Helper methods
    def _show_notification(self, title, message, is_error=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'danger' if is_error else 'success',
                'sticky': is_error
            }
        }

    def _process_status_response(self, response):
        """Store status response data"""
        self.write({
            'fiscal_day_status': response.get('fiscalDayStatus'),
            'last_receipt_global_no': response.get('lastReceiptGlobalNo'),
            'last_receipt_no': response.get('lastReceiptNo'),
            'fiscal_day_counters': response.get('fiscalDayCounters', []),
            'last_status_check': fields.Datetime.now(),
            'fiscal_day_no': response.get('lastFiscalDayNo')
        })
    
    def _show_notification(self, title, message, is_error=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'danger' if is_error else 'success',
                'sticky': is_error
            }
        }
    