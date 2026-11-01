#!/usr/bin/env python
"""
TradingAgents POC - Memory Integration Test
Tests EUvest SQLite persistence integration with TradingAgents memory.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent / ".venv" / "src" / "tradingagents"))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG, build_default_config
from tradingagents.dataflows.config import set_config
from tradingagents.memory.log import TradingMemoryLog