"""
Stage 10 support: Random-effects (DerSimonian-Laird) meta-analysis pooling
for combining odds/relative/hazard ratios extracted from potentially
different papers (AD-6).

Why: independently sampling each paper's ratio and multiplying them
together treats them as independent multiplicative risk factors measured
on the same population -- which they are not. Two papers' estimates of a
similar effect (with genuine between-study heterogeneity: different
populations, methods, follow-up periods) must be POOLED into one combined
estimate with a properly widened confidence interval, not multiplied
together, which silently understates uncertainty.

Method verified against the Cochrane Handbook (9.4.3.1, "Random-effects
(DerSimonian and Laird) method") and the original DerSimonian-Laird (1986)
method-of-moments estimator.

Scope note (deliberate, see Story 3.2 Dev Notes): this module pools
odds ratios, relative risks, and hazard ratios together as if they were
repeated estimates of one effect, with no type-consistency check. These
are statistically distinct quantities, only approximately interchangeable
under a rare-outcome assumption. The param schema this codebase uses has
no risk-factor-identity/grouping field to distinguish "same effect,
different papers" from "different effects" -- introducing that
distinction is a data-model change out of scope here.

Confidence gating: params reaching pool_risk_ratios are expected to
already be confidence-gated upstream by run_simulation (Story 3.1). This
function ALSO skips any param whose confidence isn't "medium"/"high" as a
defense-in-depth guard -- before this story, every risk-ratio param
passed through simulation_engine._sample(), which has its own defensive
raise for disallowed confidence; that protection is otherwise unreachable
for this code path now that pooling bypasses _sample() entirely.
"""
import numpy as np

Z_95 = 1.96
# Sane finite bounds for the pooled ratio/CI -- guards against an extreme
# or malformed individual value (or extreme heterogeneity) silently
# producing inf/nan, which downstream JSON serialization can't represent.
_OUTPUT_CLIP_MIN = 1e-6
_OUTPUT_CLIP_MAX = 1e6


def _pool(y_values: list, variances: list, tau_squared: float) -> tuple[float, float]:
    """Given log-scale point estimates, their variances, and a
    between-study variance (0.0 for a fixed-effect pool), returns
    (pooled_log_estimate, pooled_log_variance). Shared by pool_risk_ratios
    (tau_squared from the DL formula, and its own internal fixed-effect
    mean used for Cochran's Q) and by tests (tau_squared=0.0, to compute
    the fixed-effect comparison point with the exact same weighting logic,
    not a re-derived one) -- one implementation of the weighting formula,
    not two independently-drifting ones."""
    if not y_values or not variances:
        raise ValueError("_pool: no values to pool")
    if len(y_values) != len(variances):
        raise ValueError("_pool: y_values and variances must be the same length")
    weights = [1.0 / (v + tau_squared) for v in variances]
    total_weight = sum(weights)
    pooled_estimate = sum(w * y for w, y in zip(weights, y_values)) / total_weight
    pooled_variance = 1.0 / total_weight
    return pooled_estimate, pooled_variance


def pool_risk_ratios(params: list) -> dict:
    """Random-effects (DerSimonian-Laird) pooling of odds/relative/hazard
    ratios, potentially from different papers (AD-6). Returns:
    {"pooled_ratio": float, "ci_lower": float, "ci_upper": float,
     "tau_squared": float, "n_studies": int, "method": "DerSimonian-Laird",
     "pooled_log_estimate": float, "pooled_log_se": float}.
    A single valid ratio (n=1) has no estimable heterogeneity and
    degenerates to that study's own value/CI (tau_squared=0.0) -- the
    same interpretation as a fixed-effect model with one study.
    Raises ValueError if no param has a usable value.

    A param is skipped (not pooled, not an error by itself) if its value
    is missing, non-numeric, non-positive, or non-finite (NaN/Inf), or if
    its confidence isn't "medium"/"high" -- matching this codebase's
    "one bad input doesn't abort the batch" convention. Only if EVERY
    param is skipped does this raise."""
    y_values = []
    variances = []
    for p in params:
        if p.get("confidence") not in ("medium", "high"):
            continue

        value = p.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(value) or value <= 0:
            continue

        lo = p.get("ci_lower")
        hi = p.get("ci_upper")
        if lo is not None and hi is not None and lo > 0 and hi > lo:
            se = (np.log(hi) - np.log(lo)) / (2 * Z_95)
        else:
            # No usable CI (missing, or an inverted/zero-width pair --
            # `hi > lo` is required, not just both positive, so a
            # malformed/reversed CI falls back here rather than producing
            # a negative or zero se that would otherwise be floored into
            # a bogus near-zero variance / near-infinite weight): fall
            # back to a 20% relative SE on the log scale, matching
            # simulation_engine._sample's own no-CI fallback (std =
            # abs(val) * 0.20 on the natural scale) via the delta method:
            # SE(ln X) ~= SE(X)/X ~= 0.20.
            se = 0.2

        y_values.append(np.log(value))
        variances.append(max(se, 1e-6) ** 2)

    k = len(y_values)
    if k == 0:
        raise ValueError("pool_risk_ratios: no usable param (confidence-gated, positive, finite value) to pool")

    # Fixed-effect mean, needed for Cochran's Q -- computed via the same
    # shared _pool() helper the tests use for their comparison point, not
    # a separately hand-rolled formula.
    fe_mean, _ = _pool(y_values, variances, 0.0)
    fe_weights = [1.0 / v for v in variances]

    if k < 2:
        tau_squared = 0.0
    else:
        q = sum(w * (y - fe_mean) ** 2 for w, y in zip(fe_weights, y_values))
        df = k - 1
        sum_w = sum(fe_weights)
        sum_w2 = sum(w ** 2 for w in fe_weights)
        c = sum_w - (sum_w2 / sum_w)
        tau_squared = 0.0 if c == 0 else max(0.0, (q - df) / c)

    pooled_log, pooled_log_var = _pool(y_values, variances, tau_squared)
    se_pooled = pooled_log_var ** 0.5

    pooled_ratio = float(np.clip(np.exp(pooled_log), _OUTPUT_CLIP_MIN, _OUTPUT_CLIP_MAX))
    ci_lower = float(np.clip(np.exp(pooled_log - Z_95 * se_pooled), _OUTPUT_CLIP_MIN, _OUTPUT_CLIP_MAX))
    ci_upper = float(np.clip(np.exp(pooled_log + Z_95 * se_pooled), _OUTPUT_CLIP_MIN, _OUTPUT_CLIP_MAX))

    return {
        "pooled_ratio": pooled_ratio,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "tau_squared": float(tau_squared),
        "n_studies": k,
        "method": "DerSimonian-Laird",
        # Stored directly so sample_pooled_risk doesn't have to reconstruct
        # them by re-log()-ing the (clipped) ratio-scale ci_lower/ci_upper
        # -- avoids a fragile round-trip that only worked by algebraic
        # coincidence and would silently diverge if either formula changed.
        "pooled_log_estimate": float(pooled_log),
        "pooled_log_se": float(se_pooled),
    }


def sample_pooled_risk(pooled: dict, n: int) -> np.ndarray:
    """Draw n samples from the pooled ratio's log-normal distribution --
    for Monte Carlo use. Clipped to [0.1, 20], matching the existing
    safety bound simulation_engine already applied to per-study risk
    samples before this story."""
    log_mean = pooled["pooled_log_estimate"]
    log_se = pooled["pooled_log_se"]
    samples = np.random.normal(log_mean, max(log_se, 1e-6), n)
    return np.clip(np.exp(samples), 0.1, 20)
