# Autonomous Futures Protocol Agents

This repository contains implementations of on-chain agents responsible for
calling public actions on the AFP Clearing Contracts. Each agent is designed
to automate a specific aspect of protocol maintenance and risk management.

## Available Agents

### Closeout Agent

The Closeout Agent monitors on-chain products that have reached expiry. When a
product's `earliestFSPSubmission` time has passed and the Final Settlement Price
has been finalized on the clearing contracts, the agent triggers the closing of
positions at the final settlement price.

**Typical Use Case:**

- Automatically closes positions for expired products.
- Helps maintain protocol health by ensuring positions are settled at expiry.
- Caller of `initiateFinalSettlement` earns a fee, credited to their margin
  account.

---

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/autonity/afp-agents.git
   cd afp-agents
   ```

2. **Install dependencies using [uv](https://github.com/astral-sh/uv):**

   ```bash
   uv sync
   ```

3. **Configure environment variables:**
   Copy `.env.template` to `.env` and fill in the required values:

   ```bash
   cp .env.template .env
   ```

   **Required variables:**

   - `PRIVATE_KEY`: The agent's account private key.
   - `RPC_URL`: Autonity RPC node URL.
   - `SUBQUERY_URL`: Autonity subquery node URL (defaults to `https://subquery.autonity.org/graphql`)

   **Optional AFP configuration:** (defaults to mainnet addresses if not set)

   - `AFP_CLEARING_DIAMOND_ADDRESS`
   - `AFP_MARGIN_ACCOUNT_REGISTRY_ADDRESS`
   - `AFP_ORACLE_PROVIDER_ADDRESS`
   - `AFP_PRODUCT_REGISTRY_ADDRESS`
   - `AFP_SYSTEM_VIEWER_ADDRESS`

   **Optional notifications:**

   - `NOTIFIER_TYPE`: Notification backend (`default` or `slack`)
   - `SLACK_TOKEN`: Slack bot token (if using Slack)
   - `SLACK_CHANNEL`: Slack channel for notifications
   - `SLACK_ICON_EMOJI`: Emoji for Slack messages

   **Optional healthcheck:**

   - `HEALTHCHECK_PING_URL`: URL to ping on successful runs

---

## Account Requirements

The Closeout Agent requires a private key to sign transactions. The account
must be funded with ATN to pay for gas fees. No margin account or collateral
is required.

---

## Running Agents

Agents can be run as Python modules. Make sure your `.env` file is configured
before running.

```bash
uv run --env-file .env -m closeout
```

Agents are intended to be run as cron jobs at a fixed periodic interval,
ensuring timely execution of protocol actions.