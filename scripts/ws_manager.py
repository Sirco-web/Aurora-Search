"""
WebSocket manager for live crawler visualization.
Handles real-time broadcasting of crawler events to connected clients.
"""

import json
import threading
from queue import Queue
from typing import Set

class WebSocketManager:
    """Manages WebSocket connections and broadcasts crawler events."""
    
    def __init__(self):
        self.clients: Set = set()
        self.event_queue = Queue()
        self.lock = threading.Lock()
        self.max_queue_size = 10000
        
    def register_client(self, websocket):
        """Register a new client connection."""
        with self.lock:
            self.clients.add(websocket)
        print(f"✅ Client connected. Total: {len(self.clients)}")
    
    def unregister_client(self, websocket):
        """Unregister a client connection."""
        with self.lock:
            self.clients.discard(websocket)
        print(f"❌ Client disconnected. Total: {len(self.clients)}")
    
    async def broadcast(self, event: dict):
        """Broadcast event to all connected clients."""
        message = json.dumps(event)
        
        with self.lock:
            clients_copy = list(self.clients)
        
        for client in clients_copy:
            try:
                await client.send_text(message)
            except Exception as e:
                print(f"Error sending to client: {e}")
                self.unregister_client(client)
    
    def queue_event(self, event: dict):
        """Queue an event to be broadcast (for sync crawlers)."""
        if self.event_queue.qsize() < self.max_queue_size:
            self.event_queue.put(event)


# Global instance
ws_manager = WebSocketManager()


# Helper functions for crawler to use
async def broadcast_crawled(url: str, depth: int = 0, title: str = "", links_found: int = 0):
    """Broadcast that a URL was crawled."""
    await ws_manager.broadcast({
        "type": "crawled",
        "url": url,
        "depth": depth,
        "title": title or url,
        "links_found": links_found
    })


async def broadcast_found(from_url: str, to_url: str, depth: int = 0):
    """Broadcast that a new URL was discovered."""
    await ws_manager.broadcast({
        "type": "found",
        "from_url": from_url,
        "url": to_url,
        "depth": depth
    })


async def broadcast_failed(url: str, reason: str = "unknown"):
    """Broadcast that a URL failed to crawl."""
    await ws_manager.broadcast({
        "type": "failed",
        "url": url,
        "reason": reason
    })


async def broadcast_queue_update(queue: list):
    """Broadcast current queue status."""
    await ws_manager.broadcast({
        "type": "queue_update",
        "queue": queue[:20]  # Send only first 20 items
    })


async def broadcast_status(status: str, message: str = ""):
    """Broadcast crawler status update."""
    await ws_manager.broadcast({
        "type": "status",
        "status": status,
        "message": message
    })
