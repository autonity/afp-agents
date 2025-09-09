# Autonomous Futures Protocol Agents

This repository contains example implementations of on-chain agents responsible
for calling public actions on the AFP Clearing Contracts. Each agent is designed
to automate a specific aspect of protocol maintenance and risk management.

## Agents Overview

There are three main agents in this repository:

- **Closeout Agent**
- **Liquidation Agent**
- **Bankruptcy Agent**

Each agent is intended to be run as a cron job at a fixed periodic interval,
ensuring timely execution of protocol actions.

---

## Closeout Agent

**Purpose:**  
The Closeout Agent monitors on-chain products that have reached expiry. When a
product's`earliestFSPSubmission` time has passed and the Final Settlement Price
has been finalized on the clearing contracts, the agent triggers the closing of
positions at the final settlement price.

**Typical Use Case:**

- Automatically closes positions for expired products.
- Helps maintain protocol health by ensuring positions are settled at expiry.
- Caller of `initiateFinalSettlement` earns a fee, credited to their margin
  account.

---

## Liquidation Agent

**Purpose:**  
The Liquidation Agent identifies margin accounts that are eligible for
liquidation auctions (ie equity < maintenance margin). It initiates
liquidation, submits bids, and manages the resell process for liquidated 
positions.

**Typical Use Case:**

- Automates the process of starting liquidation auctions for unhealthy accounts.
- Submits bids to participate in ongoing auctions.
- Can be configured to resell acquired positions.
- Liquidated positions can usually be taken over below the current mark
  price, so liquidators can make a profit on successfully reselling liquidated
  positions.

---

## Bankruptcy Agent

**Purpose:**  
The Bankruptcy Agent detects accounts that have entered bankruptcy and executes
the necessary protocol actions to resolve them. This involves mutualizing 
losses amongst Loss Absorbing Accounts (LAAs).

**Typical Use Case:**

- Handles accounts that cannot be restored via liquidation or closeout.
- Ensures the protocol remains solvent by processing bankrupt accounts.

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
- `SUBQUERY_URL`: Autonity subquery node URL.

**Optional AFP configuration:** (defaults to mainnet addresses if not set)

- `AFP_CLEARING_DIAMOND_ADDRESS`
- `AFP_MARGIN_ACCOUNT_REGISTRY_ADDRESS`
- `AFP_ORACLE_PROVIDER_ADDRESS`
- `AFP_PRODUCT_REGISTRY_ADDRESS`

**Exchange Connection (only for liquidation agent):**

- `AFP_EXCHANGE_URL`

---

## Account Requirements

Each agent requires a private key to sign transactions. The requirements for the
account corresponding to this key differ by agent:

- **Closeout Agent:**  
  The account must be funded with ATN to pay for gas fees. No margin account or
  collateral is required.

- **Bankruptcy Agent:**  
  The account must be funded with ATN to pay for gas fees. No margin account or
  collateral is required.

- **Liquidation Agent:**  
  The account must be funded with ATN for gas fees **and** must have a funded
  margin account in the collateral asset used for liquidation.  
  This is required because the agent must take over the positions of the
  liquidated account before it can resell them. The margin account must be
  sufficiently funded to pass the MAE (Margin Account Equity) checks for the
  positions it is taking over.

---

## Running Agents

Agents can be run using the commands defined in `pyproject.toml`.  
Make sure your `.env` file is configured before running.

**To run an agent:**

```bash
uv run --env-file .env -m bankruptcy
uv run --env-file .env -m closeout
uv run --env-file .env -m liquidation
```

Each command will run the corresponding agent with your environment
configuration.

