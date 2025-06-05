#!/usr/bin/env python3
"""
ActiveCampaign Webhook Handler for Render Deployment
Includes automatic database initialization and error handling
"""

import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from flask import Flask, request, jsonify
import hashlib
import hmac
from functools import wraps

# Configure logging with immediate flushing
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)

# Force logging to flush immediately
for handler in logging.root.handlers:
    handler.flush = lambda: None
logger = logging.getLogger(__name__)

class RenderWebhookHandler:
    """Webhook handler optimized for Render deployment"""
    
    def __init__(self, db_path: str = "webhook_data.db", webhook_secret: str = None):
        self.db_path = db_path
        self.webhook_secret = webhook_secret or "CorvusSolutions"  # Default secret
        self._init_database()
        
    def _init_database(self):
        """Initialize database with required tables"""
        try:
            # Ensure directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
                
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create webhook_logs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webhook_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT,
                        contact_email TEXT,
                        webhook_data TEXT,
                        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed BOOLEAN DEFAULT FALSE
                    )
                """)
                
                # Create contact_updates table for tracking changes
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS contact_updates (
                        update_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT NOT NULL,
                        field_name TEXT,
                        old_value TEXT,
                        new_value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                logger.info(f"Database initialized at {self.db_path}")
                
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def verify_webhook(self, request_data: bytes, signature: str) -> bool:
        """Verify webhook signature from ActiveCampaign"""
        if not self.webhook_secret:
            logger.warning("No webhook secret configured - skipping verification")
            return True
            
        expected_signature = hmac.new(
            self.webhook_secret.encode('utf-8'),
            request_data,
            hashlib.sha256
        ).hexdigest()
        
        is_valid = hmac.compare_digest(signature, expected_signature)
        if not is_valid:
            logger.warning("Invalid webhook signature received")
        return is_valid
    
    def process_webhook(self, webhook_data: Dict) -> Dict:
        """Process incoming webhook data"""
        
        event_type = webhook_data.get('type', 'unknown')
        contact_data = webhook_data.get('contact', {})
        
        result = {
            'status': 'success',
            'actions_taken': [],
            'event_type': event_type,
            'timestamp': datetime.now().isoformat()
        }
        
        # Extract contact information
        email = contact_data.get('email')
        if not email:
            # Try alternate locations for email (including ActiveCampaign form format)
            email = (webhook_data.get('email') or 
                    webhook_data.get('contact_email') or 
                    webhook_data.get('contact[email]'))
        
        if email:
            result['contact_email'] = email
            
            # Log the webhook
            log_id = self._log_webhook_event(event_type, email, webhook_data)
            result['actions_taken'].append(f'Logged {event_type} for {email} (ID: {log_id})')
            
            # Process specific event types
            if event_type == 'contact_update':
                self._process_contact_update(email, contact_data)
                result['actions_taken'].append('Processed contact update')
            elif event_type == 'contact_add':
                result['actions_taken'].append('New contact added')
            elif event_type == 'contact_tag_added':
                tag = webhook_data.get('tag', {}).get('tag', 'unknown')
                result['actions_taken'].append(f'Tag added: {tag}')
        else:
            logger.warning(f"No email found in webhook data: {json.dumps(webhook_data)[:200]}")
            result['status'] = 'warning'
            result['message'] = 'No email address found in webhook data'
        
        return result
    
    def _log_webhook_event(self, event_type: str, email: str, data: Dict) -> int:
        """Log webhook events to database"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO webhook_logs (event_type, contact_email, webhook_data)
                    VALUES (?, ?, ?)
                """, (event_type, email, json.dumps(data)))
                
                log_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Logged webhook: {event_type} for {email} (ID: {log_id})")
                return log_id
                
        except Exception as e:
            logger.error(f"Failed to log webhook: {e}")
            raise
    
    def _process_contact_update(self, email: str, contact_data: Dict):
        """Process contact update events"""
        try:
            # Track field changes if we have previous data
            # For now, just log that an update occurred
            logger.info(f"Contact update for {email}: {json.dumps(contact_data)[:200]}")
        except Exception as e:
            logger.error(f"Error processing contact update: {e}")


# Flask application
app = Flask(__name__)

# Initialize handler with environment variable for secret
webhook_handler = RenderWebhookHandler(
    webhook_secret=os.environ.get('AC_WEBHOOK_SECRET', 'CorvusSolutions')
)


def require_webhook_auth(f):
    """Decorator to verify webhook signatures"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip auth for health checks
        if request.endpoint == 'health_check':
            return f(*args, **kwargs)
            
        signature = request.headers.get('X-ActiveCampaign-Signature')
        if signature and not webhook_handler.verify_webhook(request.data, signature):
            logger.warning(f"Rejected webhook with invalid signature")
            return jsonify({'error': 'Invalid signature'}), 403
        return f(*args, **kwargs)
    return decorated_function


