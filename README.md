# ActiveCampaign Webhook Handler

Production-ready webhook handler for ActiveCampaign on Render.

## Quick Deploy

1. Push these files to your GitHub repo root:
   - `webhook_render.py`
   - `requirements.txt`
   - This README.md

2. In Render:
   - Create New > Web Service
   - Connect your GitHub repo
   - **Leave Root Directory blank** (use repo root)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn webhook_render:app`

3. Add environment variables in Render:
   - `AC_WEBHOOK_SECRET` = `CorvusSolutions`
   - `ADMIN_TOKEN` = (click Generate to create random token)

4. Deploy!

## Your Webhook URL

After deployment, your webhook URL will be:
```
https://YOUR-APP-NAME.onrender.com/webhook/activecampaign
```

## Configure ActiveCampaign

1. Go to ActiveCampaign > Settings > Developer > Webhooks
2. Add New Webhook:
   - URL: Your Render webhook URL (above)
   - Secret: CorvusSolutions
   - Events: Select contact events you want to track

## Test Your Webhook

```bash
# Test endpoint (replace with your URL)
curl -X POST https://YOUR-APP.onrender.com/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"type":"contact_add","contact":{"email":"test@example.com"}}'

# View logs (use your ADMIN_TOKEN)
curl https://YOUR-APP.onrender.com/webhook/logs \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

## Endpoints

- `/` - Service info
- `/webhook/activecampaign` - Main webhook endpoint
- `/webhook/health` - Health check
- `/webhook/test` - Test webhook
- `/webhook/logs` - View recent logs (requires auth)