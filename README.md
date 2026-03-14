# Hyperliquid Wallet Tracker Bot

This is a Python-based Telegram bot that tracks specific wallet addresses on the Hyperliquid DEX. It automatically alerts you whenever a tracked wallet opens a new position. Built with Flask and designed for seamless deployment on Vercel.

## Key Features

-   **Wallet Management**: Easily add (`/add`), remove (`/remove`), or list (`/list`) tracked Hyperliquid wallets directly via Telegram.
-   **Real-time Notifications**: Get instant Telegram alerts when a monitored wallet opens a new Long or Short position.
-   **Detailed Alerts**: Notifications include the token symbol, trade direction, position size, entry price, and leverage used.
-   **Quick Trade Links**: Each alert includes a direct link to trade the specific token on the Hyperliquid platform.
-   **Fully Automated**: Utilizes Vercel Cron Jobs (configured via `vercel.json`) to automatically check positions every minute without external services.

## Tech Stack

-   **Language**: Python
-   **Framework**: Flask
-   **Deployment**: Vercel
-   **Database**: Redis (Compatible with Vercel KV, Upstash, etc.)
-   **Data Source**: Hyperliquid API

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
-   `CRON_SECRET`: A long, random, secret string that you create. This is used to secure your cron job endpoint.

### Step 4: Deploy & Set Webhook

1.  Click the **Deploy** button in Vercel.
2.  Once the deployment is complete, Vercel will provide you with a URL (e.g., `https://your-bot-name.vercel.app`).
3.  Set the Telegram webhook by running the following command in your terminal. Replace the placeholders with your actual values:
    ```bash
    curl "[https://api.telegram.org/bot](https://api.telegram.org/bot)<YOUR_TELEGRAM_TOKEN>/setWebhook?url=<YOUR_VERCEL_URL>"
    ```

### Step 5: Cron Job Setup

You do **not** need to set up external cron jobs anymore! 

The `vercel.json` file is already configured to trigger the `/check_positions` endpoint every minute using Vercel's built-in cron feature. Vercel will automatically use the `CRON_SECRET` environment variable to authenticate the requests.

## Bot Commands

-   `/start` - Displays a welcome message and instructions on how to use the bot.
-   `/add <wallet_address>` - Subscribes your chat to alerts for a specific Hyperliquid wallet.
-   `/remove <wallet_address>` - Unsubscribes your chat from a specific wallet's alerts.
-   `/list` - Shows all the wallet addresses you are currently tracking.