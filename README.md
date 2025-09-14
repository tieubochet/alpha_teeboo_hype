# Real-time tracking of Binance Alpha project airdrops Bot

This is a Python-based Telegram bot that fetches and displays upcoming crypto airdrop events. It is built with Flask and designed for easy deployment on Vercel.

The bot automatically sends reminder notifications to subscribed groups before an event begins.

## Key Features

-   **View Airdrop Events**: Displays a clean list of today's and upcoming airdrop events.
-   **Interactive Refresh Button**: Allows users to get the latest event list without sending a new command.
-   **Dynamic "Trade" Button**: The trade link button automatically updates to show the token of the next upcoming event (e.g., "Trade ZRO on Hyperliquid").
-   **Automatic Reminders**: Sends a notification to subscribed groups 5 minutes before an event starts.
-   **Auto-Pinning**: Important reminder messages are automatically pinned in the group for visibility.
-   **Easy Subscription**: Group administrators can manage notifications with simple `/start` and `/stop` commands.

## Tech Stack

-   **Language**: Python
-   **Framework**: Flask
-   **Deployment**: Vercel
-   **Database**: Redis (Compatible with Vercel KV, Upstash, etc.)
-   **Data Source**: API

## Deployment Guide

Follow these steps to deploy your own instance of the bot on Vercel.

### Step 1: Project Setup

1.  Clone this repository to your local machine.
2.  Create a new repository on your GitHub, GitLab, or Bitbucket account.
3.  Push the cloned code to your new repository.

### Step 2: Create Vercel Project

1.  Log in to your Vercel account and select **Add New... -> Project**.
2.  Import the Git repository you just created. Vercel will automatically detect the Python environment from the `vercel.json` file.

### Step 3: Configure Environment Variables

In your Vercel project dashboard, go to **Settings -> Environment Variables** and add the following:

-   `TELEGRAM_TOKEN`: The token for your Telegram bot, obtained from BotFather.
-   `REDIS_URL`: The full connection string for your Redis database (e.g., from Vercel KV or Upstash).
-   `CRON_SECRET`: A long, random, secret string that you create. This is used to protect your cron job endpoint.

### Step 4: Deploy & Set Webhook

1.  Click the **Deploy** button.
2.  Once the deployment is complete, Vercel will provide you with a URL (e.g., `https://your-bot-name.vercel.app`).
3.  Set the Telegram webhook by running the following command in your terminal. Replace the placeholders with your actual values.
    ```bash
    curl "https://api.telegram.org/bot<YOUR_TELEGRAM_TOKEN>/setWebhook?url=<YOUR_VERCEL_URL>"
    ```

### Step 5: Configure Cron Job

To enable automatic notifications, you need to set up a cron job to call the `/check_events` endpoint every minute.

1.  In your Vercel project dashboard, navigate to the **Cron Jobs** tab.
2.  Create a new job with the following settings:
    -   **Schedule**: `* * * * *` (This means "run every minute").
    -   **URL**: `https://<YOUR_VERCEL_URL>/check_events` (Make sure to add `/check_events` to the end of your Vercel URL).
    -   **HTTP Method**: `POST`
    -   **Headers**: Add one header with the key `X-Cron-Secret` and the value as the `CRON_SECRET` you created in Step 3.

## Bot Commands

-   `/start` - Displays a welcome message and subscribes the chat to airdrop notifications.
-   `/stop` - Unsubscribes the chat from airdrop notifications.
-   `/alpha` - Shows the current list of today's and upcoming airdrop events.