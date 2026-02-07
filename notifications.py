import requests
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_message(self, message: str):
        """Send a simple text message to Discord."""
        if not self.webhook_url:
            return
            
        try:
            payload = {"content": message}
            requests.post(self.webhook_url, json=payload)
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")

    def send_trade_alert(self, symbol: str, direction: str, price: float, pattern: str):
        """Send a formatted trade alert."""
        if not self.webhook_url:
            return
            
        # Green for Calls/Long, Red for Puts/Short
        color = 5763719 if "CALL" in direction.upper() or "LONG" in direction.upper() else 15548997
        
        embed = {
            "title": f"🚨 Trade Alert: {symbol}",
            "description": f"**{direction.upper()}** triggered by {pattern}",
            "color": color,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Time", "value": datetime.now().strftime("%H:%M:%S"), "inline": True}
            ],
            "footer": {"text": "Swing Trading Bot"}
        }
        
        try:
            payload = {"embeds": [embed]}
            requests.post(self.webhook_url, json=payload)
        except Exception as e:
            logger.error(f"Failed to send Discord trade alert: {e}")