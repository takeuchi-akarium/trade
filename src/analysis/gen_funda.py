"""
ファンダスコア閾値感度分析
gold_days=80 に変更後、スコアstdが0.54->0.81に拡大したことで
旧閾値(fundaThr=0.3, boostThr=0.5)が適切でなくなった可能性を検証。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta


FUNDA_THRS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
BOOST_THRS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
UP_ZONE    = 5.0
DOWN_ZONE  = -10.0

