# ActiveCampaign Webhook Handler for Render

This is a production-ready webhook handler for ActiveCampaign, optimized for deployment on Render.com.

## Features

- ✅ Automatic database initialization (SQLite)
- ✅ Webhook signature verification
- ✅ Comprehensive error handling and logging
- ✅ Health check endpoint for monitoring
- ✅ Test endpoint for development
- ✅ Logs viewer (protected with token)

## Quick Deploy to Render

### Option 1: Deploy with Render Button (Easiest)

1. Push this folder to a GitHub repository
2. Click "New +" in Render dashboard
3. Select "Web Service"
4. Connect your GitHub repository
5. Use these settings:
   - **Name**: activecampaign-webhook
   - **Root Directory**: src/unified/render-webhook (if in subdirectory)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn webhook_render:app`

### Option 2: Manual Setup

1. Create a new Web Service on Render
2. Connect to your GitHub repository
3. Configure environment variables:
   - `AC_WEBHOOK_SECRET`: CorvusSolutions (or your secret)
   - `ADMIN_TOKEN`: (auto-generate for security)
4. Deploy!

## Environment Variables

- `AC_WEBHOOK_SECRET`: Webhook secret for signature verification (default: "CorvusSolutions")
- `ADMIN_TOKEN`: Token for accessing the logs endpoint
- `PORT`: Port to run on (Render sets this automatically)

## Endpoints

- `POST /webhook/activecampaign` - Main webhook endpoint
- `GET /webhook/health` - Health check (Render uses this)
- `POST /webhook/test` - Test endpoint
- `GET /webhook/logs` - View recent logs (requires Authorization header)
- `GET /` - Service info

## ActiveCampaign Configuration

1. After deployment, copy your Render URL (e.g., `https://your-app.onrender.com`)
2. In ActiveCampaign:
   - Go to Settings → Developer → Webhooks
   - Add new webhook
   - URL: `https://your-app.onrender.com/webhook/activecampaign`
   - Secret: CorvusSolutions (or your custom secret)
   - Events: Select the events you want to track

## Testing

1. Use the test endpoint:
```bash
curl -X POST https://your-app.onrender.com/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"type":"contact_add","contact":{"email":"test@example.com"}}'
```

2. View logs:
```bash
curl https://your-app.onrender.com/webhook/logs \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

## Database

The webhook uses SQLite which stores data in `webhook_data.db`. This file persists across deployments on Render's paid plans. For the free tier, consider using Render's PostgreSQL addon instead.

## Monitoring

- Check `/webhook/health` for service status
- Use `/webhook/logs` to view recent webhook activity
- Render provides automatic monitoring and alerts

## Troubleshooting

1. **500 Errors**: Check Render logs for detailed error messages
2. **403 Forbidden**: Verify webhook secret matches ActiveCampaign
3. **No data**: Check that ActiveCampaign is sending to the correct URL

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python webhook_render.py

# Test with ngrok
ngrok http 8080
```