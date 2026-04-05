"""
部分空間正則化付きPCA (Subspace Regularized PCA)

論文の核心アルゴリズム:
1. 事前部分空間 V0 から事前エクスポージャー C0 を構築
2. サンプル相関行列とC0を正則化混合 → C_reg
3. C_reg の上位K固有ベクトルでシグナルを構成

参考: 中川ら (SIG-FIN-035, 2025) + (SIG-FIN-036, 2026)
"""

import numpy as np

from leadlag.constants import N_US, N_JP, NUM_FACTORS, LAMBDA_REG


def buildPriorExposure(cFull, v0):
  """
  事前エクスポージャー行列 C0 を構築する (論文 式10-12)。

  C0 = Δ^{-1/2} V0 D0 V0^T Δ^{-1/2} (対角=1に正規化)

  Args:
    cFull: 長期推定相関行列 (N x N)
    v0: 事前部分空間 (N x K0)

  Returns:
    C0: 事前エクスポージャー相関行列 (N x N)
  """
  # D0: 事前方向の固有値推定 (式10)
  d0 = np.diag(v0.T @ cFull @ v0)
  D0 = np.diag(d0)

  # Craw0 = V0 @ D0 @ V0.T (式11)
  cRaw0 = v0 @ D0 @ v0.T

  # 対角正規化して相関行列化 (式12)
  delta = np.diag(cRaw0)
  delta = np.where(delta > 0, delta, 1e-8)  # ゼロ除算回避
  deltaInvSqrt = np.diag(1.0 / np.sqrt(delta))
  c0 = deltaInvSqrt @ cRaw0 @ deltaInvSqrt

  # 対角を厳密に1に
  np.fill_diagonal(c0, 1.0)
  return c0


def estimateCorrelation(returns):
  """
  標準化リターンから相関行列を推定する。
  NaNを含む行は除外して推定。

  Args:
    returns: (L x N) リターン行列 (NaN許容)

  Returns:
    C: (N x N) 相関行列
    mu: (N,) 平均 (全行から計算)
    sigma: (N,) 標準偏差 (全行から計算)
  """
  # NaN行を除外
  mask = ~np.isnan(returns).any(axis=1)
  clean = returns[mask]

  if clean.shape[0] < 2:
    N = returns.shape[1]
    return np.eye(N), np.zeros(N), np.ones(N)

  mu = np.mean(clean, axis=0)
  sigma = np.std(clean, axis=0, ddof=0)
  sigma = np.where(sigma > 0, sigma, 1e-8)

  z = (clean - mu) / sigma
  L = z.shape[0]
  C = (z.T @ z) / L

  # 対角を厳密に1に
  np.fill_diagonal(C, 1.0)
  return C, mu, sigma


def subspaceRegPca(cSample, c0, lam=LAMBDA_REG, k=NUM_FACTORS):
  """
  部分空間正則化PCA (論文 式13-16)。

  C_reg = (1-λ)C_sample + λC_0
  → 固有値分解で上位K固有ベクトル抽出
  → US/JP ブロックに分割

  Args:
    cSample: サンプル相関行列 (N x N)
    c0: 事前エクスポージャー行列 (N x N)
    lam: 正則化パラメータ (0=サンプルのみ, 1=事前のみ)
    k: 抽出するファクター数

  Returns:
    loadingsUs: 米国側ローディング (N_US x K)
    loadingsJp: 日本側ローディング (N_JP x K)
    eigenvalues: 上位K固有値
  """
  # 正則化相関行列 (式13)
  cReg = (1 - lam) * cSample + lam * c0

  # 対称行列の固有値分解 (数値安定)
  eigvals, eigvecs = np.linalg.eigh(cReg)

  # eighは昇順なので反転して上位K個
  idx = np.argsort(eigvals)[::-1]
  eigvals = eigvals[idx]
  eigvecs = eigvecs[:, idx]

  topEigvals = eigvals[:k]
  topEigvecs = eigvecs[:, :k]

  # US/JPブロックに分割 (式16)
  loadingsUs = topEigvecs[:N_US, :]
  loadingsJp = topEigvecs[N_US:, :]

  return loadingsUs, loadingsJp, topEigvals


def projectSignal(usShock, loadingsUs, loadingsJp):
  """
  米国シグナルを日本側に射影 (論文 式17-19)。

  1. ファクタースコア: f = V_U^T @ z_U  (式18)
  2. 日本予測: ẑ_J = V_J @ f           (式19)

  Args:
    usShock: 米国標準化リターン (N_US,)
    loadingsUs: 米国側ローディング (N_US x K)
    loadingsJp: 日本側ローディング (N_JP x K)

  Returns:
    jpPredicted: 日本側予測シグナル (N_JP,)
    factorScores: ファクタースコア (K,)
  """
  factorScores = loadingsUs.T @ usShock   # (K,)
  jpPredicted = loadingsJp @ factorScores  # (N_JP,)
  return jpPredicted, factorScores
