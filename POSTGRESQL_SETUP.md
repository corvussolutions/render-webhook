# PostgreSQL Setup for ActiveCampaign Webhook

## Step 1: Create PostgreSQL Database in Render

1. **Go to Render Dashboard** → Click "New +"
2. **Select "PostgreSQL"**
3. **Configure:**
   - **Name**: `activecampaign-webhook-db` (or any name you prefer)
   - **Database**: `webhook_db` 
   - **User**: `webhook_user`
   - **Region**: Same as your web service (for better performance)
   - **Plan**: Starter ($7/month)

4. **Click "Create Database"**

5. **Wait for it to deploy** (2-3 minutes)

## Step 2: Get Database Connection Info

1. **In the PostgreSQL dashboard**, find the **"Connections"** section
2. **Copy the "External Database URL"** - it looks like:
   ```
   postgresql://username:password@host:port/database
   ```

## Step 3: Update Your Web Service

1. **Go to your web service** (`render-webhook`)
2. **Click "Environment"** 
3. **Add new environment variable:**
   - **Key**: `DATABASE_URL`
   - **Value**: Paste the database URL from step 2

4. **Update your service settings:**
   - **Start Command**: `gunicorn webhook_postgresql:app`
   - Make sure `requirements.txt` includes `psycopg2-binary==2.9.9`

## Step 4: Deploy

1. **Push updated files to GitHub:**
   - `webhook_postgresql.py` (new main file)
   - `requirements.txt` (updated with psycopg2)

2. **In Render**: Click "Manual Deploy" or it will auto-deploy

3. **Check logs** to see:
   ```
   PostgreSQL connection pool initialized
   PostgreSQL database tables initialized
   ```

## Step 5: Test

1. **Health check**: `https://render-webhook-odht.onrender.com/webhook/health`
   - Should show database stats

2. **Make a change in ActiveCampaign** (add a note to a contact)

3. **Check logs**: `https://render-webhook-odht.onrender.com/webhook/logs`
   - Requires Authorization: `Bearer YOUR_ADMIN_TOKEN`

## Benefits of PostgreSQL

✅ **Data persists** through deployments
✅ **Automatic backups** by Render
✅ **Better performance** than SQLite
✅ **JSONB storage** for webhook data (searchable)
✅ **Concurrent access** support
✅ **Monitoring and alerts**

## New Features

- **Stats endpoint**: `/webhook/stats` shows event counts
- **JSONB storage**: Webhook data stored as searchable JSON
- **Connection pooling**: Better performance under load
- **Database indexes**: Faster queries on email and date

## Cost

- **PostgreSQL**: $7/month (Starter plan)
- **Web Service**: ~$7/month (Starter plan)
- **Total**: ~$14/month for reliable webhook processing

## Troubleshooting

1. **"Database not configured" error**: Check DATABASE_URL environment variable
2. **Connection failed**: Verify database URL is correct
3. **Permission denied**: Make sure database is in same region as web service

Your webhook will now have persistent, production-ready storage! 🎉