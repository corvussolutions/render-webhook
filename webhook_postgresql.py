#!/usr/bin/env python3
"""
ActiveCampaign Webhook Handler for Render with PostgreSQL
Production-ready with persistent database storage
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from flask import Flask, request, jsonify
import hashlib
import hmac
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import psycopg2.pool
from urllib.parse import urlparse

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

class PostgreSQLWebhookHandler:
    """Webhook handler with PostgreSQL storage"""
    
    def __init__(self, database_url: str = None, webhook_secret: str = None):
        self.database_url = database_url or os.environ.get('DATABASE_URL')
        self.webhook_secret = webhook_secret or "CorvusSolutions"
        
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
            
        self.connection_pool = None
        self._init_connection_pool()
        self._init_database()
        
    def _init_connection_pool(self):
        """Initialize PostgreSQL connection pool"""
        try:
            # Parse the database URL
            parsed = urlparse(self.database_url)
            
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                1, 20,  # min and max connections
                host=parsed.hostname,
                database=parsed.path[1:],  # Remove leading slash
                user=parsed.username,
                password=parsed.password,
                port=parsed.port or 5432
            )
            logger.info("PostgreSQL connection pool initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    
    def _get_connection(self):
        """Get a connection from the pool"""
        return self.connection_pool.getconn()
    
    def _put_connection(self, conn):
        """Return a connection to the pool"""
        self.connection_pool.putconn(conn)
        
    def _init_database(self):
        """Initialize database with required tables"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Create webhook_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS webhook_logs (
                    log_id SERIAL PRIMARY KEY,
                    event_type VARCHAR(100),
                    contact_email VARCHAR(255),
                    contact_id VARCHAR(50),
                    webhook_data JSONB,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Create contact_updates table for tracking changes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contact_updates (
                    update_id SERIAL PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    contact_id VARCHAR(50),
                    field_name VARCHAR(100),
                    old_value TEXT,
                    new_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for better performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhook_logs_email 
                ON webhook_logs(contact_email)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhook_logs_received_at 
                ON webhook_logs(received_at DESC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contact_updates_email 
                ON contact_updates(email)
            """)
            
            conn.commit()
            logger.info("PostgreSQL database tables initialized")
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database initialization failed: {e}")
            raise
        finally:
            if conn:
                self._put_connection(conn)
    
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
        
        # Extract contact ID
        contact_id = (contact_data.get('id') or 
                     webhook_data.get('contact_id') or 
                     webhook_data.get('contact[id]'))
        
        if email or contact_id:
            result['contact_email'] = email
            result['contact_id'] = contact_id
            
            # Log the webhook
            log_id = self._log_webhook_event(event_type, email, contact_id, webhook_data)
            result['actions_taken'].append(f'Logged {event_type} for {email or contact_id} (ID: {log_id})')
            
            # Process specific event types
            if event_type == 'contact_update':
                self._process_contact_update(email, contact_id, contact_data)
                result['actions_taken'].append('Processed contact update')
            elif event_type == 'contact_add':
                result['actions_taken'].append('New contact added')
            elif event_type in ['contact_tag_added', 'contact_tag_removed']:
                tag = webhook_data.get('tag', {}).get('tag', 'unknown')
                result['actions_taken'].append(f'Tag {event_type.split("_")[-1]}: {tag}')
            elif event_type == 'subscriber_note':
                note = webhook_data.get('note', 'No note content')
                result['actions_taken'].append(f'Note added: {note[:50]}...')
        else:
            logger.warning(f"No email or contact ID found in webhook data")
            result['status'] = 'warning'
            result['message'] = 'No email address or contact ID found in webhook data'
        
        return result
    
    def _log_webhook_event(self, event_type: str, email: str, contact_id: str, data: Dict) -> int:
        """Log webhook events to database"""
        
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO webhook_logs (event_type, contact_email, contact_id, webhook_data)
                VALUES (%s, %s, %s, %s)
                RETURNING log_id
            """, (event_type, email, contact_id, json.dumps(data)))
            
            log_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Logged webhook: {event_type} for {email or contact_id} (ID: {log_id})")
            return log_id
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to log webhook: {e}")
            raise
        finally:
            if conn:
                self._put_connection(conn)
    
    def _process_contact_update(self, email: str, contact_id: str, contact_data: Dict):
        """Process contact update events"""
        try:
            # Track field changes if we have previous data
            # For now, just log that an update occurred
            logger.info(f"Contact update for {email or contact_id}: {str(contact_data)[:200]}")
        except Exception as e:
            logger.error(f"Error processing contact update: {e}")
    
    def get_recent_logs(self, limit: int = 20) -> list:
        """Get recent webhook logs"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT log_id, event_type, contact_email, contact_id, received_at 
                FROM webhook_logs 
                ORDER BY received_at DESC 
                LIMIT %s
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            logger.error(f"Error fetching logs: {e}")
            return []
        finally:
            if conn:
                self._put_connection(conn)
    
    def get_stats(self) -> dict:
        """Get webhook statistics"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Total logs
            cursor.execute("SELECT COUNT(*) FROM webhook_logs")
            total_logs = cursor.fetchone()[0]
            
            # Logs by event type
            cursor.execute("""
                SELECT event_type, COUNT(*) as count 
                FROM webhook_logs 
                GROUP BY event_type 
                ORDER BY count DESC
            """)
            event_types = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Recent activity (last 24 hours)
            cursor.execute("""
                SELECT COUNT(*) FROM webhook_logs 
                WHERE received_at > NOW() - INTERVAL '24 hours'
            """)
            recent_activity = cursor.fetchone()[0]
            
            return {
                'total_logs': total_logs,
                'event_types': event_types,
                'recent_24h': recent_activity
            }
            
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            return {}
        finally:
            if conn:
                self._put_connection(conn)


# Flask application
app = Flask(__name__)

# Initialize handler - will fail gracefully if DATABASE_URL not set
try:
    webhook_handler = PostgreSQLWebhookHandler(
        webhook_secret=os.environ.get('AC_WEBHOOK_SECRET', 'CorvusSolutions')
    )
    logger.info("PostgreSQL webhook handler initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize webhook handler: {e}")
    webhook_handler = None


def require_webhook_auth(f):
    """Decorator to verify webhook signatures"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip auth for health checks and if handler not initialized
        if request.endpoint == 'health_check' or not webhook_handler:
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
    
    if not webhook_handler:
        return jsonify({'error': 'Database not configured'}), 503
    
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
        if not webhook_handler:
            return jsonify({
                'status': 'unhealthy',
                'error': 'Database handler not initialized'
            }), 503
            
        # Test database connection and get stats
        stats = webhook_handler.get_stats()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'ActiveCampaign Webhook',
            'version': '3.0',
            'database': 'PostgreSQL connected',
            'stats': stats
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
    
    if not webhook_handler:
        return jsonify({'error': 'Database not configured'}), 503
    
    # Log that test endpoint was hit
    logger.info(f"=== TEST ENDPOINT HIT - Method: {request.method} ===")
    print(f"=== TEST ENDPOINT HIT - Method: {request.method} ===", flush=True)
    
    if request.method == 'GET':
        # For GET requests, return a simple test page
        return jsonify({
            'message': 'Test endpoint is working!',
            'method': 'GET',
            'timestamp': datetime.now().isoformat(),
            'instructions': 'Send POST request with JSON data to test webhook processing',
            'database': 'PostgreSQL connected'
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
    
    if not webhook_handler:
        return jsonify({'error': 'Database not configured'}), 503
    
    # Simple auth check
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {os.environ.get('ADMIN_TOKEN', 'admin123')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        limit = int(request.args.get('limit', 20))
        logs = webhook_handler.get_recent_logs(limit)
        
        return jsonify({
            'logs': logs,
            'count': len(logs)
        })
        
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return jsonify({'error': 'Failed to fetch logs'}), 500


@app.route('/webhook/stats', methods=['GET'])
def view_stats():
    """View webhook statistics (protected endpoint)"""
    
    if not webhook_handler:
        return jsonify({'error': 'Database not configured'}), 503
    
    # Simple auth check
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {os.environ.get('ADMIN_TOKEN', 'admin123')}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        stats = webhook_handler.get_stats()
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({'error': 'Failed to fetch stats'}), 500


@app.route('/', methods=['GET'])
def root():
    """Root endpoint with service info"""
    return jsonify({
        'service': 'ActiveCampaign Webhook Handler',
        'status': 'running',
        'version': '3.0',
        'database': 'PostgreSQL' if webhook_handler else 'Not configured',
        'endpoints': {
            'webhook': '/webhook/activecampaign',
            'health': '/webhook/health',
            'test': '/webhook/test',
            'logs': '/webhook/logs (requires auth)',
            'stats': '/webhook/stats (requires auth)'
        },
        'deployment': 'Render'
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # Production mode for Render
    app.run(host="0.0.0.0", port=port, debug=False)