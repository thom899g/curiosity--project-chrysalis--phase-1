"""
Component 1: Perception & Validation Layer
The system's sensory apparatus - ingests and sanitizes reality with redundancy checks.
"""
import logging
import asyncio
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import requests
import ccxt
from sklearn.ensemble import IsolationForest
import numpy as np
from .data_schema import TreasuryState
from .config import (
    FIREBASE_CLIENT,
    ORACLE_SOURCES,
    ANOMALY_DETECTION_WINDOW,
    MAX_ORACLE_DISCREPANCY_PCT,
    CIRCUIT_BREAKER_THRESHOLD
)

logger = logging.getLogger(__name__)


class PerceptionValidationLayer:
    """Validated data ingestion with anomaly detection and circuit breakers"""
    
    def __init__(self, firebase_client=None):
        self.firebase = firebase_client or FIREBASE_CLIENT
        self.db = self.firebase.firestore()
        self.anomaly_detector = IsolationForest(
            contamination=0.05,
            random_state=42,
            n_estimators=100
        )
        self.data_buffer = []  # For anomaly detection training
        self.circuit_breaker_triggered = False
        
    def _fetch_treasury_balance(self) -> Dict[str, float]:
        """Fetch treasury balances from configured APIs with retry logic"""
        balances = {}
        # Simulated - replace with actual API calls
        api_endpoints = [
            "https://api.treasury.example.com/balances",
            "https://backup.treasury.example.com/v1/balance"
        ]
        
        for endpoint in api_endpoints:
            try:
                response = requests.get(
                    endpoint,
                    timeout=10,
                    headers={'User-Agent': 'AutonomyEngine/1.0'}
                )
                if response.status_code == 200:
                    data = response.json()
                    # Extract balances - adapt to actual API structure
                    balances.update(data.get('balances', {}))
                    logger.info(f"Fetched balances from {endpoint}")
                    break
            except (requests.RequestException, KeyError) as e:
                logger.warning(f"Failed to fetch from {endpoint}: {e}")
                continue
        
        if not balances:
            logger.error("All treasury balance APIs failed")
            raise ConnectionError("Could not fetch treasury balances")
            
        return balances
    
    def _fetch_market_data(self) -> Dict[str, Any]:
        """Fetch market data from multiple exchanges with redundancy"""
        market_data = {}
        price_discrepancies = {}
        
        # Configure exchange instances
        exchanges = {
            'binance': ccxt.binance(),
            'coinbase': ccxt.coinbase(),
            'kraken': ccxt.kraken()
        }
        
        for exchange_name, exchange in exchanges.items():
            try:
                exchange.load_markets()
                # Fetch prices for relevant assets
                tickers = exchange.fetch_tickers(['BTC/USDT', 'ETH/USDT', 'USDC/USDT'])
                prices = {symbol: ticker['last'] for symbol, ticker in tickers.items()}
                market_data[exchange_name] = {
                    'prices': prices,
                    'timestamp': datetime.utcnow().isoformat()
                }
                logger.debug(f"Fetched prices from {exchange_name}")
            except (ccxt.NetworkError, ccxt.ExchangeError) as e:
                logger.warning(f"Exchange {exchange_name} failed: {e}")
                continue
        
        # Cross-check prices for discrepancies
        if len(market_data) >= 2:
            primary_prices = list(market_data.values())[0]['prices']
            for exchange, data in list(market_data.items())[1:]:
                for symbol, price in data['prices'].items():
                    if symbol in primary_prices:
                        discrepancy = abs(price - primary_prices[symbol]) / primary_prices[symbol] * 100
                        if discrepancy > MAX_ORACLE_DISCREPANCY_PCT:
                            price_discrepancies[f"{exchange}_{symbol}"] = discrepancy
        
        return {
            'sources': market_data,
            'consensus_prices': self._calculate_consensus_prices(market_data),
            'discrepancies': price_discrepancies
        }
    
    def _calculate_consensus_prices(self, market_data: Dict) -> Dict[str, float]:
        """Calculate median prices across exchanges"""
        all_prices = {}
        for exchange_data in market_data.values():
            for symbol, price in exchange_data['prices'].items():
                all_prices.setdefault(symbol, []).append(price)
        
        consensus = {}
        for symbol, prices in all_prices.items():
            if len(prices) >= 2:  # Require at least 2 sources
                consensus[symbol] = np.median(prices)
            else:
                consensus[symbol] = prices[0] if prices else 0
                
        return consensus
    
    def _detect_anomalies(self, data_vector: List[float]) -> Tuple[bool, float]:
        """Detect anomalous data using Isolation Forest"""
        if len(self.data_buffer) < ANOMALY_DETECTION_WINDOW:
            # Not enough historical data yet
            self.data_buffer.append(data_vector)
            return False, 0.0
        
        # Train on historical data
        X_train = np.array(self.data_buffer[-ANOMALY_DETECTION_WINDOW:])
        
        try:
            self.anomaly_detector.fit(X_train)
            anomaly_score = self.anomaly_detector.score_samples([data_vector])[0]
            is_anomaly = anomaly_score < -0.5  # Threshold
            
            # Update buffer (circular)
            if len(self.data_buffer) >= ANOMALY_DETECTION_WINDOW * 2:
                self.data_buffer = self.data_buffer[-ANOMALY_DETECTION_WINDOW:]
            self.data_buffer.append(data_vector)
            
            return is_anomaly, float(anomaly_score)
            
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return False, 0.0
    
    def _calculate_confidence_score(self, data: Dict) -> float:
        """Calculate overall data confidence score (0.0-1.0)"""
        confidence = 1.0
        
        # Penalize for missing data sources
        if not data.get('balances'):
            confidence *= 0.5
            
        # Penalize for price discrepancies
        discrepancies = data.get('market_data', {}).get('discrepancies', {})
        if discrepancies:
            max_discrepancy = max(discrepancies.values()) / 100
            confidence *= max(0.5, 1.0 - max_discrepancy)
        
        # Penalize for anomalies
        if data.get('anomaly_flags'):
            confidence *= 0.7
            
        return round(confidence, 4)
    
    def check_circuit_breaker(self, anomaly_count: int, total_metrics: int) -> bool:
        """Trigger circuit breaker if too many anomalies"""
        anomaly_ratio = anomaly_count / total_metrics if total_metrics > 0 else 0
        should_trigger = anomaly_ratio > CIRCUIT_BREAKER_THRESHOLD
        
        if should_trigger and not self.circuit_breaker_triggered:
            logger.critical(f"Circuit breaker triggered: {anomaly_ratio:.1%} anomalies")
            self.circuit_breaker_triggered = True
            
            # Log to Firestore
            self.db.collection('control').document('emergency').set({
                'halted': True,
                'reason': f'Data anomaly ratio {anomaly_ratio:.1%} exceeds threshold',
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Could also trigger Telegram alert here
            
        return should_trigger
    
    async def get_validated_state(self) -> TreasuryState:
        """Main entry point: fetch and validate all data sources"""
        logger.info("Starting data validation cycle")
        
        try:
            # Fetch data from all sources
            balances = self._fetch_treasury_balance()
            market_data = self._fetch_market_data()
            
            # Prepare for anomaly detection
            data_vector = []
            anomaly_flags = []
            
            # Extract numerical features for anomaly detection
            if balances:
                total_balance = sum(balances.values())
                data_vector.append(total_balance)
            
            if market_data.get('consensus_prices'):
                btc_price = market_data['consensus_prices'].get('BTC/USDT', 0)
                data_vector.append(btc_price)
            
            # Detect anomalies
            if data_vector:
                is_anomaly, anomaly_score = self._detect_anomalies(data_vector)
                if is_anomaly:
                    anomaly_flags.append(f"anomaly_score_{anomaly_score:.2f}")
            
            # Check circuit breaker conditions
            total_metrics = len(data_vector)
            anomaly_count = len(anomaly_flags)
            
            if self.check_circuit_breaker(anomaly_count, total_metrics):
                raise RuntimeError("Circuit breaker triggered - data validation halted")
            
            # Calculate confidence score
            raw_data = {
                'balances': balances,
                'market_data': market_data,
                'anomaly_flags': anomaly_flags
            }
            confidence = self._calculate_confidence_score(raw_data)
            
            # Create validated TreasuryState
            treasury_state = TreasuryState(
                balances=balances,
                market_data=market_data,
                confidence_score=confidence,
                anomaly_flags=anomaly_flags,
                oracle_discrepancies=market_data.get('discrepancies', {})
            )
            
            # Save to Firestore
            doc_ref = self.db.collection('treasury_state').document()
            doc_ref.set(treasury_state.dict())
            
            logger.info(f"Data validation