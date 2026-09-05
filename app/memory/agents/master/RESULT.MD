Rust algo-trading frameworks, smallest/fastest first:

**Frameworks**
- **Nautilus Trader** — the big one (Python+Cython core, not Rust). Skip if you want pure Rust.
- **TectonicDB** / **DB3** — niche, not really trading.
- **Barrage** — async crypto trading framework (Rust, Binance/OKX, order-book + strategy plugins).
- **Gobbot** — minimal Rust crypto trading bot scaffold.
- **Crypto-botters** — Rust port of pybotters (async exchange clients, Binance/Bybit/bitFlyer).
- **rfq** — minimal async trading engine.

**More "library than framework" (build your own thin layer)**
- **rust_decimal** — precise prices/quantities (mandatory)
- **tokio / async-std** — async runtime
- **serde + serde_json** — exchange messages
- **rustls + tungstenite** — secure WebSocket feeds
- **chrono / time** — timestamps

**Reality check**
There's no dominant Rust equivalent of `ccxt` or `backtrader`. Most Rust traders either:
1. Use **Nautilus Trader** (best full-featured, but you write Python strategies on a Rust-grade engine), or
2. Roll their own thin `tokio + rust_decimal + websocket` core against a specific exchange.

For "small and fast," the pragmatic answer is usually: **Nautilus Trader** for features, or a hand-rolled `tokio` core if you really need pure-Rust minimalism.

What's the use case — crypto or equities, backtesting or live execution? That changes the pick significantly.