// Attempt strategy. Replace this placeholder with the mechanism.
//
// API (see the engine repo's scripts/rhai/ for working examples):
//   init(cfg)      -> state map (`this` in on_candle); cfg.script.* = preset knobs
//   on_candle(c)   -> array of opportunities; c has tf/ts/open/high/low/close
//   hist(tf)       -> history handle: .len, .close(i), .high(i), .low(i) (0 = current)
//   opp(name, tf, dir, ts) -> opportunity; set .entry, .stop, .score (and the
//                    engine derives the target from rr, or set .target yourself)

fn init(cfg) {
    #{}
}

fn on_candle(c) {
    // Placeholder: no trades. An empty eval proves the plumbing.
    []
}
