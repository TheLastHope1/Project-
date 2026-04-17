"""Interactive setup for the Polymarket BTC bot.

Walks the user through creating a valid .env file and prints the
derived EOA address so they can verify it matches Polymarket's
"Signer Address" before going live.

Run via ./start.sh (auto-invoked when .env is missing) or directly:

    python setup.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# eth_account is a transitive dep of py-clob-client; available after
# requirements install.
from eth_account import Account

ENV_PATH = Path(__file__).resolve().parent / ".env"


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    """Prompt the user for a value. Shows [default] if provided."""
    label = f"{prompt}"
    if default:
        label += f" [{default}]"
    label += ": "
    if secret:
        import getpass
        val = getpass.getpass(label).strip()
    else:
        val = input(label).strip()
    return val or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " (Y/n)" if default else " (y/N)"
    ans = input(prompt + suffix + ": ").strip().lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def header(text: str) -> None:
    print()
    print("━" * 64)
    print(text)
    print("━" * 64)


def main() -> int:
    header("Polymarket BTC Bot — Interactive Setup")
    print("""
This wizard creates your .env file. You'll need:

  1. Your Polymarket wallet's PRIVATE KEY
  2. Your Polymarket FUNDER ADDRESS (deposit address)
  3. How you signed up (MetaMask vs email)

Press Ctrl+C at any time to abort.
""")

    if ENV_PATH.exists():
        if not ask_yes_no(
            f".env already exists at {ENV_PATH}. Overwrite?",
            default=False,
        ):
            print("Aborted. No changes made.")
            return 1

    # ── Signup method ───────────────────────────────────────────────
    header("Step 1 — How did you sign up to Polymarket?")
    print("""
  [1] MetaMask or external wallet (connected via WalletConnect)
  [2] Email / Google / social signup (Polymarket embedded wallet)
""")
    while True:
        choice = ask("Choose 1 or 2", default="2")
        if choice in ("1", "2"):
            break
        print("  ↳ enter 1 or 2")

    sig_type = 1 if choice == "1" else 2
    sig_name = "POLY_PROXY" if sig_type == 1 else "POLY_GNOSIS_SAFE"
    print(f"  ↳ signature_type={sig_type} ({sig_name})")

    # ── Private key ─────────────────────────────────────────────────
    header("Step 2 — Paste your Polymarket wallet PRIVATE KEY")
    print("""
Where to find it:

  MetaMask:  click account icon → Account Details → Export Private Key
             → enter your MetaMask password → copy the hex string

  Email:     polymarket.com → Profile icon → Settings
             → scroll to "Export Private Key" → enter password → copy it

The key is a 64-character hex string (may start with 0x). It will NOT
be displayed as you type.
""")
    while True:
        pk = ask("PRIVATE_KEY", secret=True)
        if not pk:
            print("  ↳ required, try again")
            continue
        # Normalize: strip 0x prefix for consistency; py-clob-client
        # accepts both but signing libs prefer with-prefix.
        if not pk.startswith("0x"):
            pk = "0x" + pk
        try:
            signer_eoa = Account.from_key(pk).address
        except Exception as e:
            print(f"  ↳ that key is invalid ({e}). Try again.")
            continue
        break

    print(f"\n  ↳ Derived signer address: {signer_eoa}")

    # ── Funder address ──────────────────────────────────────────────
    header("Step 3 — Your Polymarket FUNDER ADDRESS")
    print("""
This is the address that holds your USDC on Polymarket (NOT the same
as your signer address above, unless you use a raw wallet).

Where to find it:

  polymarket.com → Profile icon (top right) → "Deposit" or "Wallet"
  → copy the address that starts with 0x.

Or: polymarket.com → Settings → look for "Funder" / "Deposit Address".
""")
    while True:
        funder = ask("POLYMARKET_FUNDER_ADDRESS")
        if not funder:
            print("  ↳ required, try again")
            continue
        funder = funder.strip()
        if not funder.startswith("0x") or len(funder) != 42:
            print("  ↳ should be a 42-char address starting with 0x. Try again.")
            continue
        break

    # Sanity-check: signer MUST differ from funder for proxy wallets
    if funder.lower() == signer_eoa.lower():
        print("""
  ⚠️  WARNING: your signer address equals your funder address.

  For email/MetaMask proxy wallets this is almost certainly wrong —
  the funder is a proxy contract, and its signer is your private key's
  derived EOA, which should be a DIFFERENT address.

  If you copy/pasted the wrong value for one of them, go back and fix
  it now. Otherwise continue at your own risk.
""")
        if not ask_yes_no("Continue anyway?", default=False):
            return 1

    # ── Dry run mode ────────────────────────────────────────────────
    header("Step 4 — Trading mode")
    print("""
  [live]    Place REAL orders with REAL money
  [dry]     Paper-trade — simulate orders, never spend USDC
""")
    mode = ask("Mode (live/dry)", default="live").lower()
    dry_run = "true" if mode.startswith("d") else "false"

    # ── Write .env ──────────────────────────────────────────────────
    header("Writing .env")
    env_contents = f"""# Generated by setup.py. Edit this file manually to change values.

# ── Polymarket credentials ─────────────────────────────────────────
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=

# Your wallet's private key (signer of orders).
PRIVATE_KEY={pk}

# Your Polymarket funder / deposit address (holds USDC).
POLYMARKET_FUNDER_ADDRESS={funder}

# Signature type:
#   1 = POLY_PROXY       (MetaMask / external wallet)
#   2 = POLY_GNOSIS_SAFE (email / Google / social signup)
POLYMARKET_SIGNATURE_TYPE={sig_type}

# ── Bot behavior ──────────────────────────────────────────────────
DRY_RUN={dry_run}

# ── Dashboard ─────────────────────────────────────────────────────
DASHBOARD_ENABLED=true
DASHBOARD_PORT=8787
"""
    ENV_PATH.write_text(env_contents)
    try:
        os.chmod(ENV_PATH, 0o600)
    except Exception:
        pass

    print(f"  ↳ wrote {ENV_PATH}")
    print(f"  ↳ chmod 600 applied")

    # ── Final verification step ─────────────────────────────────────
    header("FINAL CHECK — verify the signer before you trade")
    print(f"""
Your SIGNER ADDRESS is:

    {signer_eoa}

Go to polymarket.com → Profile → Settings and find the field labeled
"Signer Address" (or "API Key" / "API Signer Address"). It MUST
match the address above exactly.

If it does NOT match, your orders will be rejected with
"invalid signature" and no trading will happen. In that case,
re-export the correct private key and run ./start.sh again.

Ready to launch? The bot will start in a moment.
""")
    input("Press ENTER to continue (or Ctrl+C to exit)...")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
