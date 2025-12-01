from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger("bakezy.spike_detector")


@dataclass
class SpikeConfig:
    """Configuration for spike detection."""
    # Statistical method thresholds
    z_score_threshold: float = 3.0
    iqr_multiplier: float = 1.5
    
    # Rolling window method parameters
    rolling_window_size: int = 7
    rolling_threshold_percent: float = 50.0  # Percentage above rolling average
    
    # Detection method combination
    detection_method: Literal["statistical", "rolling", "both"] = "both"
    combination_logic: Literal["AND", "OR"] = "OR"  # How to combine methods when using "both"
    
    # Smoothing options
    smoothing_method: Literal["median", "mean"] = "median"
    remove_spikes: bool = False  # If True, remove spikes; if False, smooth them
    
    # Minimum value to consider (ignore spikes below this)
    min_value_threshold: float = 0.0


@dataclass
class SpikeDetectionResult:
    """Result of spike detection."""
    is_spike: pd.Series  # Boolean series indicating spikes
    severity_score: pd.Series  # Float series (0-1) indicating spike severity
    original_values: pd.Series  # Original values before smoothing
    smoothed_values: pd.Series  # Values after smoothing (if applied)


class SpikeDetector:
    """
    Detects spikes in time series data using statistical and rolling window methods.
    """
    
    def __init__(self, config: Optional[SpikeConfig] = None):
        self.config = config or SpikeConfig()
    
    def detect_statistical(self, df: pd.DataFrame, value_col: str = "y") -> pd.Series:
        """
        Detect spikes using statistical methods (Z-score and IQR).
        
        Returns:
            Boolean Series indicating spikes
        """
        if value_col not in df.columns:
            logger.warning(f"Column '{value_col}' not found in dataframe")
            return pd.Series(False, index=df.index)
        
        values = df[value_col].copy()
        is_spike = pd.Series(False, index=df.index)
        
        # Filter out zeros and very small values
        valid_mask = values >= self.config.min_value_threshold
        if not valid_mask.any():
            return is_spike
        
        valid_values = values[valid_mask]
        
        # Z-score method
        mean = valid_values.mean()
        std = valid_values.std()
        
        if std > 0:
            z_scores = np.abs((values - mean) / std)
            z_spike = z_scores > self.config.z_score_threshold
        else:
            z_spike = pd.Series(False, index=df.index)
        
        # IQR method
        q1 = valid_values.quantile(0.25)
        q3 = valid_values.quantile(0.75)
        iqr = q3 - q1
        
        if iqr > 0:
            lower_bound = q1 - self.config.iqr_multiplier * iqr
            upper_bound = q3 + self.config.iqr_multiplier * iqr
            iqr_spike = (values < lower_bound) | (values > upper_bound)
        else:
            iqr_spike = pd.Series(False, index=df.index)
        
        # Combine statistical methods (OR logic)
        is_spike = z_spike | iqr_spike
        
        return is_spike
    
    def detect_rolling(self, df: pd.DataFrame, value_col: str = "y") -> pd.Series:
        """
        Detect spikes using rolling window comparison.
        
        Returns:
            Boolean Series indicating spikes
        """
        if value_col not in df.columns:
            logger.warning(f"Column '{value_col}' not found in dataframe")
            return pd.Series(False, index=df.index)
        
        values = df[value_col].copy()
        is_spike = pd.Series(False, index=df.index)
        
        # Calculate rolling average
        rolling_mean = values.rolling(
            window=self.config.rolling_window_size,
            min_periods=1,
            center=False
        ).mean()
        
        # Calculate threshold (rolling mean * (1 + threshold_percent/100))
        threshold = rolling_mean * (1 + self.config.rolling_threshold_percent / 100.0)
        
        # Mark as spike if value exceeds threshold
        is_spike = values > threshold
        
        # Also check for values significantly below rolling mean (negative spikes)
        lower_threshold = rolling_mean * (1 - self.config.rolling_threshold_percent / 100.0)
        negative_spike = values < lower_threshold
        
        # Combine positive and negative spikes
        is_spike = is_spike | negative_spike
        
        return is_spike
    
    def calculate_severity(self, df: pd.DataFrame, is_spike: pd.Series, value_col: str = "y") -> pd.Series:
        """
        Calculate severity score (0-1) for detected spikes.
        
        Returns:
            Float Series with severity scores
        """
        if value_col not in df.columns:
            return pd.Series(0.0, index=df.index)
        
        values = df[value_col].copy()
        severity = pd.Series(0.0, index=df.index)
        
        if not is_spike.any():
            return severity
        
        # Calculate rolling statistics for context
        rolling_mean = values.rolling(
            window=self.config.rolling_window_size,
            min_periods=1,
            center=False
        ).mean()
        
        rolling_std = values.rolling(
            window=self.config.rolling_window_size,
            min_periods=1,
            center=False
        ).std().fillna(0)
        
        # For spikes, calculate how many standard deviations away
        spike_mask = is_spike
        if spike_mask.any():
            deviations = np.abs((values[spike_mask] - rolling_mean[spike_mask]) / (rolling_std[spike_mask] + 1e-6))
            # Normalize to 0-1 range (cap at 5 std devs = 1.0)
            severity[spike_mask] = np.clip(deviations / 5.0, 0.0, 1.0)
        
        return severity
    
    def smooth_values(
        self,
        df: pd.DataFrame,
        is_spike: pd.Series,
        value_col: str = "y"
    ) -> pd.Series:
        """
        Smooth spike values using rolling median or mean.
        
        Returns:
            Series with smoothed values
        """
        if value_col not in df.columns:
            return df[value_col].copy() if value_col in df.columns else pd.Series(0.0, index=df.index)
        
        values = df[value_col].copy()
        smoothed = values.copy()
        
        if not is_spike.any():
            return smoothed
        
        # Calculate rolling statistic
        if self.config.smoothing_method == "median":
            rolling_stat = values.rolling(
                window=self.config.rolling_window_size,
                min_periods=1,
                center=True
            ).median()
        else:  # mean
            rolling_stat = values.rolling(
                window=self.config.rolling_window_size,
                min_periods=1,
                center=True
            ).mean()
        
        # Replace spike values with rolling statistic
        spike_mask = is_spike
        smoothed[spike_mask] = rolling_stat[spike_mask]
        
        # Fill any remaining NaN values
        smoothed = smoothed.bfill().ffill().fillna(0.0)
        
        return smoothed
    
    def detect(
        self,
        df: pd.DataFrame,
        value_col: str = "y"
    ) -> SpikeDetectionResult:
        """
        Main detection method that combines all detection approaches.
        
        Args:
            df: DataFrame with time series data
            value_col: Column name containing values to analyze
            
        Returns:
            SpikeDetectionResult with detection flags and smoothed values
        """
        if value_col not in df.columns:
            logger.warning(f"Column '{value_col}' not found, returning empty detection")
            empty_series = pd.Series(False, index=df.index)
            return SpikeDetectionResult(
                is_spike=empty_series,
                severity_score=pd.Series(0.0, index=df.index),
                original_values=df[value_col].copy() if value_col in df.columns else pd.Series(0.0, index=df.index),
                smoothed_values=df[value_col].copy() if value_col in df.columns else pd.Series(0.0, index=df.index),
            )
        
        original_values = df[value_col].copy()
        is_spike = pd.Series(False, index=df.index)
        
        # Apply detection methods based on config
        if self.config.detection_method == "statistical":
            is_spike = self.detect_statistical(df, value_col)
        elif self.config.detection_method == "rolling":
            is_spike = self.detect_rolling(df, value_col)
        elif self.config.detection_method == "both":
            stat_spike = self.detect_statistical(df, value_col)
            roll_spike = self.detect_rolling(df, value_col)
            
            if self.config.combination_logic == "AND":
                is_spike = stat_spike & roll_spike
            else:  # OR
                is_spike = stat_spike | roll_spike
        
        # Calculate severity scores
        severity_score = self.calculate_severity(df, is_spike, value_col)
        
        # Smooth or remove spikes
        if self.config.remove_spikes:
            # Remove spikes by setting to NaN (will be handled by preprocessing)
            smoothed_values = original_values.copy()
            smoothed_values[is_spike] = np.nan
        else:
            # Smooth spikes
            smoothed_values = self.smooth_values(df, is_spike, value_col)
        
        # Log detection results
        num_spikes = is_spike.sum()
        if num_spikes > 0:
            logger.info(
                f"Detected {num_spikes} spikes ({num_spikes/len(df)*100:.1f}%) "
                f"using method={self.config.detection_method}"
            )
        
        return SpikeDetectionResult(
            is_spike=is_spike,
            severity_score=severity_score,
            original_values=original_values,
            smoothed_values=smoothed_values,
        )