@app.route('/webhook/activecampaign', methods=['POST'])
@require_webhook_auth
def handle_webhook():
    """Main webhook endpoint"""
    
    try:
        # Log raw request for debugging
        logger.info(f"Received webhook - Headers: {dict(request.headers)}")
        logger.info(f"Content-Type: {request.content_type}")
        
        # ActiveCampaign sends form data, not JSON
        if request.content_type and 'application/x-www-form-urlencoded' in request.content_type:
            # Parse form data
            webhook_data = {}
            for key, value in request.form.items():
                try:
                    # Try to parse as JSON if it looks like JSON
                    if value.startswith('{') and value.endswith('}'):
                        webhook_data[key] = json.loads(value)
                    else:
                        webhook_data[key] = value
                except json.JSONDecodeError:
                    webhook_data[key] = value
                    
            logger.info(f"Parsed form data keys: {list(webhook_data.keys())}")
            
        elif request.content_type and 'application/json' in request.content_type:
            # Handle JSON data
            webhook_data = request.get_json()
        else:
            # Try both methods
            webhook_data = request.get_json(silent=True) or dict(request.form)
        
        if not webhook_data:
            logger.error("No data in webhook request")
            logger.info(f"Raw form data: {dict(request.form)}")
            logger.info(f"Raw data: {request.data[:500]}")
            return jsonify({'error': 'No data provided'}), 400
        
        logger.info(f"Processing webhook data: {str(webhook_data)[:500]}")
        
        # Process the webhook
        result = webhook_handler.process_webhook(webhook_data)
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        logger.info(f"Request form data: {dict(request.form)}")
        logger.info(f"Request data: {request.data[:200]}")
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@app.route('/webhook/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    try:
        # Test database connection
        with sqlite3.connect(webhook_handler.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM webhook_logs")
            log_count = cursor.fetchone()[0]
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'ActiveCampaign Webhook',
            'version': '2.0',
            'database': 'connected',
            'total_logs': log_count
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 503


@app.route('/webhook/test', methods=['GET', 'POST'])
def test_webhook():
    """Test endpoint for development"""
    
    # Log that test endpoint was hit
    logger.info(f"=== TEST ENDPOINT HIT - Method: {request.method} ===")
    print(f"=== TEST ENDPOINT HIT - Method: {request.method} ===", flush=True)
    
    if request.method == 'GET':
        # For GET requests, return a simple test page
        return jsonify({
            'message': 'Test endpoint is working!',
            'method': 'GET',
            'timestamp': datetime.now().isoformat(),
            'instructions': 'Send POST request with JSON data to test webhook processing'
        })
    
    # For POST requests, process webhook data
    test_data = request.get_json() or {
        'type': 'contact_update',
        'contact': {
            'email': 'test@example.com',
            'firstName': 'Test',
            'lastName': 'User',
            'phone': '555-1234'
        }
    }
    
    logger.info(f"Test data: {json.dumps(test_data)}")
    print(f"Test data: {json.dumps(test_data)}", flush=True)
    
    result = webhook_handler.process_webhook(test_data)
    
    logger.info(f"Test result: {json.dumps(result)}")
    print(f"Test result: {json.dumps(result)}", flush=True)
    
    return jsonify(result)


@app.route('/webhook/logs', methods=['GET'])
def view_logs():
    """View recent webhook logs (protected endpoint)"""
    
    # Simple auth check - you should implement proper authentication
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {os.environ.get('ADMIN_TOKEN', 'admin123')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        limit = int(request.args.get('limit', 20))
        
        with sqlite3.connect(webhook_handler.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT log_id, event_type, contact_email, received_at 
                FROM webhook_logs 
                ORDER BY received_at DESC 
                LIMIT ?
            """, (limit,))
            
            logs = []
            for row in cursor.fetchall():
                logs.append({
                    'id': row[0],
                    'event_type': row[1],
                    'email': row[2],
                    'timestamp': row[3]
                })
        
        return jsonify({
            'logs': logs,
            'count': len(logs)
        })
        
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return jsonify({'error': 'Failed to fetch logs'}), 500


@app.route('/', methods=['GET'])
def root():
    """Root endpoint with service info"""
    return jsonify({
        'service': 'ActiveCampaign Webhook Handler',
        'status': 'running',
        'version': '2.0',
        'endpoints': {
            'webhook': '/webhook/activecampaign',
            'health': '/webhook/health',
            'test': '/webhook/test',
            'logs': '/webhook/logs (requires auth)'
        },
        'deployment': 'Render'
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # Production mode for Render
    app.run(host="0.0.0.0", port=port, debug=False)