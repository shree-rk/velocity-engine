# VELOCITY ENGINE - Setup Guide

## What You Have So Far (Phase 1, Batch 1)
- ✅ Project structure with all directories
- ✅ `config/settings.py` - All configuration loaded from .env
- ✅ `config/watchlists.py` - All 11 Velocity symbols + 12 Geo symbols defined
- ✅ `indicators/technical.py` - BB, RSI, ATR, ADX, SMA, Volume + position sizing
- ✅ `tests/test_indicators.py` - 25+ unit tests for all indicator math
- ✅ `requirements.txt` - All Python dependencies
- ✅ `.env.example` - Environment template
- ✅ `.gitignore` - Keeps secrets out of Git

## What's Coming (next sessions)
- 🔲 `brokers/alpaca_broker.py` - Alpaca connection (paper + live)
- 🔲 `filters/` - VIX filter, event calendar, trading hours
- 🔲 `storage/models.py` - Database models
- 🔲 `strategies/velocity_mr.py` - The strategy scanner
- 🔲 `core/engine.py` - Orchestrator
- 🔲 `core/scheduler.py` - APScheduler cron jobs
- 🔲 `core/risk_manager.py` - Alpha Shield
- 🔲 `main.py` - Entry point

---

## STEP 1: Check Python Version

Open your terminal (Command Prompt on Windows, Terminal on Mac).

```bash
python --version
```

You need Python 3.11 or higher. If you see 3.11, 3.12, or 3.13 you're good.

If you see an older version or "command not found":
- **Windows**: Download from https://www.python.org/downloads/ - CHECK "Add to PATH" during install
- **Mac**: `brew install python@3.12` (if you have Homebrew) or download from python.org

---

## STEP 2: Create a Project Folder

```bash
# Navigate to where you want the project
cd ~/Documents

# Create the project folder (or download the files I gave you into it)
mkdir velocity-engine
cd velocity-engine
```

---

## STEP 3: Create a Virtual Environment

This keeps your project's packages separate from other Python projects.

```bash
# Create virtual environment
python -m venv venv

# Activate it:
# On Windows:
venv\Scripts\activate

# On Mac/Linux:
source venv/bin/activate
```

You'll see `(venv)` at the start of your terminal prompt. This means it's active.

**IMPORTANT**: Every time you open a new terminal to work on this project, you need to activate the venv again.

---

## STEP 4: Install Dependencies

```bash
pip install -r requirements.txt
```

This will take a minute. You'll see a lot of text scrolling. Wait until it finishes.

To verify it worked:
```bash
python -c "import pandas_ta; import alpaca; print('All packages installed!')"
```

---

## STEP 5: Set Up Your .env File

```bash
# Copy the template
cp .env.example .env
```

Now edit `.env` with your text editor and fill in your Alpaca keys:
```
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxx        # Your paper trading key
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxx  # Your paper trading secret
ALPACA_TRADING_MODE=paper
```

You can find your Alpaca keys at: https://app.alpaca.markets → Paper Trading → API Keys

---

## STEP 6: Run the Tests

This validates that all the indicator math works correctly:

```bash
pytest tests/test_indicators.py -v
```

You should see output like:
```
tests/test_indicators.py::TestValidation::test_valid_dataframe_passes PASSED
tests/test_indicators.py::TestIndicatorCalculation::test_price_is_last_close PASSED
tests/test_indicators.py::TestStopLoss::test_high_beta_stop PASSED
...
```

**ALL tests should pass.** If any fail, copy the error and share it with me.

---

## STEP 7: Set Up GitHub

```bash
# Initialize git repo
git init

# Add all files
git add .

# First commit
git commit -m "Phase 1 Batch 1: Project structure, config, indicators, tests"

# Create a PRIVATE repo on GitHub (https://github.com/new)
# Name it: velocity-engine
# Make it PRIVATE (important - your trading logic!)

# Connect to GitHub (replace with your repo URL)
git remote add origin https://github.com/shree-rk/velocity-engine.git

# Push
git branch -M main
git push -u origin main
```

---

## STEP 8: Verify Your Setup

Run this quick check script:
```bash
python -c "
from config.settings import validate_config, ALPACA_TRADING_MODE
print('=== Velocity Engine Config Check ===')
validate_config()
print('Config: OK')

from config.watchlists import VELOCITY_MR_WATCHLIST, get_all_symbols
symbols = get_all_symbols(VELOCITY_MR_WATCHLIST)
print(f'Watchlist: {len(symbols)} symbols - {symbols}')

from indicators.technical import IndicatorSnapshot
snap = IndicatorSnapshot(
    symbol='TEST', price=95.0, sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
    rsi_14=25.0, atr_14=2.0, adx_14=20.0, plus_di=15.0, minus_di=25.0,
    volume=2000000, avg_volume=1000000, volume_ratio=2.0,
)
print(f'Indicators: {snap.conditions_met_count}/4 conditions met')
print(f'All entry conditions: {snap.all_entry_conditions_met}')
print('=== All OK! Ready for next batch ===')
"
```

---

## Next Session: What We Build
1. Alpaca broker connection (fetch bars, place orders)
2. VIX filter, event calendar, trading hours
3. Database models + PostgreSQL setup
4. The Velocity 2.0 scanner strategy module

---

## Troubleshooting

**"ModuleNotFoundError: No module named 'config'"**
→ Make sure you're running from the project root directory (`velocity-engine/`)

**"pip: command not found"**
→ Try `pip3` instead of `pip`, or `python -m pip`

**Tests fail with import errors**
→ Make sure your virtual environment is activated (you see `(venv)` in your prompt)

**Alpaca key errors**
→ Double-check your .env file has the correct keys with no extra spaces
