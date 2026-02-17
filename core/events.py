"""
Internal event bus for signal propagation.

Decouples signal generation (strategy engine) from signal consumption
(order executor, notifications, logging).

Uses asyncio-native patterns — no external dependencies.

Usage:
    bus = EventBus()
    bus.subscribe(SignalType.STOP_LOSS_HIT, handle_stop_loss)
    await bus.emit(signal)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog

from core.models import SignalType, TradeSignal

logger = structlog.get_logger(__name__)

# Type alias for async event handlers
EventHandler = Callable[[TradeSignal], Coroutine[Any, Any, None]]


class EventBus:
    """
    Simple async event bus for internal signal propagation.

    Supports:
    - Subscribe/unsubscribe by signal type
    - Async handler invocation
    - Error isolation (one handler failure doesn't block others)
    """

    def __init__(self) -> None:
        self._handlers: dict[SignalType, list[EventHandler]] = defaultdict(list)

    def subscribe(self, signal_type: SignalType, handler: EventHandler) -> None:
        """Register a handler for a specific signal type."""
        self._handlers[signal_type].append(handler)
        logger.debug(
            "event_handler_subscribed",
            signal_type=signal_type.value,
            handler=handler.__name__,
        )

    def unsubscribe(self, signal_type: SignalType, handler: EventHandler) -> None:
        """Remove a handler for a specific signal type."""
        handlers = self._handlers.get(signal_type, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug(
                "event_handler_unsubscribed",
                signal_type=signal_type.value,
                handler=handler.__name__,
            )

    async def emit(self, signal: TradeSignal) -> None:
        """
        Emit a signal to all registered handlers.

        Handlers are invoked concurrently via asyncio.gather.
        Individual handler errors are logged but don't propagate —
        other handlers still execute.
        """
        handlers = self._handlers.get(signal.signal_type, [])
        if not handlers:
            logger.debug(
                "event_no_handlers",
                signal_type=signal.signal_type.value,
                ticker=signal.ticker,
            )
            return

        logger.info(
            "event_emitting",
            signal_type=signal.signal_type.value,
            ticker=signal.ticker,
            price=signal.price,
            handler_count=len(handlers),
        )

        # Run all handlers concurrently, isolating errors
        results = await asyncio.gather(
            *(self._safe_invoke(handler, signal) for handler in handlers),
            return_exceptions=True,
        )

        # Log any handler failures
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "event_handler_error",
                    signal_type=signal.signal_type.value,
                    ticker=signal.ticker,
                    handler=handlers[i].__name__,
                    error=str(result),
                )

    async def _safe_invoke(self, handler: EventHandler, signal: TradeSignal) -> None:
        """Invoke a handler with error isolation."""
        try:
            await handler(signal)
        except Exception:
            # Re-raise so asyncio.gather captures it
            raise

    def clear(self) -> None:
        """Remove all handlers (useful for testing)."""
        self._handlers.clear()
